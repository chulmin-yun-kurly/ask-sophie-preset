"""
qna_group의 각 그룹에 대해 연관 추천(suggest)을 생성합니다.

후보 풀: qna_group 대표 질문 + compare_qna 비교 질문.
임베딩으로 후보를 축소한 뒤, LLM으로 최종 SUGGEST_COUNT 개를 선정합니다.
"""
import json
import asyncio
import numpy as np
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from config import MODEL_LIGHT, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE, CLUSTER_MAX_CONCURRENT, TEMP_SUGGEST
from llm_client import load_prompt, build_system_prompt, chat_json, get_embeddings
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

SUGGEST_COUNT = 10
CANDIDATE_COUNT = 50


def build_content_map(df_prepared: pd.DataFrame) -> dict:
    """prepared_data에서 content_no → key_description 매핑을 생성합니다."""
    content_map = {}
    for _, row in df_prepared.iterrows():
        cno = int(row['content_no'])
        content_map[cno] = row.get('key_description', '')
    return content_map


def get_content_descriptions(content_list_json: str, content_map: dict) -> str:
    """content_list의 key_description을 모아 텍스트로 만듭니다."""
    try:
        content_nos = json.loads(content_list_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    descs = []
    for cno in content_nos:
        desc = content_map.get(int(cno), '')
        if desc:
            descs.append(desc)
    return " / ".join(descs)


async def main():
    # 1. 시트 읽기
    print("1. 시트 읽는 중...")
    df = read_google_sheet(sheet_name='qna_group')
    print(f"   qna_group: {df.shape}")

    df_prepared = read_google_sheet(sheet_name='prepared_data')
    content_map = build_content_map(df_prepared)
    print(f"   상품 매핑: {len(content_map)}개")

    # compare_qna는 후보 풀에만 추가 (없거나 비어 있으면 스킵)
    try:
        df_compare = read_google_sheet(sheet_name='compare_qna')
        print(f"   compare_qna: {df_compare.shape}")
    except Exception:
        df_compare = None
        print("   compare_qna: 없음 (스킵)")

    # 타깃: qna_group 각 그룹 (suggest를 채울 대상)
    targets = []
    for idx, row in df.iterrows():
        targets.append({
            'df_idx': idx,
            'id': row.get('id', ''),
            'representative': row['representative'],
            'answer_intro': row.get('answer_intro', ''),
            'subtopics': row.get('subtopics', '[]'),
            'answer_outro': row.get('answer_outro', ''),
            'content_desc': get_content_descriptions(
                row.get('content_list', '[]'), content_map
            ),
        })

    # 후보 풀: qna_group 항목 + compare_qna 항목 (앞부분 = qna_group)
    pool = [{'id': t['id'], 'text': t['representative']} for t in targets]
    if df_compare is not None:
        for _, row in df_compare.iterrows():
            cid = str(row.get('id', '')).strip()
            text = str(row.get('question', '')).strip()
            if cid and text:
                pool.append({'id': cid, 'text': text})

    print(f"   타깃 {len(targets)}개, 후보 풀 {len(pool)}개")

    # 2. 임베딩 생성 (풀 전체)
    print("\n2. 임베딩 생성 중...")
    pool_texts = [p['text'] for p in pool]
    pool_embeddings = await get_embeddings(pool_texts, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
    pool_emb = np.array(pool_embeddings)
    print(f"   풀 임베딩 Shape: {pool_emb.shape}")

    # 타깃 임베딩 = 풀의 앞부분(qna_group 구간)
    target_emb = pool_emb[:len(targets)]

    # 3. 후보 선정 (cosine similarity top-K, 자기 자신 제외)
    print(f"\n3. 그룹별 후보 {CANDIDATE_COUNT}개 선정 중...")
    sim_matrix = cosine_similarity(target_emb, pool_emb)

    candidates = {}
    for i in range(len(targets)):
        sims = sim_matrix[i].copy()
        sims[i] = -1  # 자기 자신(qna_group은 풀의 앞부분이라 인덱스 동일)
        top_indices = np.argsort(sims)[::-1][:CANDIDATE_COUNT]
        candidates[i] = top_indices.tolist()

    # 4. LLM으로 연관 추천 선정
    print(f"\n4. LLM으로 연관 추천 {SUGGEST_COUNT}개 선정 중...")

    system_prompt = build_system_prompt(load_prompt('qna/suggest_system.txt'))
    user_template = load_prompt('qna/suggest_user.txt')

    suggest_map = {}
    semaphore = asyncio.Semaphore(CLUSTER_MAX_CONCURRENT)

    async def process_group(group_idx):
        async with semaphore:
            t = targets[group_idx]
            cand_indices = candidates[group_idx]

            cand_text = "\n".join(
                f"  {j}. [{pool[ci]['id']}] {pool[ci]['text']}"
                for j, ci in enumerate(cand_indices)
            )

            content_desc_section = ""
            if t['content_desc']:
                content_desc_section = f"\n상품 특성: {t['content_desc']}"

            # answer_intro + subtopics + answer_outro를 합쳐서 answer 텍스트 구성
            answer_parts = []
            if t['answer_intro']:
                answer_parts.append(t['answer_intro'])
            try:
                subtopics = json.loads(t['subtopics']) if isinstance(t['subtopics'], str) else t['subtopics']
            except (json.JSONDecodeError, TypeError):
                subtopics = []
            for st_item in subtopics:
                if st_item.get('subtitle'):
                    answer_parts.append(st_item['subtitle'])
                if st_item.get('description'):
                    answer_parts.append(st_item['description'])
            if t['answer_outro']:
                answer_parts.append(t['answer_outro'])
            answer_text = ' '.join(answer_parts)

            user_prompt = user_template.format(
                suggest_count=SUGGEST_COUNT,
                representative=t['representative'],
                answer=answer_text,
                content_desc_section=content_desc_section,
                cand_text=cand_text,
            )

            parsed = await chat_json(MODEL_LIGHT, system_prompt, user_prompt, temperature=TEMP_SUGGEST)

            picked_indices = parsed.get('suggest', [])
            suggest_ids = []
            for pi in picked_indices:
                if isinstance(pi, int) and 0 <= pi < len(cand_indices):
                    suggest_ids.append(pool[cand_indices[pi]]['id'])

            suggest_map[group_idx] = suggest_ids[:SUGGEST_COUNT]

    tasks = [process_group(i) for i in range(len(targets))]
    await asyncio.gather(*tasks)

    print(f"   완료 ({len(suggest_map)}개 그룹)")

    # 5. 결과 저장
    print("\n5. 결과 저장 중...")
    df['suggest'] = [
        json.dumps(suggest_map.get(i, []), ensure_ascii=False)
        for i in range(len(df))
    ]

    # 요약 출력
    for i, (_, row) in enumerate(df.iterrows()):
        suggests = json.loads(row['suggest']) if row['suggest'] else []
        print(f"   [{row.get('id', '')}] {row['representative']}")
        print(f"     → suggest: {suggests}")

    write_dataframe_to_sheet(df, sheet_name='qna_group')
    print(f"\nSuccessfully wrote {len(df)} rows to 'qna_group' sheet")


if __name__ == '__main__':
    asyncio.run(main())
