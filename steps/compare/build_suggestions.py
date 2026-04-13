"""
compare_qna의 각 비교 질문에 대해 연관 추천(suggest)을 생성합니다.

suggest 후보 풀: qna_group의 대표 질문 + compare_qna의 비교 질문.
  (product 질문은 대상에서 제외)

임베딩으로 top-K 후보를 뽑고, LLM으로 최종 COMPARE_SUGGEST_COUNT 개를 선정합니다.
결과는 compare_qna 시트의 `suggest` 컬럼에 JSON 배열로 저장됩니다.
"""
import json
import asyncio
import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from config import (
    MODEL_LIGHT,
    MODEL_EMBEDDING,
    EMBEDDING_BATCH_SIZE,
    COMPARE_MAX_CONCURRENT,
    COMPARE_SUGGEST_COUNT,
    COMPARE_SUGGEST_CANDIDATE_COUNT,
    TEMP_SUGGEST,
)
from llm_client import load_prompt, build_system_prompt, chat_json, get_embeddings
from sheet_reader import read_google_sheet, write_dataframe_to_sheet


def _stringify(v) -> str:
    if v is None:
        return ''
    return str(v).strip()


def build_candidate_pool(df_qna: pd.DataFrame, df_compare: pd.DataFrame) -> list[dict]:
    """qna_group + compare_qna 질문을 하나의 후보 풀로 구성."""
    pool = []
    for _, row in df_qna.iterrows():
        qid = _stringify(row.get('id', ''))
        text = _stringify(row.get('representative', ''))
        if qid and text:
            pool.append({'id': qid, 'text': text, 'source': 'qna'})
    for _, row in df_compare.iterrows():
        qid = _stringify(row.get('id', ''))
        text = _stringify(row.get('question', ''))
        if qid and text:
            pool.append({'id': qid, 'text': text, 'source': 'compare'})
    return pool


async def main():
    # 1. 시트 읽기
    print("1. 시트 읽는 중...")
    df_compare = read_google_sheet(sheet_name='compare_qna')
    print(f"   compare_qna: {df_compare.shape}")
    df_qna = read_google_sheet(sheet_name='qna_group')
    print(f"   qna_group: {df_qna.shape}")

    if df_compare.empty:
        print("✗ compare_qna 시트가 비어 있습니다. answer 단계를 먼저 실행하세요.")
        return

    # 2. 후보 풀 구성
    pool = build_candidate_pool(df_qna, df_compare)
    pool_id_to_idx = {p['id']: i for i, p in enumerate(pool)}
    print(f"   후보 풀: {len(pool)}개 (qna {sum(1 for p in pool if p['source']=='qna')}, "
          f"compare {sum(1 for p in pool if p['source']=='compare')})")

    # 3. 임베딩 생성 (풀 전체)
    print("\n2. 후보 풀 임베딩 생성 중...")
    pool_texts = [p['text'] for p in pool]
    pool_embeddings = await get_embeddings(pool_texts, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
    pool_emb = np.array(pool_embeddings)
    print(f"   풀 임베딩 Shape: {pool_emb.shape}")

    # 4. 비교 질문 임베딩 (풀 내 compare 항목의 임베딩을 그대로 재사용)
    print("\n3. 비교 질문별 후보 선정 및 LLM 필터...")
    targets = []  # 각 compare_qna 행에 대응
    for _, row in df_compare.iterrows():
        qid = _stringify(row.get('id', ''))
        text = _stringify(row.get('question', ''))
        pool_idx = pool_id_to_idx.get(qid)
        targets.append({'id': qid, 'text': text, 'pool_idx': pool_idx})

    # cosine similarity: 각 target vs 풀 전체
    target_pool_indices = [t['pool_idx'] for t in targets if t['pool_idx'] is not None]
    if len(target_pool_indices) != len(targets):
        missing = [t['id'] for t in targets if t['pool_idx'] is None]
        print(f"✗ 풀에서 찾지 못한 비교 질문이 있습니다: {missing}")
        return

    target_emb = pool_emb[target_pool_indices]
    sim_matrix = cosine_similarity(target_emb, pool_emb)

    top_k = min(COMPARE_SUGGEST_CANDIDATE_COUNT, len(pool))

    # 5. LLM 필터 (qna/suggest 프롬프트 재사용)
    system_prompt = build_system_prompt(load_prompt('qna/suggest_system.txt'))
    user_template = load_prompt('qna/suggest_user.txt')

    suggest_map: dict[int, list[str]] = {}
    semaphore = asyncio.Semaphore(COMPARE_MAX_CONCURRENT)

    async def process_target(t_idx: int):
        async with semaphore:
            t = targets[t_idx]
            sims = sim_matrix[t_idx].copy()
            # 자기 자신 제외
            sims[t['pool_idx']] = -1
            cand_indices = np.argsort(sims)[::-1][:top_k].tolist()

            cand_text = "\n".join(
                f"  {j}. [{pool[ci]['id']}] {pool[ci]['text']}"
                for j, ci in enumerate(cand_indices)
            )

            user_prompt = user_template.format(
                suggest_count=COMPARE_SUGGEST_COUNT,
                representative=t['text'],
                answer='',  # 비교 질문에서는 답변 텍스트 생략
                content_desc_section='',
                cand_text=cand_text,
            )

            try:
                parsed = await chat_json(
                    MODEL_LIGHT, system_prompt, user_prompt, temperature=TEMP_SUGGEST
                )
            except Exception as e:
                print(f"   ⚠ [{t['id']}] suggest LLM 실패: {e}")
                suggest_map[t_idx] = []
                return

            picked_indices = parsed.get('suggest', [])
            suggest_ids: list[str] = []
            seen: set[str] = set()
            for pi in picked_indices:
                if not isinstance(pi, int):
                    continue
                if 0 <= pi < len(cand_indices):
                    sid = pool[cand_indices[pi]]['id']
                    if sid not in seen:
                        suggest_ids.append(sid)
                        seen.add(sid)
                if len(suggest_ids) >= COMPARE_SUGGEST_COUNT:
                    break

            suggest_map[t_idx] = suggest_ids

    await asyncio.gather(*[process_target(i) for i in range(len(targets))])
    print(f"   완료 ({len(suggest_map)}개)")

    # 6. 결과 저장
    print("\n4. 결과 저장 중...")
    df_compare['suggest'] = [
        json.dumps(suggest_map.get(i, []), ensure_ascii=False)
        for i in range(len(df_compare))
    ]

    for i, row in df_compare.iterrows():
        sids = json.loads(row['suggest']) if row['suggest'] else []
        print(f"   [{row.get('id', '')}] {row.get('question', '')}")
        print(f"     → suggest({len(sids)}): {sids}")

    write_dataframe_to_sheet(df_compare, sheet_name='compare_qna')
    print(f"\nSuccessfully wrote {len(df_compare)} rows to 'compare_qna' sheet")


if __name__ == '__main__':
    asyncio.run(main())
