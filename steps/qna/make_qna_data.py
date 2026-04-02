"""
prepared_data 시트에서 상품 데이터를 읽어
카테고리 체계에 맞는 소비자 질문을 생성합니다.
"""
import json
import asyncio
import time
from config import MODEL_MAIN, QNA_BATCH_SIZE, QNA_MAX_CONCURRENT, SKIP_EMPTY_DESC
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
핵심 설명: {item['key_description']}
특성 키워드: {item['topic_keyword']}
상품 상세 설명 (JSON):

{item['description']}
"""

    system_prompt = build_system_prompt(load_prompt('qna/qna_system.txt'))
    user_prompt = load_prompt('qna/qna_user.txt').format(
        item_count=len(items),
        products_text=products_text
    )

    parsed = await chat_json(MODEL_MAIN, system_prompt, user_prompt, temperature=0.7)
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
            'key_description': row.get('key_description', ''),
            'topic_keyword': row.get('topic_keyword', ''),
            'description': desc
        })
        if len(current_batch) >= QNA_BATCH_SIZE:
            batches.append(current_batch)
            current_batch = []
    if current_batch:
        batches.append(current_batch)

    if skipped:
        print(f"description 없는 상품 {len(skipped)}건 스킵 (SKIP_EMPTY_DESC={SKIP_EMPTY_DESC})")

    print(f"총 {len(batches)}개 배치 (배치당 {QNA_BATCH_SIZE}개, 동시 {QNA_MAX_CONCURRENT}개)")

    all_results = {}
    semaphore = asyncio.Semaphore(QNA_MAX_CONCURRENT)

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
                    question_list = r.get('question_list', {})
                    if isinstance(question_list, dict):
                        question_list = json.dumps(question_list, ensure_ascii=False)
                    all_results[df_idx] = {'question_list': question_list}
                print(f"  배치 {batch_idx + 1}/{len(batches)} 완료")
            except Exception as e:
                print(f"  배치 {batch_idx + 1}/{len(batches)} ERROR: {e}")
                for item in batch_items:
                    all_results[item['index']] = {'question_list': '{}'}

    tasks = [run_batch(i, batch) for i, batch in enumerate(batches)]
    await asyncio.gather(*tasks)
    return all_results


def main():
    # 1. prepared_data 시트 읽기
    df = read_google_sheet(sheet_name='prepared_data')
    print(f"1. Read Shape: {df.shape}")

    # 2. 비동기 배치 처리
    start_time = time.time()
    results = asyncio.run(process_all(df))
    elapsed = time.time() - start_time
    print(f"\n처리 완료: {elapsed:.1f}초 소요")

    # 3. 결과 반영 및 저장
    df['question_list'] = [results.get(i, {}).get('question_list', '{}') for i in range(len(df))]

    write_dataframe_to_sheet(df, sheet_name='qna_data')
    print(f"Successfully wrote {len(df)} rows to 'qna_data' sheet")


if __name__ == '__main__':
    main()
