"""
qna_group의 각 그룹에 대해 연관 추천(suggest)을 생성합니다.
임베딩으로 후보를 축소한 뒤, LLM으로 최종 5개를 선정합니다.
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

    # 그룹 정보 준비
    groups = []
    for idx, row in df.iterrows():
        groups.append({
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

    print(f"   총 {len(groups)}개 그룹")

    # 2. 임베딩 생성
    print("\n2. 임베딩 생성 중...")
    texts = [g['representative'] for g in groups]
    embeddings = await get_embeddings(texts, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
    emb_matrix = np.array(embeddings)
    print(f"   임베딩 Shape: {emb_matrix.shape}")

    # 3. 후보 선정 (cosine similarity top-K)
    print(f"\n3. 그룹별 후보 {CANDIDATE_COUNT}개 선정 중...")
    sim_matrix = cosine_similarity(emb_matrix)

    candidates = {}
    for i in range(len(groups)):
        sims = sim_matrix[i].copy()
        sims[i] = -1  # 자기 자신 제외
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
            g = groups[group_idx]
            cand_indices = candidates[group_idx]

            cand_text = "\n".join(
                f"  {j}. [{groups[ci]['id']}] {groups[ci]['representative']}"
                for j, ci in enumerate(cand_indices)
            )

            content_desc_section = ""
            if g['content_desc']:
                content_desc_section = f"\n상품 특성: {g['content_desc']}"

            # answer_intro + subtopics + answer_outro를 합쳐서 answer 텍스트 구성
            answer_parts = []
            if g['answer_intro']:
                answer_parts.append(g['answer_intro'])
            try:
                subtopics = json.loads(g['subtopics']) if isinstance(g['subtopics'], str) else g['subtopics']
            except (json.JSONDecodeError, TypeError):
                subtopics = []
            for st_item in subtopics:
                if st_item.get('subtitle'):
                    answer_parts.append(st_item['subtitle'])
                if st_item.get('description'):
                    answer_parts.append(st_item['description'])
            if g['answer_outro']:
                answer_parts.append(g['answer_outro'])
            answer_text = ' '.join(answer_parts)

            user_prompt = user_template.format(
                suggest_count=SUGGEST_COUNT,
                representative=g['representative'],
                answer=answer_text,
                content_desc_section=content_desc_section,
                cand_text=cand_text,
            )

            parsed = await chat_json(MODEL_LIGHT, system_prompt, user_prompt, temperature=TEMP_SUGGEST)

            picked_indices = parsed.get('suggest', [])
            suggest_ids = []
            for pi in picked_indices:
                if isinstance(pi, int) and 0 <= pi < len(cand_indices):
                    suggest_ids.append(groups[cand_indices[pi]]['id'])

            suggest_map[group_idx] = suggest_ids[:SUGGEST_COUNT]

    tasks = [process_group(i) for i in range(len(groups))]
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
