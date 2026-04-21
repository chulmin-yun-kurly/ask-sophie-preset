"""
공용 텍스트 교정 모듈.
배치 단위로 LLM을 호출하여 한국어 문법/맞춤법/표현을 교정합니다.
"""
import asyncio
from config import MODEL_MAIN, TEMP_CORRECT
from llm_client import load_prompt, chat_json


async def correct_texts(
    items: list[dict],
    batch_size: int,
    max_concurrent: int,
) -> dict[int, dict]:
    """텍스트 교정을 배치로 수행합니다.

    Args:
        items: [{"index": int, "fields": {"field_name": "텍스트", ...}}, ...]
               빈 문자열 필드는 자동으로 스킵됩니다.
        batch_size: 배치당 항목 수
        max_concurrent: 동시 요청 수

    Returns:
        {index: {"field_name": "교정된 텍스트", ...}}
    """
    if not items:
        return {}

    system_prompt = load_prompt('shared/correct_system.txt')
    user_template = load_prompt('shared/correct_user.txt')

    # 빈 필드 필터링: 실제 교정 대상이 있는 항목만 추출
    filtered_items = []
    for item in items:
        non_empty = {k: v for k, v in item['fields'].items() if v and v.strip()}
        if non_empty:
            filtered_items.append({'index': item['index'], 'fields': non_empty})

    if not filtered_items:
        return {}

    # 배치 분할
    batches = []
    for i in range(0, len(filtered_items), batch_size):
        batches.append(filtered_items[i:i + batch_size])

    total_batches = len(batches)
    results: dict[int, dict] = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def run_batch(batch_idx: int, batch: list[dict]):
        async with semaphore:
            # 유저 프롬프트 포맷
            items_text = ""
            for item in batch:
                items_text += f"\n[항목 #{item['index']}]\n"
                for field_name, text in item['fields'].items():
                    items_text += f"{field_name}: \"{text}\"\n"

            user_prompt = user_template.format(items_text=items_text)

            print(f"   교정 배치 {batch_idx + 1}/{total_batches} 처리 중...")
            try:
                parsed = await chat_json(
                    MODEL_MAIN, system_prompt, user_prompt,
                    temperature=TEMP_CORRECT,
                )
                corrections = parsed.get('corrections', [])
                for corr in corrections:
                    if not isinstance(corr, dict):
                        continue
                    idx = corr.get('index')
                    fields = corr.get('fields', {})
                    if idx is not None and isinstance(fields, dict):
                        results[idx] = fields
                print(f"   교정 배치 {batch_idx + 1}/{total_batches} 완료")
            except Exception as e:
                print(f"   교정 배치 {batch_idx + 1}/{total_batches} ERROR: {e}")

    tasks = [run_batch(i, batch) for i, batch in enumerate(batches)]
    await asyncio.gather(*tasks)

    # 교정 전/후 비교 출력
    originals = {item['index']: item['fields'] for item in filtered_items}
    diff_count = 0
    for idx in sorted(results.keys()):
        orig = originals.get(idx, {})
        corr = results[idx]
        for field_name, corrected in corr.items():
            original = orig.get(field_name, '')
            if original and corrected != original:
                diff_count += 1
                print(f"   [#{idx}] {field_name}")
                print(f"     before: {original[:120]}")
                print(f"     after : {corrected[:120]}")
    if diff_count == 0:
        print("   교정 변경 사항 없음 (모두 원문 유지)")
    else:
        print(f"   총 {diff_count}건 교정됨")

    return results
