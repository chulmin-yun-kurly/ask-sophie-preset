"""
각 상품에 대해 소비자 관점의 질문을 생성합니다.
결과는 product_qna 시트에 저장됩니다 (답변 컬럼은 비워둠).
"""
import asyncio
import json
import pandas as pd
from config import MODEL_MAIN, PREPARE_BATCH_SIZE, PREPARE_MAX_CONCURRENT
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet


async def generate_questions_batch(items: list[dict], system_prompt: str, user_template: str) -> list[dict]:
    """여러 상품에 대한 질문을 한 번의 API 요청으로 생성합니다."""
    products_text = ""
    for pos, item in enumerate(items):
        products_text += f"""
---
[상품 #{pos}]
상품명: {item['content_nm']}
핵심 요약: {item['key_description']}
특장점: {item['features']}
스토리: {item['story']}
추천 대상: {item['recommendation']}
"""

    user_prompt = user_template.format(products_text=products_text)
    parsed = await chat_json(MODEL_MAIN, system_prompt, user_prompt, temperature=0.5)
    return parsed.get('results', [])


async def generate_all_questions(items: list[dict]) -> dict:
    """모든 상품에 대해 질문을 생성합니다. 반환: {original_idx: [질문1, ...]}"""
    system_prompt = build_system_prompt(load_prompt('product/product_question_system.txt'))
    user_template = load_prompt('product/product_question_user.txt')

    batches = []
    for i in range(0, len(items), PREPARE_BATCH_SIZE):
        batches.append(items[i:i + PREPARE_BATCH_SIZE])

    print(f"   총 {len(batches)}개 배치 (배치당 {PREPARE_BATCH_SIZE}개, 동시 {PREPARE_MAX_CONCURRENT}개)")

    results = {}
    semaphore = asyncio.Semaphore(PREPARE_MAX_CONCURRENT)

    async def run_batch(batch_idx, batch_items):
        async with semaphore:
            print(f"   배치 {batch_idx + 1}/{len(batches)} 처리 중...")
            try:
                batch_results = await generate_questions_batch(batch_items, system_prompt, user_template)
                for r in batch_results:
                    if not isinstance(r, dict):
                        continue
                    idx = int(r.get('index', -1))
                    if 0 <= idx < len(batch_items):
                        original_idx = batch_items[idx]['original_idx']
                        results[original_idx] = r.get('questions', [])
                print(f"   배치 {batch_idx + 1}/{len(batches)} 완료")
            except Exception as e:
                print(f"   배치 {batch_idx + 1}/{len(batches)} ERROR: {e}")

    tasks = [run_batch(i, batch) for i, batch in enumerate(batches)]
    await asyncio.gather(*tasks)
    return results


async def main():
    # 1. product_data 시트 읽기
    print("1. product_data 시트 읽는 중...")
    df_product = read_google_sheet(sheet_name='product_data')
    print(f"   product_data: {len(df_product)}건")

    # 2. prepared_data에서 key_description 가져오기
    print("\n   prepared_data 읽는 중...")
    df_prepared = read_google_sheet(sheet_name='prepared_data')
    prep_map = {}
    for _, row in df_prepared.iterrows():
        cno = int(row['content_no'])
        prep_map[cno] = {
            'key_description': row.get('key_description', ''),
        }

    # 3. 질문 생성용 아이템 구성
    items = []
    for i, row in df_product.iterrows():
        cno = int(row['content_no'])
        prep = prep_map.get(cno, {})
        items.append({
            'original_idx': i,
            'content_no': cno,
            'content_nm': row.get('content_nm', ''),
            'key_description': prep.get('key_description', ''),
            'features': row.get('features', ''),
            'story': row.get('story', ''),
            'recommendation': row.get('recommendation', ''),
        })

    # 4. 질문 생성
    print("\n2. 질문 생성 중...")
    question_results = await generate_all_questions(items)
    print(f"   질문 생성 완료: {sum(len(qs) for qs in question_results.values())}개")

    # 5. 결과 DataFrame 구성 (답변 컬럼은 비워둠)
    print("\n3. 결과 정리 중...")
    rows = []
    for item in items:
        idx = item['original_idx']
        questions = question_results.get(idx, [])
        for q_num, q in enumerate(questions, start=1):
            q_text = q.get('question', '') if isinstance(q, dict) else q
            q_category = q.get('category', '') if isinstance(q, dict) else ''
            rows.append({
                'content_no': item['content_no'],
                'content_nm': item['content_nm'],
                'q_number': q_num,
                'category': q_category,
                'question': q_text,
                'answer_intro': '',
                'subtopics': '[]',
                'answer_outro': '',
            })

    df_out = pd.DataFrame(rows)

    for _, row in df_out.iterrows():
        print(f"   [{row['content_no']}_{row['q_number']}] {row['question'][:50]}")

    # 6. 시트 저장
    print("\n4. 결과 저장 중...")
    write_dataframe_to_sheet(df_out, sheet_name='product_qna')
    print(f"\nSuccessfully wrote {len(df_out)} rows to 'product_qna' sheet")


if __name__ == '__main__':
    asyncio.run(main())
