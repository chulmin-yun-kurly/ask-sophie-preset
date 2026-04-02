"""
product_data와 product_qna에 대해 관련 질문(suggest)을 매핑합니다.

product_data suggest (5개):
  1. 해당 상품의 product_qna 질문 ID (pqq_<cno>_N) 무조건 포함
  2. 나머지를 qna_group에서: 직접 매핑(max 2) + 임베딩 유사도

product_qna suggest (5개):
  - qna_group에서: 직접 매핑(max 2) + 임베딩 유사도
"""
import json
import asyncio
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from config import MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE
from llm_client import get_embeddings
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

SUGGEST_COUNT = 15
DIRECT_MAP_LIMIT = 2


def build_qna_group_data(df_qna):
    """qna_group 시트에서 그룹 목록과 직접 매핑을 구성합니다."""
    direct_map = {}  # content_no → list of qna_group ids
    groups = []
    for _, row in df_qna.iterrows():
        gid = row.get('id', '')
        rep = row.get('representative', '')
        content_list = json.loads(row['content_list']) if row.get('content_list') else []
        groups.append({'id': gid, 'representative': rep})
        for cno in content_list:
            cno = str(cno).strip()
            if cno not in direct_map:
                direct_map[cno] = []
            if gid not in direct_map[cno]:
                direct_map[cno].append(gid)
    return groups, direct_map


def fill_from_qna_group(suggest_ids: list, cno: str, sim_row: np.ndarray,
                         groups: list, direct_map: dict) -> list:
    """직접 매핑(max DIRECT_MAP_LIMIT) + 임베딩 유사도로 suggest를 채웁니다."""
    existing = set(suggest_ids)

    # 직접 매핑 (최대 2개)
    direct_ids = direct_map.get(cno, [])
    direct_added = 0
    for gid in direct_ids:
        if len(suggest_ids) >= SUGGEST_COUNT:
            break
        if gid not in existing:
            suggest_ids.append(gid)
            existing.add(gid)
            direct_added += 1
            if direct_added >= DIRECT_MAP_LIMIT:
                break

    # 임베딩 유사도
    sim_ranking = np.argsort(sim_row)[::-1]
    for gi in sim_ranking:
        if len(suggest_ids) >= SUGGEST_COUNT:
            break
        gid = groups[gi]['id']
        if gid not in existing:
            suggest_ids.append(gid)
            existing.add(gid)

    return suggest_ids[:SUGGEST_COUNT]


async def main():
    # 1. 시트 읽기
    print("1. 시트 읽는 중...")
    df_product = read_google_sheet(sheet_name='product_data')
    print(f"   product_data: {len(df_product)}건")

    df_qna = read_google_sheet(sheet_name='qna_group')
    print(f"   qna_group: {len(df_qna)}건")

    df_prepared = read_google_sheet(sheet_name='prepared_data')
    key_desc_map = {}
    for _, row in df_prepared.iterrows():
        cno = str(row['content_no']).strip()
        key_desc_map[cno] = row.get('key_description', '')

    try:
        df_product_qna = read_google_sheet(sheet_name='product_qna')
        print(f"   product_qna: {len(df_product_qna)}건")
    except Exception:
        df_product_qna = None
        print("   product_qna: 없음 (스킵)")

    # 2. qna_group 데이터 준비
    groups, direct_map = build_qna_group_data(df_qna)

    # 3. product_qna ID 맵 구성 (content_no → [pqq_<cno>_1, ...])
    pqq_map = {}  # content_no → list of pqq IDs
    if df_product_qna is not None:
        for _, row in df_product_qna.iterrows():
            cno = str(row['content_no']).strip()
            q_num = int(row['q_number'])
            pqq_id = f"pqq_{cno}_{q_num}"
            if cno not in pqq_map:
                pqq_map[cno] = []
            pqq_map[cno].append(pqq_id)

    # 4. 임베딩 생성
    print("\n2. 임베딩 생성 중...")
    # 상품 텍스트
    product_texts = []
    product_cnos = []
    for _, row in df_product.iterrows():
        cno = str(row['content_no']).strip()
        key_desc = key_desc_map.get(cno, '')
        product_texts.append(f"{row['content_nm']} {key_desc}")
        product_cnos.append(cno)

    # product_qna 질문 텍스트
    pqna_texts = []
    if df_product_qna is not None:
        for _, row in df_product_qna.iterrows():
            pqna_texts.append(row.get('question', ''))

    # qna_group 대표 질문 텍스트
    group_texts = [g['representative'] for g in groups]

    all_texts = product_texts + pqna_texts + group_texts
    all_embs = await get_embeddings(all_texts, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
    emb_matrix = np.array(all_embs)

    n_products = len(product_texts)
    n_pqna = len(pqna_texts)

    product_embs = emb_matrix[:n_products]
    pqna_embs = emb_matrix[n_products:n_products + n_pqna]
    group_embs = emb_matrix[n_products + n_pqna:]

    # 5. product_data suggest 매핑
    print("\n3. product_data suggest 매핑 중...")
    sim_product_group = cosine_similarity(product_embs, group_embs)

    suggest_col = []
    for pi, cno in enumerate(product_cnos):
        # product_qna 질문 ID 우선 포함
        suggest_ids = list(pqq_map.get(cno, []))
        # 나머지를 qna_group에서 채움
        suggest_ids = fill_from_qna_group(suggest_ids, cno, sim_product_group[pi], groups, direct_map)
        suggest_col.append(json.dumps(suggest_ids, ensure_ascii=False))

    df_product['suggest'] = suggest_col

    for _, row in df_product.iterrows():
        suggests = json.loads(row['suggest'])
        print(f"   [{row['content_no']}] {row['content_nm']}")
        print(f"     → suggest: {suggests}")

    # 6. product_qna suggest 매핑
    if df_product_qna is not None and n_pqna > 0:
        print(f"\n4. product_qna suggest 매핑 중...")
        sim_pqna_group = cosine_similarity(pqna_embs, group_embs)

        pqna_suggest_col = []
        for qi, (_, row) in enumerate(df_product_qna.iterrows()):
            cno = str(row['content_no']).strip()
            suggest_ids = fill_from_qna_group([], cno, sim_pqna_group[qi], groups, direct_map)
            pqna_suggest_col.append(json.dumps(suggest_ids, ensure_ascii=False))

        df_product_qna['suggest'] = pqna_suggest_col

        for _, row in df_product_qna.iterrows():
            suggests = json.loads(row['suggest'])
            print(f"   [pqq_{row['content_no']}_{row['q_number']}] {row['question'][:40]}")
            print(f"     → suggest: {suggests}")

    # 7. 저장
    print("\n5. 결과 저장 중...")
    write_dataframe_to_sheet(df_product, sheet_name='product_data')
    print(f"   product_data: {len(df_product)}건 저장")

    if df_product_qna is not None:
        write_dataframe_to_sheet(df_product_qna, sheet_name='product_qna')
        print(f"   product_qna: {len(df_product_qna)}건 저장")

    print("\nDone.")


if __name__ == '__main__':
    asyncio.run(main())
