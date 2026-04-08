"""
merged_final 시트에서 상품 데이터를 읽어
LLM으로 key_description, topic_keyword를 생성합니다.
누락이 있으면 최대 MAX_RETRY_ROUNDS회 재시도합니다.
"""
import json
import asyncio
import sys
import time
from config import MODEL_MAIN, PREPARE_BATCH_SIZE, PREPARE_MAX_CONCURRENT, SKIP_EMPTY_DESC
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

MAX_RETRY_ROUNDS = 3


async def generate_batch(items: list[dict]) -> list[dict]:
    """여러 상품을 한 번의 API 요청으로 처리합니다."""
    products_text = ""
    for pos, item in enumerate(items):
        products_text += f"""
---
[상품 #{pos}]
상품명: {item['content_nm']}
상품 상세 설명 (JSON):
{item['description']}
"""

    system_prompt = build_system_prompt(load_prompt('qna/system.txt'))
    user_prompt = load_prompt('qna/user.txt').format(
        item_count=len(items),
        products_text=products_text
    )

    parsed = await chat_json(MODEL_MAIN, system_prompt, user_prompt, temperature=0.3)
    return parsed.get('results', [])


async def process_all(df, only_indices: set = None):
    """배치를 만들고 비동기 병렬로 처리합니다."""
    skipped = set()
    batches = []
    current_batch = []
    for i in range(len(df)):
        if only_indices is not None and i not in only_indices:
            continue

        row = df.iloc[i]
        desc = row.get('description', '[]')
        is_empty = (not desc) or (desc in ('[]', ''))

        if SKIP_EMPTY_DESC and is_empty:
            skipped.add(i)
            continue

        current_batch.append({
            'index': i,
            'content_nm': row['content_nm'],
            'description': desc
        })
        if len(current_batch) >= PREPARE_BATCH_SIZE:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    if skipped:
        print(f"description 없는 상품 {len(skipped)}건 스킵 (SKIP_EMPTY_DESC={SKIP_EMPTY_DESC})")

    print(f"총 {len(batches)}개 배치 (배치당 {PREPARE_BATCH_SIZE}개, 동시 {PREPARE_MAX_CONCURRENT}개)")

    all_results = {}
    semaphore = asyncio.Semaphore(PREPARE_MAX_CONCURRENT)

    async def run_batch(batch_idx, batch_items):
        async with semaphore:
            indices = [item['index'] for item in batch_items]
            print(f"  배치 {batch_idx + 1}/{len(batches)} (상품 {indices[0]+1}~{indices[-1]+1}) 처리 중...")
            try:
                results = await generate_batch(batch_items)
                for pos, r in enumerate(results):
                    if pos >= len(batch_items):
                        break
                    df_idx = batch_items[pos]['index']
                    key_desc = r.get('key_description', '')
                    if not key_desc:
                        continue
                    keywords = r.get('topic_keyword', [])
                    if isinstance(keywords, list):
                        keywords = json.dumps(keywords, ensure_ascii=False)
                    all_results[df_idx] = {
                        'key_description': key_desc,
                        'topic_keyword': keywords
                    }
                print(f"  배치 {batch_idx + 1}/{len(batches)} 완료")
            except Exception as e:
                print(f"  배치 {batch_idx + 1}/{len(batches)} ERROR: {e}")

    tasks = [run_batch(i, batch) for i, batch in enumerate(batches)]
    await asyncio.gather(*tasks)
    return all_results


def main():
    # 1. merged_final 시트 읽기
    df = read_google_sheet(sheet_name='merged_final')
    print(f"Read Shape: {df.shape}")

    # 2. 비동기 배치 처리 (재시도 포함)
    start_time = time.time()

    # description이 있는 아이템의 인덱스 집합
    expected_indices = set()
    for i in range(len(df)):
        desc = df.iloc[i].get('description', '[]')
        if desc and desc not in ('[]', ''):
            expected_indices.add(i)

    all_results = {}
    for attempt in range(1, MAX_RETRY_ROUNDS + 1):
        missing_indices = expected_indices - set(all_results.keys())
        if not missing_indices:
            break

        label = f"라운드 {attempt}/{MAX_RETRY_ROUNDS}" if attempt > 1 else "처리"
        print(f"\n{label}: {len(missing_indices)}건...")
        round_results = asyncio.run(process_all(df, only_indices=missing_indices))
        all_results.update(round_results)

        if attempt < MAX_RETRY_ROUNDS:
            still_missing = expected_indices - set(all_results.keys())
            if still_missing:
                print(f"  ⚠ {len(still_missing)}건 누락 → 재시도...")

    elapsed = time.time() - start_time
    print(f"\n처리 완료: {elapsed:.1f}초 소요")

    # 검증
    final_missing = expected_indices - set(all_results.keys())
    if final_missing:
        print(f"\n✗ {MAX_RETRY_ROUNDS}회 재시도 후에도 {len(final_missing)}건 누락")
        sys.exit(1)

    # 3. 결과 반영 및 저장
    df['key_description'] = [all_results.get(i, {}).get('key_description', '') for i in range(len(df))]
    df['topic_keyword'] = [all_results.get(i, {}).get('topic_keyword', '[]') for i in range(len(df))]

    write_dataframe_to_sheet(df, sheet_name='prepared_data')
    print(f"Successfully wrote {len(df)} rows to 'prepared_data' sheet")


if __name__ == '__main__':
    main()
