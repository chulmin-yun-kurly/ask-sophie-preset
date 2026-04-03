"""
product_qna 시트의 질문을 읽어 답변을 생성합니다.
질문은 그대로 유지하고 답변 컬럼만 갱신합니다.
"""
import asyncio
import json
import pandas as pd
from config import MODEL_MAIN, PREPARE_BATCH_SIZE, PREPARE_MAX_CONCURRENT
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet


async def generate_answers_batch(qa_items: list[dict], system_prompt: str, user_template: str) -> list[dict]:
    """여러 질문에 대한 답변을 한 번의 API 요청으로 생성합니다."""
    items_text = ""
    for pos, item in enumerate(qa_items):
        items_text += f"""
---
[항목 #{pos}]
상품명: {item['content_nm']}
질문: {item['question']}
핵심 요약: {item['key_description']}
특장점: {item['strengths']}
스토리: {item['stories']}
추천 대상: {item['targetUser']}
상세 설명: {item['description']}
"""

    user_prompt = user_template.format(items_text=items_text)
    parsed = await chat_json(MODEL_MAIN, system_prompt, user_prompt, temperature=0.5)
    return parsed.get('results', [])


async def generate_all_answers(qa_items: list[dict]) -> dict:
    """모든 질문에 대해 답변을 생성합니다. 반환: {qa_key: answer_dict}"""
    system_prompt = build_system_prompt(load_prompt('product/product_answer_system.txt'))
    user_template = load_prompt('product/product_answer_user.txt')

    batches = []
    for i in range(0, len(qa_items), PREPARE_BATCH_SIZE):
        batches.append(qa_items[i:i + PREPARE_BATCH_SIZE])

    print(f"   총 {len(batches)}개 배치 (배치당 {PREPARE_BATCH_SIZE}개, 동시 {PREPARE_MAX_CONCURRENT}개)")

    results = {}
    semaphore = asyncio.Semaphore(PREPARE_MAX_CONCURRENT)

    async def run_batch(batch_idx, batch_items):
        async with semaphore:
            print(f"   배치 {batch_idx + 1}/{len(batches)} 처리 중...")
            try:
                batch_results = await generate_answers_batch(batch_items, system_prompt, user_template)
                for r in batch_results:
                    idx = r.get('index', -1)
                    if 0 <= idx < len(batch_items):
                        key = batch_items[idx]['qa_key']
                        results[key] = {
                            'answer_intro': r.get('answer_intro', ''),
                            'subtopics': r.get('subtopics', []),
                            'answer_outro': r.get('answer_outro', ''),
                        }
                print(f"   배치 {batch_idx + 1}/{len(batches)} 완료")
            except Exception as e:
                print(f"   배치 {batch_idx + 1}/{len(batches)} ERROR: {e}")

    tasks = [run_batch(i, batch) for i, batch in enumerate(batches)]
    await asyncio.gather(*tasks)
    return results


async def main():
    # 1. product_qna 시트에서 질문 읽기
    print("1. product_qna 시트 읽는 중...")
    df_qna = read_google_sheet(sheet_name='product_qna')
    print(f"   product_qna: {len(df_qna)}건")

    # 2. product_data, prepared_data에서 상품 정보 가져오기
    print("\n   product_data 읽는 중...")
    df_product = read_google_sheet(sheet_name='product_data')
    product_map = {}
    for _, row in df_product.iterrows():
        cno = str(row['content_no']).strip()
        product_map[cno] = {
            'content_nm': row.get('content_nm', ''),
            'strengths': row.get('strengths', ''),
            'stories': row.get('stories', ''),
            'targetUser': row.get('targetUser', ''),
        }

    print("   prepared_data 읽는 중...")
    df_prepared = read_google_sheet(sheet_name='prepared_data')
    prep_map = {}
    for _, row in df_prepared.iterrows():
        cno = str(row['content_no']).strip()
        prep_map[cno] = {
            'key_description': row.get('key_description', ''),
            'description': row.get('description', ''),
        }

    # 3. 답변 생성용 아이템 구성
    qa_items = []
    for _, row in df_qna.iterrows():
        cno = str(row['content_no']).strip()
        product = product_map.get(cno, {})
        prep = prep_map.get(cno, {})
        q_num = int(row['q_number'])
        qa_key = f"{cno}_{q_num}"
        qa_items.append({
            'qa_key': qa_key,
            'content_no': cno,
            'content_nm': product.get('content_nm', row.get('content_nm', '')),
            'question': row.get('question', ''),
            'category': row.get('category', ''),
            'q_number': q_num,
            'key_description': prep.get('key_description', ''),
            'description': prep.get('description', ''),
            'strengths': product.get('strengths', ''),
            'stories': product.get('stories', ''),
            'targetUser': product.get('targetUser', ''),
        })

    # 4. 답변 생성
    print(f"\n2. 답변 생성 중... ({len(qa_items)}건)")
    answer_results = await generate_all_answers(qa_items)
    print(f"   답변 생성 완료: {len(answer_results)}건")

    # 5. 결과 DataFrame 구성 (질문은 그대로 유지)
    print("\n3. 결과 정리 중...")
    rows = []
    for qa_item in qa_items:
        key = qa_item['qa_key']
        answer = answer_results.get(key, {})
        rows.append({
            'content_no': qa_item['content_no'],
            'content_nm': qa_item['content_nm'],
            'q_number': qa_item['q_number'],
            'category': qa_item['category'],
            'question': qa_item['question'],
            'answer_intro': answer.get('answer_intro', ''),
            'subtopics': json.dumps(answer.get('subtopics', []), ensure_ascii=False),
            'answer_outro': answer.get('answer_outro', ''),
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
