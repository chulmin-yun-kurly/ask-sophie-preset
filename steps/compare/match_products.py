"""
비교 질문별 매칭 상품을 선정합니다.
1) prepared_data와 compare_prepared 임베딩 생성
2) 질문별 cosine similarity top-K(=COMPARE_CANDIDATE_COUNT) 후보 추출
3) LLM 필터로 최종 5~10개 선정 + 제외 사유 요약
"""
import json
import asyncio
import sys
import time
import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from config import (
    MODEL_LIGHT,
    MODEL_EMBEDDING,
    EMBEDDING_BATCH_SIZE,
    COMPARE_CANDIDATE_COUNT,
    COMPARE_FINAL_MIN,
    COMPARE_FINAL_MAX,
    COMPARE_MAX_CONCURRENT,
    TEMP_COMPARE_MATCH,
)
from llm_client import load_prompt, build_system_prompt, chat_json, get_embeddings
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

MAX_RETRY_ROUNDS = 3


def _topic_keyword_text(raw) -> str:
    """topic_keyword 컬럼 값을 사람이 읽을 수 있는 문자열로 변환."""
    if raw is None:
        return ''
    if isinstance(raw, list):
        return ', '.join(str(x) for x in raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return ''
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return ', '.join(str(x) for x in parsed)
        except (json.JSONDecodeError, TypeError):
            pass
        return s
    return str(raw)


def build_product_embedding_text(row) -> str:
    origin = row.get('origin', '') or ''
    kw = _topic_keyword_text(row.get('topic_keyword', ''))
    return (
        f"{row.get('content_nm', '')}\n"
        f"원산지: {origin}\n"
        f"핵심설명: {row.get('key_description', '')}\n"
        f"키워드: {kw}"
    )


def build_candidate_block(content_no: int, prod: dict) -> str:
    """LLM 후보 목록에 들어갈 상품 요약 블록."""
    origin = prod.get('origin', '') or ''
    kw = _topic_keyword_text(prod.get('topic_keyword', ''))
    return (
        f"[content_no={content_no}]\n"
        f"상품명: {prod.get('content_nm', '')}\n"
        f"원산지: {origin}\n"
        f"핵심설명: {prod.get('key_description', '')}\n"
        f"키워드: {kw}"
    )


async def run_filter(question: str, candidates_text: str) -> dict:
    """LLM으로 최종 상품을 필터링합니다."""
    system_prompt = build_system_prompt(
        load_prompt('compare/match_system.txt').format(
            final_min=COMPARE_FINAL_MIN,
            final_max=COMPARE_FINAL_MAX,
        )
    )
    user_prompt = load_prompt('compare/match_user.txt').format(
        question=question,
        candidates_text=candidates_text,
        final_min=COMPARE_FINAL_MIN,
        final_max=COMPARE_FINAL_MAX,
    )
    return await chat_json(
        MODEL_LIGHT, system_prompt, user_prompt, temperature=TEMP_COMPARE_MATCH
    )


async def process_questions(questions: list, prod_lookup: dict, candidates_map: dict) -> dict:
    """질문별 LLM 필터를 배치(동시성) 실행."""
    semaphore = asyncio.Semaphore(COMPARE_MAX_CONCURRENT)
    results: dict[int, dict] = {}

    async def _one(q_idx: int):
        async with semaphore:
            q = questions[q_idx]
            cand_nos = candidates_map[q_idx]
            candidates_text = "\n\n".join(
                build_candidate_block(cno, prod_lookup[cno]) for cno in cand_nos
            )
            try:
                parsed = await run_filter(q['question'], candidates_text)
            except Exception as e:
                print(f"   ⚠ [{q['id']}] LLM 필터 실패: {e}")
                return

            selected_raw = parsed.get('selected', [])
            selected_nos: list[int] = []
            allowed = set(cand_nos)
            for item in selected_raw:
                if not isinstance(item, dict):
                    continue
                try:
                    cno = int(item.get('content_no'))
                except (TypeError, ValueError):
                    continue
                if cno in allowed and cno not in selected_nos:
                    selected_nos.append(cno)
                if len(selected_nos) >= COMPARE_FINAL_MAX:
                    break

            if len(selected_nos) < COMPARE_FINAL_MIN:
                print(
                    f"   ⚠ [{q['id']}] 선정 상품 {len(selected_nos)}개 "
                    f"(하한 {COMPARE_FINAL_MIN}) → 재시도 대상"
                )
                return

            results[q_idx] = {
                'content_list': selected_nos,
                'match_rationale': parsed.get('excluded_rationale', '') or '',
            }
            print(f"   [{q['id']}] 최종 {len(selected_nos)}개 선정")

    await asyncio.gather(*[_one(i) for i in range(len(questions))])
    return results


async def main():
    # 1. 시트 읽기
    print("1. 시트 읽는 중...")
    df_prepared = read_google_sheet(sheet_name='prepared_data')
    df_compare = read_google_sheet(sheet_name='compare_prepared')
    print(f"   prepared_data: {df_prepared.shape}")
    print(f"   compare_prepared: {df_compare.shape}")

    if df_compare.empty:
        print("✗ compare_prepared 시트가 비어 있습니다. prepare 단계를 먼저 실행하세요.")
        sys.exit(1)

    # content_no → 상품 정보 lookup
    prod_lookup: dict[int, dict] = {}
    prod_order: list[int] = []  # 임베딩 인덱스와 정렬 일치
    for _, row in df_prepared.iterrows():
        try:
            cno = int(row['content_no'])
        except (TypeError, ValueError, KeyError):
            continue
        prod_lookup[cno] = {
            'content_nm': row.get('content_nm', ''),
            'origin': row.get('origin', ''),
            'key_description': row.get('key_description', ''),
            'topic_keyword': row.get('topic_keyword', ''),
        }
        prod_order.append(cno)

    if not prod_order:
        print("✗ prepared_data에서 유효한 상품을 찾지 못했습니다.")
        sys.exit(1)

    # 2. 상품 임베딩 생성
    print("\n2. 상품 임베딩 생성 중...")
    prod_texts = [
        build_product_embedding_text({'content_nm': prod_lookup[c]['content_nm'],
                                      'origin': prod_lookup[c]['origin'],
                                      'key_description': prod_lookup[c]['key_description'],
                                      'topic_keyword': prod_lookup[c]['topic_keyword']})
        for c in prod_order
    ]
    prod_embeddings = await get_embeddings(prod_texts, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
    prod_emb = np.array(prod_embeddings)
    print(f"   상품 임베딩 Shape: {prod_emb.shape}")

    # 3. 질문 임베딩 생성
    print("\n3. 질문 임베딩 생성 중...")
    questions = []
    for _, row in df_compare.iterrows():
        questions.append({'id': row['id'], 'question': row['question']})
    q_texts = [q['question'] for q in questions]
    q_embeddings = await get_embeddings(q_texts, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
    q_emb = np.array(q_embeddings)
    print(f"   질문 임베딩 Shape: {q_emb.shape}")

    # 4. 질문별 top-K 후보 추출
    top_k = min(COMPARE_CANDIDATE_COUNT, len(prod_order))
    print(f"\n4. 질문별 top-{top_k} 후보 추출 중...")
    sim = cosine_similarity(q_emb, prod_emb)
    candidates_map: dict[int, list[int]] = {}
    for i in range(len(questions)):
        order = np.argsort(sim[i])[::-1][:top_k]
        candidates_map[i] = [prod_order[j] for j in order]

    # 5. LLM 필터 (재시도 최대 3라운드)
    print(f"\n5. LLM 필터 실행 (동시 {COMPARE_MAX_CONCURRENT}개)...")
    start = time.time()
    all_results: dict[int, dict] = {}
    for attempt in range(1, MAX_RETRY_ROUNDS + 1):
        pending = [i for i in range(len(questions)) if i not in all_results]
        if not pending:
            break
        label = f"라운드 {attempt}/{MAX_RETRY_ROUNDS}" if attempt > 1 else "처리"
        print(f"\n   {label}: {len(pending)}건...")
        pending_questions = [questions[i] for i in pending]
        pending_candidates = {p_idx: candidates_map[orig_idx] for p_idx, orig_idx in enumerate(pending)}
        round_results = await process_questions(pending_questions, prod_lookup, pending_candidates)
        for local_idx, value in round_results.items():
            all_results[pending[local_idx]] = value

    elapsed = time.time() - start
    print(f"\n   필터 완료: {elapsed:.1f}초")

    # 검증
    missing = [questions[i]['id'] for i in range(len(questions)) if i not in all_results]
    if missing:
        print(f"\n✗ {MAX_RETRY_ROUNDS}회 재시도 후에도 {len(missing)}건 누락: {missing}")
        sys.exit(1)

    # 6. 결과 반영 후 저장
    print("\n6. 결과 저장 중...")
    df_compare['candidate_list'] = [
        json.dumps(candidates_map[i], ensure_ascii=False) for i in range(len(questions))
    ]
    df_compare['content_list'] = [
        json.dumps(all_results[i]['content_list'], ensure_ascii=False)
        for i in range(len(questions))
    ]
    df_compare['match_rationale'] = [
        all_results[i]['match_rationale'] for i in range(len(questions))
    ]

    write_dataframe_to_sheet(df_compare, sheet_name='compare_prepared')
    print(f"Successfully wrote {len(df_compare)} rows to 'compare_prepared' sheet")


if __name__ == '__main__':
    asyncio.run(main())
