"""
inverted_questions.csv를 읽어 질문을 클러스터링하고,
LLM으로 병합합니다.
"""
import json
import asyncio
import math
import os
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity
from config import (
    MODEL_LIGHT, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE,
    CLUSTER_MAX_QUESTIONS, CLUSTER_MAX_CONCURRENT, MIN_CONTENT_COUNT, TEMP_CLUSTER_MERGE
)
from llm_client import client, load_prompt, build_system_prompt, chat_json, get_embeddings
from sheet_reader import write_dataframe_to_sheet


async def merge_cluster_questions(category: str, cluster: dict) -> dict:
    """클러스터 내 질문들을 LLM으로 유사 질문끼리 병합합니다."""
    questions = cluster['questions']

    if len(questions) <= 2:
        return {
            'groups': [{
                'representative': cluster['representative'],
                'questions': questions
            }]
        }

    qs_text = "\n".join(f"  {i}. {q}" for i, q in enumerate(questions))

    merge_system = build_system_prompt(load_prompt('qna/merge_system.txt'))
    merge_user = load_prompt('qna/merge_user.txt').format(
        question_count=len(questions),
        max_groups=max(2, len(questions) // 3),
        category=category,
        qs_text=qs_text
    )

    parsed = await chat_json(MODEL_LIGHT, merge_system, merge_user, temperature=TEMP_CLUSTER_MERGE)

    groups = parsed.get('groups', [])
    result_groups = []
    covered = set()
    for g in groups:
        indices = g.get('question_indices', [])
        group_questions = [questions[i] for i in indices if i < len(questions)]
        if group_questions:
            result_groups.append({
                'representative': g.get('representative', group_questions[0]),
                'questions': group_questions
            })
            covered.update(indices)

    # 누락된 질문 처리
    for i in range(len(questions)):
        if i not in covered:
            result_groups.append({
                'representative': questions[i],
                'questions': [questions[i]]
            })

    return {'groups': result_groups}


async def main():
    # ──────────────────────────────────────────────
    # 1. inverted_questions.csv 읽기
    # ──────────────────────────────────────────────
    from product_config import get_output_dir
    output_dir = get_output_dir()

    print("1. inverted_questions.csv 읽는 중...")
    df_inv = pd.read_csv(os.path.join(output_dir, 'inverted_questions.csv'), encoding='utf-8-sig')
    print(f"   Read Shape: {df_inv.shape}")

    category_data = {}
    for _, row in df_inv.iterrows():
        category = row['category']
        question = row['question']
        content_list = json.loads(row['content_list'])
        if category not in category_data:
            category_data[category] = []
        category_data[category].append({
            'question': question,
            'content_nos': set(content_list)
        })

    # 질문→상품 빠른 검색용 인덱스
    question_index = {}
    for category, items in category_data.items():
        for item in items:
            question_index[(category, item['question'])] = item['content_nos']

    total_questions = sum(len(v) for v in category_data.values())
    print(f"   총 {total_questions}개 고유 질문, {len(category_data)}개 카테고리")
    for cat, items in category_data.items():
        print(f"     {cat}: {len(items)}개 질문")

    # ──────────────────────────────────────────────
    # 2. 전체 질문 임베딩 생성
    # ──────────────────────────────────────────────
    print("\n2. 임베딩 생성 중...")

    all_questions = []
    for category, items in category_data.items():
        for item in items:
            all_questions.append(item['question'])

    all_embeddings = await get_embeddings(all_questions, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
    all_embedding_matrix = np.array(all_embeddings)
    print(f"   임베딩 Shape: {all_embedding_matrix.shape}")

    category_embeddings = {}
    idx = 0
    for category, items in category_data.items():
        n = len(items)
        category_embeddings[category] = all_embedding_matrix[idx:idx + n]
        idx += n

    # ──────────────────────────────────────────────
    # 3. 카테고리별 클러스터링 + 대표 질문 선정
    # ──────────────────────────────────────────────
    print(f"\n3. 카테고리별 클러스터링 (클러스터당 최대 {CLUSTER_MAX_QUESTIONS}개 목표)...")

    cluster_tree = {}

    for category in category_data:
        items = category_data[category]
        embeddings = category_embeddings[category]
        n_questions = len(items)

        cluster_tree[category] = {}

        if n_questions <= CLUSTER_MAX_QUESTIONS:
            centroid = embeddings.mean(axis=0)
            sims = cosine_similarity([centroid], embeddings)[0]
            rep_idx = int(np.argmax(sims))

            all_content_nos = set()
            for item in items:
                all_content_nos.update(item['content_nos'])

            cluster_tree[category][0] = {
                'representative': items[rep_idx]['question'],
                'questions': [item['question'] for item in items],
                'content_nos': all_content_nos
            }
            print(f"   {category}: 질문 {n_questions}개 → 클러스터 1개 (≤{CLUSTER_MAX_QUESTIONS})")
            continue

        sub_k = math.ceil(n_questions / CLUSTER_MAX_QUESTIONS)

        km = KMeans(n_clusters=sub_k, random_state=42, n_init=10)
        labels = km.fit_predict(embeddings)

        for j, label in enumerate(labels):
            label = int(label)
            if label not in cluster_tree[category]:
                cluster_tree[category][label] = {
                    'representative': None,
                    'questions': [],
                    'content_nos': set()
                }
            cluster_tree[category][label]['questions'].append(items[j]['question'])
            cluster_tree[category][label]['content_nos'].update(items[j]['content_nos'])

        for label in cluster_tree[category]:
            cluster_indices = [j for j, l in enumerate(labels) if l == label]
            cluster_embs = embeddings[cluster_indices]
            centroid = cluster_embs.mean(axis=0)
            sims = cosine_similarity([centroid], cluster_embs)[0]
            rep_local_idx = int(np.argmax(sims))
            rep_global_idx = cluster_indices[rep_local_idx]
            cluster_tree[category][label]['representative'] = items[rep_global_idx]['question']

        sub_sizes = [len(cluster_tree[category][s]['questions']) for s in sorted(cluster_tree[category])]
        print(f"   {category}: 질문 {n_questions}개 → 클러스터 {sub_k}개 {sub_sizes}")

    # ──────────────────────────────────────────────
    # 4. LLM으로 클러스터 내 유사 질문 병합
    # ──────────────────────────────────────────────
    print("\n4. LLM으로 클러스터 내 유사 질문 병합 중...")

    semaphore = asyncio.Semaphore(CLUSTER_MAX_CONCURRENT)
    merge_results = {}

    async def process_merge(cat, lab, clust):
        async with semaphore:
            result = await merge_cluster_questions(cat, clust)
            merge_results[(cat, lab)] = result

    tasks = []
    for category in cluster_tree:
        for label in cluster_tree[category]:
            tasks.append(process_merge(category, label, cluster_tree[category][label]))
    await asyncio.gather(*tasks)

    # 병합 결과로 cluster_tree 재구성
    merged_tree = {}
    for category in cluster_tree:
        merged_tree[category] = {}
        cluster_idx = 0
        for label in sorted(cluster_tree[category].keys()):
            original = cluster_tree[category][label]
            merge_result = merge_results.get((category, label), {})
            groups = merge_result.get('groups', [{'representative': original['representative'], 'questions': original['questions']}])

            for sg in groups:
                sg_content_nos = set()
                for q in sg['questions']:
                    sg_content_nos.update(question_index.get((category, q), set()))

                merged_tree[category][cluster_idx] = {
                    'representative': sg['representative'],
                    'questions': sg['questions'],
                    'content_nos': sg_content_nos
                }
                cluster_idx += 1

    total_before = sum(len(cat) for cat in cluster_tree.values())
    total_after = sum(len(cat) for cat in merged_tree.values())
    print(f"   병합 전: {total_before}개 클러스터 → 병합 후: {total_after}개 클러스터")

    cluster_tree = merged_tree

    # ──────────────────────────────────────────────
    # 5. 결과 DataFrame 생성 & 스프레드시트 저장
    # ──────────────────────────────────────────────
    print("\n5. 결과 저장 중...")

    rows = []
    for category in cluster_tree:
        for label in sorted(cluster_tree[category].keys()):
            cluster = cluster_tree[category][label]
            label_key = f"{category}/{label}"

            rows.append({
                'category': category,
                'sub_group': label,
                'sub_group_label': '',
                'representative': cluster['representative'],
                'question_count': len(cluster['questions']),
                'content_count': len(cluster['content_nos']),
                'question_list': json.dumps(cluster['questions'], ensure_ascii=False),
                'content_list': json.dumps(sorted(cluster['content_nos']), ensure_ascii=False)
            })

    df_result = pd.DataFrame(rows)

    # content_count 필터링
    before_count = len(df_result)
    df_result = df_result[df_result['content_count'] >= MIN_CONTENT_COUNT].reset_index(drop=True)
    removed = before_count - len(df_result)
    if removed:
        print(f"   content_count < {MIN_CONTENT_COUNT} 제외: {removed}건 → {len(df_result)}건 남음")

    print(f"   결과 Shape: {df_result.shape}")
    print(f"\n   카테고리별 요약:")
    current_cat = None
    for _, row in df_result.iterrows():
        if row['category'] != current_cat:
            current_cat = row['category']
            cat_total = df_result[df_result['category'] == current_cat]['question_count'].sum()
            print(f"\n   ▸ {row['category']} (총 {cat_total}개 질문)")
        print(f"       클러스터 {row['sub_group']}: "
              f"질문 {row['question_count']}개, 상품 {row['content_count']}개")
        print(f"         대표: {row['representative']}")

    write_dataframe_to_sheet(df_result, sheet_name='qna_group')
    print(f"\nSuccessfully wrote {len(df_result)} rows to 'qna_group' sheet")


if __name__ == '__main__':
    asyncio.run(main())
