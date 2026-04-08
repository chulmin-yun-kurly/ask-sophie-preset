"""
prepared_data의 각 상품에 대해 소개 및 홍보 텍스트를 LLM으로 생성합니다.
description이 있는 상품만 대상으로 합니다.
이미 product_data에 존재하는 상품은 건너뛰고, 미처리분만 생성합니다.
누락이 있으면 최대 MAX_RETRY_ROUNDS회 재시도합니다.
"""
import asyncio
import sys
import pandas as pd
from config import MODEL_MAIN, PREPARE_BATCH_SIZE, PREPARE_MAX_CONCURRENT
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

MAX_RETRY_ROUNDS = 3


def _ensure_str(value) -> str:
    """LLM이 리스트로 반환할 경우 '- ' 구분 문자열로 변환합니다."""
    if isinstance(value, list):
        return '\n'.join(f'- {v}' for v in value)
    return str(value) if value else ''


PRODUCT_FIELDS = ['intro', 'headline', 'features', 'story', 'recommendation', 'outro']


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
                    if not isinstance(r, dict):
                        continue
                    idx = int(r.get('index', -1))
                    if 0 <= idx < len(batch_items):
                        content_no = batch_items[idx]['content_no']
                        results[content_no] = {
                            'content_no': content_no,
                            'content_nm': batch_items[idx]['content_nm'],
                        }
                        for field in PRODUCT_FIELDS:
                            results[content_no][field] = _ensure_str(r.get(field, ''))
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

    # description이 있는 상품 필터
    target_items = []
    for _, row in df.iterrows():
        desc = row.get('description', '')
        if desc and desc not in ('[]', ''):
            target_items.append({
                'content_no': int(row['content_no']),
                'content_nm': row['content_nm'],
                'key_description': row.get('key_description', ''),
                'description': desc,
            })

    print(f"   description 있는 상품: {len(target_items)}건 (스킵: {len(df) - len(target_items)}건)")

    # 2. 기존 product_data 시트 확인 → 미처리분 파악
    print("\n2. 기존 product_data 확인 중...")
    existing = {}
    try:
        df_existing = read_google_sheet(sheet_name='product_data')
        for _, row in df_existing.iterrows():
            cno = int(row['content_no'])
            # headline이 비어있으면 미처리로 간주
            if row.get('headline', ''):
                existing[cno] = row.to_dict()
        print(f"   기존 처리 완료: {len(existing)}건")
    except Exception:
        print(f"   기존 데이터 없음")

    pending_items = [item for item in target_items if item['content_no'] not in existing]
    print(f"   미처리: {len(pending_items)}건")

    if not pending_items:
        print("\n보완할 상품이 없습니다.")
        # 검증만 수행
        _verify_and_save(target_items, existing, {})
        return

    # 3. LLM으로 미처리분 생성 (재시도 포함)
    all_new_results = {}
    for attempt in range(1, MAX_RETRY_ROUNDS + 1):
        # 이번 라운드에서 처리할 항목
        still_pending = [item for item in pending_items if item['content_no'] not in all_new_results]
        if not still_pending:
            break

        label = f"라운드 {attempt}/{MAX_RETRY_ROUNDS}" if attempt > 1 else "생성"
        print(f"\n3. 홍보 텍스트 {label} ({len(still_pending)}건)...")
        round_results = await process_all(still_pending)
        all_new_results.update(round_results)
        print(f"   {label} 완료: {len(round_results)}건 (누적: {len(all_new_results)}건)")

        if len(all_new_results) == len(pending_items):
            break

        if attempt < MAX_RETRY_ROUNDS:
            remaining = len(pending_items) - len(all_new_results)
            print(f"   ⚠ {remaining}건 누락 → 재시도...")

    # 4. 기존 + 신규 병합 후 저장
    _verify_and_save(target_items, existing, all_new_results)


def _verify_and_save(target_items: list, existing: dict, new_results: dict):
    """기존 + 신규를 병합하고, 검증 후 저장합니다."""
    print("\n4. 결과 병합 및 검증 중...")

    rows = []
    missing = []
    for item in target_items:
        cno = item['content_no']
        if cno in new_results:
            rows.append(new_results[cno])
        elif cno in existing:
            rows.append({
                'content_no': cno,
                'content_nm': existing[cno].get('content_nm', ''),
                **{f: existing[cno].get(f, '') for f in PRODUCT_FIELDS},
            })
        else:
            missing.append(cno)

    if missing:
        print(f"   ⚠ 미처리 상품 {len(missing)}건 남음: {missing[:10]}{'...' if len(missing) > 10 else ''}")

    df_out = pd.DataFrame(rows)

    # 검증: target 수 vs 결과 수
    print(f"\n   검증: description 있는 상품 {len(target_items)}건 → product_data {len(df_out)}건", end='')
    if len(df_out) == len(target_items):
        print(" ✓")
    else:
        print(f" ✗ (차이 {len(target_items) - len(df_out)}건)")
        print(f"\n✗ {MAX_RETRY_ROUNDS}회 재시도 후에도 누락이 있어 파이프라인을 중단합니다.")
        sys.exit(1)

    # 저장
    print("\n5. 결과 저장 중...")
    for _, row in df_out.iterrows():
        headline = str(row.get('headline', '')).replace('\n', ' ')[:60]
        print(f"   [{row['content_no']}] {row['content_nm']}: {headline}")

    write_dataframe_to_sheet(df_out, sheet_name='product_data')
    print(f"\nSuccessfully wrote {len(df_out)} rows to 'product_data' sheet")


if __name__ == '__main__':
    asyncio.run(main())
