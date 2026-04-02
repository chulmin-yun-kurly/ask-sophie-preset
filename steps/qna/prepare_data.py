"""
merged_final 시트에서 상품 데이터를 읽어
LLM으로 key_description, topic_keyword를 생성합니다.
"""
import json
import asyncio
import time
from config import MODEL_MAIN, PREPARE_BATCH_SIZE, PREPARE_MAX_CONCURRENT, SKIP_EMPTY_DESC
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet


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


async def process_all(df):
    """배치를 만들고 비동기 병렬로 처리합니다."""
    skipped = set()
    batches = []
    current_batch = []
    for i in range(len(df)):
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
                    keywords = r.get('topic_keyword', [])
                    if isinstance(keywords, list):
                        keywords = json.dumps(keywords, ensure_ascii=False)
                    all_results[df_idx] = {
                        'key_description': r.get('key_description', ''),
                        'topic_keyword': keywords
                    }
                print(f"  배치 {batch_idx + 1}/{len(batches)} 완료")
            except Exception as e:
                print(f"  배치 {batch_idx + 1}/{len(batches)} ERROR: {e}")
                for item in batch_items:
                    all_results[item['index']] = {
                        'key_description': '',
                        'topic_keyword': '[]'
                    }

    tasks = [run_batch(i, batch) for i, batch in enumerate(batches)]
    await asyncio.gather(*tasks)
    return all_results


def main():
    # 1. merged_final 시트 읽기
    df = read_google_sheet(sheet_name='merged_final')
    print(f"Read Shape: {df.shape}")

    # 2. 비동기 배치 처리
    start_time = time.time()
    results = asyncio.run(process_all(df))
    elapsed = time.time() - start_time
    print(f"\n처리 완료: {elapsed:.1f}초 소요")

    # 3. 결과 반영 및 저장
    df['key_description'] = [results.get(i, {}).get('key_description', '') for i in range(len(df))]
    df['topic_keyword'] = [results.get(i, {}).get('topic_keyword', '[]') for i in range(len(df))]

    write_dataframe_to_sheet(df, sheet_name='prepared_data')
    print(f"Successfully wrote {len(df)} rows to 'prepared_data' sheet")


if __name__ == '__main__':
    main()
