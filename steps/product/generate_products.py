"""
prepared_data의 각 상품에 대해 소개 및 홍보 텍스트를 LLM으로 생성합니다.
description이 있는 상품만 대상으로 합니다.
"""
import asyncio
from config import MODEL_MAIN, PREPARE_BATCH_SIZE, PREPARE_MAX_CONCURRENT
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

def _ensure_str(value) -> str:
    """LLM이 리스트로 반환할 경우 '- ' 구분 문자열로 변환합니다."""
    if isinstance(value, list):
        return '\n'.join(f'- {v}' for v in value)
    return str(value) if value else ''


async def generate_batch(items: list[dict], system_prompt: str, user_template: str) -> list[dict]:
    """여러 상품을 한 번의 API 요청으로 처리합니다."""
    products_text = ""
    for pos, item in enumerate(items):
        products_text += f"""
---
[상품 #{pos}]
상품명: {item['content_nm']}
핵심 요약: {item['key_description']}
상품 상세 설명:
{item['description']}
"""

    user_prompt = user_template.format(products_text=products_text)
    parsed = await chat_json(MODEL_MAIN, system_prompt, user_prompt, temperature=0.5)
    return parsed.get('results', [])


async def process_all(items: list[dict]) -> dict:
    """배치를 만들고 비동기 병렬로 처리합니다."""
    system_prompt = build_system_prompt(load_prompt('product/product_system.txt'))
    user_template = load_prompt('product/product_user.txt')

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
                batch_results = await generate_batch(batch_items, system_prompt, user_template)
                for r in batch_results:
                    idx = r.get('index', -1)
                    if 0 <= idx < len(batch_items):
                        original_idx = batch_items[idx]['original_idx']
                        results[original_idx] = {
                            'headline': _ensure_str(r.get('headline', '')),
                            'strengths': _ensure_str(r.get('strengths', '')),
                            'stories': _ensure_str(r.get('stories', '')),
                            'targetUser': _ensure_str(r.get('targetUser', '')),
                        }
                print(f"   배치 {batch_idx + 1}/{len(batches)} 완료")
            except Exception as e:
                print(f"   배치 {batch_idx + 1}/{len(batches)} ERROR: {e}")

    tasks = [run_batch(i, batch) for i, batch in enumerate(batches)]
    await asyncio.gather(*tasks)
    return results


async def main():
    # 1. prepared_data 시트 읽기
    print("1. prepared_data 시트 읽는 중...")
    df = read_google_sheet(sheet_name='prepared_data')
    print(f"   전체: {len(df)}건")

    # 2. description이 있는 상품만 필터
    items = []
    for i, row in df.iterrows():
        desc = row.get('description', '')
        if desc and desc not in ('[]', ''):
            items.append({
                'original_idx': i,
                'content_nm': row['content_nm'],
                'key_description': row.get('key_description', ''),
                'description': desc,
            })

    print(f"   description 있는 상품: {len(items)}건 (스킵: {len(df) - len(items)}건)")

    # 3. LLM으로 홍보 텍스트 생성
    print("\n2. 홍보 텍스트 생성 중...")
    results = await process_all(items)
    print(f"   생성 완료: {len(results)}건")

    # 4. 결과 DataFrame 구성
    print("\n3. 결과 정리 중...")
    product_fields = ['headline', 'strengths', 'stories', 'targetUser']
    df_out = df[['content_no', 'content_nm']].copy()
    for field in product_fields:
        df_out[field] = [results.get(i, {}).get(field, '') for i in range(len(df))]

    # description 없는 행 제거 (결과가 없는 행)
    df_out = df_out[df_out['headline'] != ''].reset_index(drop=True)

    # 요약 출력
    print("\n4. 결과 저장 중...")
    for _, row in df_out.iterrows():
        headline = row['headline'].replace('\n', ' ')[:60]
        print(f"   [{row['content_no']}] {row['content_nm']}: {headline}")

    write_dataframe_to_sheet(df_out, sheet_name='product_data')
    print(f"\nSuccessfully wrote {len(df_out)} rows to 'product_data' sheet")


if __name__ == '__main__':
    asyncio.run(main())
