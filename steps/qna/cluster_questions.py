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
from collections import defaultdict
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity
from config import (
    MODEL_LIGHT, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE,
    CLUSTER_MAX_QUESTIONS, CLUSTER_MAX_CONCURRENT, MIN_CONTENT_COUNT, TEMP_CLUSTER_MERGE,
    CLUSTER_PRE_DEDUP_THRESHOLD, CLUSTER_POST_DEDUP_THRESHOLD, CLUSTER_CROSS_MAX_CONCURRENT,
    CLUSTER_COHESION_THRESHOLD
)
from llm_client import client, load_prompt, build_system_prompt, chat_json, get_embeddings
from sheet_reader import write_dataframe_to_sheet


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[b] = a


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
        max_groups=max(3, len(questions) // 2),
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


async def validate_group(category: str, group: dict, question_index: dict) -> list[dict]:
    """그룹 내 질문들의 의도 일관성을 검증하고, 불일치 시 분리합니다."""
    questions = group['questions']
    if len(questions) <= 2:
        return [group]

    qs_text = "\n".join(f"  {i}. {q}" for i, q in enumerate(questions))

    validate_system = build_system_prompt(load_prompt('qna/validate_system.txt'))
    validate_user = load_prompt('qna/validate_user.txt').format(
        representative=group['representative'],
        category=category,
        qs_text=qs_text
    )

    parsed = await chat_json(MODEL_LIGHT, validate_system, validate_user,
                             temperature=TEMP_CLUSTER_MERGE)

    result_groups = []
    for g in parsed.get('groups', []):
        indices = g.get('question_indices', [])
        group_qs = [questions[i] for i in indices if i < len(questions)]
        if group_qs:
            group_content = set()
            for q in group_qs:
                group_content.update(question_index.get((category, q), set()))
            result_groups.append({
                'representative': g.get('representative', group_qs[0]),
                'questions': group_qs,
                'content_nos': group_content,
            })

    return result_groups if result_groups else [group]


async def confirm_cross_merge(group_a: tuple, group_b: tuple,
                              semaphore: asyncio.Semaphore) -> dict | None:
    """Cross-category 그룹 쌍의 병합 여부를 LLM으로 확인합니다."""
    cat_a, grp_a = group_a
    cat_b, grp_b = group_b

    sample_a = "\n".join(f"    - {q}" for q in grp_a['questions'][:5])
    sample_b = "\n".join(f"    - {q}" for q in grp_b['questions'][:5])

    cross_system = build_system_prompt(load_prompt('qna/cross_merge_system.txt'))
    cross_user = load_prompt('qna/cross_merge_user.txt').format(
        category_a=cat_a,
        representative_a=grp_a['representative'],
        sample_questions_a=sample_a,
        category_b=cat_b,
        representative_b=grp_b['representative'],
        sample_questions_b=sample_b
    )

    async with semaphore:
        parsed = await chat_json(MODEL_LIGHT, cross_system, cross_user,
                                 temperature=TEMP_CLUSTER_MERGE)

    if parsed.get('merge'):
        return {
            'merge': True,
            'representative': parsed.get('representative', grp_a['representative'])
        }
    return None


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

    # question → embedding 매핑 (Step A/B/C에서 재사용)
    embedding_lookup = {}
    for i, q in enumerate(all_questions):
        embedding_lookup[q] = all_embedding_matrix[i]

    category_embeddings = {}
    idx = 0
    for category, items in category_data.items():
        n = len(items)
        category_embeddings[category] = all_embedding_matrix[idx:idx + n]
        idx += n

    # ──────────────────────────────────────────────
    # 2.5 Step A: Semantic Pre-dedup (카테고리 내)
    # ──────────────────────────────────────────────
    print("\n2.5 카테고리 내 Semantic Pre-dedup...")

    for category in list(category_data.keys()):
        items = category_data[category]
        embs = category_embeddings[category]
        n = len(items)
        if n < 2:
            continue

        sim_matrix = cosine_similarity(embs)
        uf = UnionFind(n)
        for i in range(n):
            for j in range(i + 1, n):
                if sim_matrix[i][j] >= CLUSTER_PRE_DEDUP_THRESHOLD:
                    uf.union(i, j)

        groups = defaultdict(list)
        for i in range(n):
            groups[uf.find(i)].append(i)

        merged_items = []
        merged_embs = []
        for indices in groups.values():
            # content_nos 합집합
            merged_content = set()
            for idx in indices:
                merged_content.update(items[idx]['content_nos'])
            # 대표: content_nos가 가장 많은 질문
            best_idx = max(indices, key=lambda i: len(items[i]['content_nos']))
            merged_items.append({
                'question': items[best_idx]['question'],
                'content_nos': merged_content,
            })
            merged_embs.append(embs[best_idx])

        category_data[category] = merged_items
        category_embeddings[category] = np.array(merged_embs)

        if len(merged_items) < n:
            print(f"   [Pre-dedup] {category}: {n} → {len(merged_items)} 질문")

    # question_index 재구축 (pre-dedup 후 content_nos 변경 반영)
    question_index = {}
    for category, items in category_data.items():
        for item in items:
            question_index[(category, item['question'])] = item['content_nos']

    total_after_prededup = sum(len(v) for v in category_data.values())
    print(f"   Pre-dedup 후 총 {total_after_prededup}개 질문 (원래 {total_questions}개)")

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

    # ──────────────────────────────────────────────
    # 4.3 Step D: LLM 그룹 검증
    # ──────────────────────────────────────────────
    print("\n4.3 LLM 그룹 검증 중...")

    validate_meta = []  # [(category, key, group), ...]
    for category in merged_tree:
        for key in sorted(merged_tree[category].keys()):
            validate_meta.append((category, key, merged_tree[category][key]))

    async def process_validate(cat, grp):
        async with semaphore:
            return await validate_group(cat, grp, question_index)

    validate_tasks = [process_validate(cat, grp) for cat, _, grp in validate_meta]
    validate_results = await asyncio.gather(*validate_tasks)

    validated_tree = defaultdict(dict)
    for (category, _, _), sub_groups in zip(validate_meta, validate_results):
        for sg in sub_groups:
            idx = len(validated_tree[category])
            validated_tree[category][idx] = sg

    for category in merged_tree:
        before = sum(1 for cat, _, _ in validate_meta if cat == category)
        after = len(validated_tree.get(category, {}))
        if after > before:
            print(f"   [Validate] {category}: {before} → {after} 그룹 (분리 발생)")

    merged_tree = dict(validated_tree)

    # ──────────────────────────────────────────────
    # 4.5 Step B: Intra-category Post-merge Dedup
    # ──────────────────────────────────────────────
    print("\n4.5 카테고리 내 Post-merge Dedup...")

    # 누락된 representative 임베딩 보충
    missing_reps = []
    for category in merged_tree:
        for key, group in merged_tree[category].items():
            rep = group['representative']
            if rep not in embedding_lookup:
                missing_reps.append(rep)

    if missing_reps:
        missing_embs = await get_embeddings(missing_reps, MODEL_EMBEDDING, EMBEDDING_BATCH_SIZE)
        for q, emb in zip(missing_reps, missing_embs):
            embedding_lookup[q] = np.array(emb)
        print(f"   {len(missing_reps)}개 누락 representative 임베딩 보충")

    for category in list(merged_tree.keys()):
        groups = list(merged_tree[category].values())
        if len(groups) < 2:
            continue

        rep_embs = np.array([embedding_lookup[g['representative']] for g in groups])

        sim_matrix = cosine_similarity(rep_embs)
        uf = UnionFind(len(groups))
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if sim_matrix[i][j] >= CLUSTER_POST_DEDUP_THRESHOLD:
                    uf.union(i, j)

        merge_groups = defaultdict(list)
        for i in range(len(groups)):
            merge_groups[uf.find(i)].append(i)

        new_tree = {}
        idx = 0
        for indices in merge_groups.values():
            combined_qs = []
            combined_content = set()
            for i in indices:
                combined_qs.extend(groups[i]['questions'])
                combined_content.update(groups[i]['content_nos'])
            biggest = max(indices, key=lambda i: len(groups[i]['questions']))
            new_tree[idx] = {
                'representative': groups[biggest]['representative'],
                'questions': combined_qs,
                'content_nos': combined_content,
            }
            idx += 1

        if len(new_tree) < len(groups):
            print(f"   [Post-dedup] {category}: {len(groups)} → {len(new_tree)} 그룹")
        merged_tree[category] = new_tree

    # ──────────────────────────────────────────────
    # 4.6 Step C: Cross-category Dedup
    # ──────────────────────────────────────────────
    print("\n4.6 Cross-category Dedup...")

    all_groups = []  # [(category, key, group_dict), ...]
    for cat in merged_tree:
        for key, group in merged_tree[cat].items():
            all_groups.append((cat, key, group))

    if len(all_groups) >= 2:
        rep_embs = np.array([embedding_lookup[g[2]['representative']] for g in all_groups])
        sim_matrix = cosine_similarity(rep_embs)

        # cross-category 고유사도 쌍 추출
        cross_pairs = []
        for i in range(len(all_groups)):
            for j in range(i + 1, len(all_groups)):
                if all_groups[i][0] != all_groups[j][0]:  # 다른 카테고리
                    if sim_matrix[i][j] >= CLUSTER_POST_DEDUP_THRESHOLD:
                        cross_pairs.append((i, j, sim_matrix[i][j]))

        if cross_pairs:
            print(f"   {len(cross_pairs)}개 cross-category 후보 쌍 발견, LLM 확인 중...")

            cross_semaphore = asyncio.Semaphore(CLUSTER_CROSS_MAX_CONCURRENT)

            async def check_pair(i, j):
                result = await confirm_cross_merge(
                    (all_groups[i][0], all_groups[i][2]),
                    (all_groups[j][0], all_groups[j][2]),
                    cross_semaphore
                )
                if result:
                    return (i, j, result['representative'])
                return None

            pair_tasks = [check_pair(i, j) for i, j, _ in cross_pairs]
            pair_results = await asyncio.gather(*pair_tasks)

            confirmed = [r for r in pair_results if r is not None]

            if confirmed:
                uf = UnionFind(len(all_groups))
                rep_override = {}
                for i, j, chosen_rep in confirmed:
                    uf.union(i, j)
                    new_root = uf.find(i)
                    rep_override[new_root] = chosen_rep

                merge_map = defaultdict(list)
                for i in range(len(all_groups)):
                    merge_map[uf.find(i)].append(i)

                # merged_tree 재구성
                new_merged_tree = defaultdict(dict)
                for root, indices in merge_map.items():
                    if len(indices) == 1:
                        i = indices[0]
                        cat = all_groups[i][0]
                        new_merged_tree[cat][len(new_merged_tree[cat])] = all_groups[i][2]
                    else:
                        # 병합: 가장 큰 그룹의 카테고리 채택
                        biggest = max(indices, key=lambda i: len(all_groups[i][2]['questions']))
                        target_cat = all_groups[biggest][0]
                        combined_qs = []
                        combined_content = set()
                        for i in indices:
                            combined_qs.extend(all_groups[i][2]['questions'])
                            combined_content.update(all_groups[i][2]['content_nos'])
                        chosen_rep = rep_override.get(root, all_groups[biggest][2]['representative'])
                        new_merged_tree[target_cat][len(new_merged_tree[target_cat])] = {
                            'representative': chosen_rep,
                            'questions': combined_qs,
                            'content_nos': combined_content,
                        }

                merged_count = sum(1 for indices in merge_map.values() if len(indices) > 1)
                print(f"   [Cross-dedup] {len(confirmed)}개 쌍 병합 확인 → {merged_count}개 그룹 병합")
                merged_tree = dict(new_merged_tree)
            else:
                print("   Cross-category 병합 대상 없음")
        else:
            print("   Cross-category 후보 쌍 없음")
    else:
        print("   그룹 수 부족, 스킵")

    cluster_tree = merged_tree

    # ──────────────────────────────────────────────
    # 4.7 Step E: Cohesion Filter (내부 일관성 미달 그룹 제거)
    # ──────────────────────────────────────────────
    print("\n4.7 Cohesion Filter...")

    total_removed = 0
    for category in list(merged_tree.keys()):
        groups = merged_tree[category]
        filtered = {}
        removed = 0
        for key, group in groups.items():
            qs = group['questions']
            if len(qs) < 2:
                filtered[len(filtered)] = group
                continue

            # 질문 임베딩 수집
            embs = []
            for q in qs:
                if q in embedding_lookup:
                    embs.append(embedding_lookup[q])
            if len(embs) < 2:
                filtered[len(filtered)] = group
                continue

            # 평균 pairwise cosine similarity
            emb_matrix = np.array(embs)
            sim_matrix = cosine_similarity(emb_matrix)
            n = len(embs)
            pair_sims = [sim_matrix[i][j] for i in range(n) for j in range(i + 1, n)]
            cohesion = sum(pair_sims) / len(pair_sims)

            if cohesion >= CLUSTER_COHESION_THRESHOLD:
                filtered[len(filtered)] = group
            else:
                removed += 1

        if removed:
            print(f"   [Cohesion] {category}: {removed}개 그룹 제거 (cohesion < {CLUSTER_COHESION_THRESHOLD})")
            total_removed += removed
        merged_tree[category] = filtered

    if total_removed:
        remaining = sum(len(cat) for cat in merged_tree.values())
        print(f"   총 {total_removed}개 그룹 제거, {remaining}개 남음")
    else:
        print("   제거 대상 없음")

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
