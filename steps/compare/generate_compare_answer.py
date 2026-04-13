"""
compare_prepared의 질문/선정 상품을 바탕으로 비교축 중심 답변을 생성합니다.
compare_qna 시트에 최종 결과를 기록합니다.
"""
import json
import asyncio
import sys
import time
import pandas as pd
from config import (
    MODEL_MAIN,
    COMPARE_MAX_CONCURRENT,
    TEMP_COMPARE_ANSWER,
)
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

MAX_RETRY_ROUNDS = 3


def _topic_keyword_text(raw) -> str:
    if raw is None:
        return ''
    if isinstance(raw, list):
        return ', '.join(str(x) for x in raw)
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return ''
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return ', '.join(str(x) for x in parsed)
        except (json.JSONDecodeError, TypeError):
            pass
        return s
    return str(raw)


def build_content_map(df_prepared: pd.DataFrame) -> dict:
    m = {}
    for _, row in df_prepared.iterrows():
        try:
            cno = int(row['content_no'])
        except (TypeError, ValueError, KeyError):
            continue
        m[cno] = {
            'content_nm': row.get('content_nm', ''),
            'origin': row.get('origin', ''),
            'key_description': row.get('key_description', ''),
            'topic_keyword': row.get('topic_keyword', ''),
        }
    return m


def format_products(content_nos: list[int], content_map: dict) -> str:
    lines = []
    for cno in content_nos:
        info = content_map.get(int(cno))
        if not info:
            continue
        origin = info.get('origin', '') or ''
        kw = _topic_keyword_text(info.get('topic_keyword', ''))
        lines.append(
            f"[content_no={cno}]\n"
            f"상품명: {info.get('content_nm', '')}\n"
            f"원산지: {origin}\n"
            f"핵심설명: {info.get('key_description', '')}\n"
            f"키워드: {kw}"
        )
    return "\n\n".join(lines)


def _clean_comparison(data, allowed_nos: set[int]) -> dict | None:
    """comparison 블록의 headers/rows를 검증·정제."""
    if not isinstance(data, dict):
        return None
    headers = data.get('headers', [])
    rows = data.get('rows', [])
    if not isinstance(headers, list) or len(headers) < 3:
        return None
    # headers[0]은 빈 문자열, 나머지는 그룹 라벨
    headers = [str(h) if h is not None else '' for h in headers]
    headers[0] = ''
    group_headers = headers[1:]
    if any(not h.strip() for h in group_headers):
        return None

    if not isinstance(rows, list) or len(rows) < 2:
        return None
    cleaned_rows = []
    for row in rows:
        if not isinstance(row, dict):
            return None
        label = row.get('label', '')
        values = row.get('values', [])
        if not label or not isinstance(values, list):
            return None
        if len(values) != len(group_headers):
            return None
        cleaned_values = []
        for v in values:
            if not isinstance(v, str) or not v.strip():
                return None
            cleaned_values.append(v.strip())
        cleaned_rows.append({'label': str(label).strip(), 'values': cleaned_values})

    return {'headers': headers, 'rows': cleaned_rows}


def _clean_content(blocks_raw, allowed_nos: set[int]) -> tuple[list[dict], list[int]] | None:
    """content 블록 배열을 검증·정제. 성공 시 (blocks, productNos) 반환."""
    if not isinstance(blocks_raw, list) or not blocks_raw:
        return None

    cleaned: list[dict] = []
    counts = {'intro': 0, 'title': 0, 'comparison': 0, 'productNos': 0, 'outro': 0}
    product_nos_final: list[int] = []

    for block in blocks_raw:
        if not isinstance(block, dict):
            return None
        btype = block.get('type', '')
        data = block.get('data')

        if btype in ('intro', 'outro', 'title', 'description'):
            if not isinstance(data, str) or not data.strip():
                return None
            cleaned.append({'type': btype, 'data': data.strip()})
            if btype in counts:
                counts[btype] += 1
        elif btype == 'comparison':
            comp = _clean_comparison(data, allowed_nos)
            if comp is None:
                return None
            cleaned.append({'type': 'comparison', 'data': comp})
            counts['comparison'] += 1
        elif btype == 'productNos':
            if not isinstance(data, list):
                return None
            nos: list[int] = []
            for item in data:
                try:
                    n_int = int(item)
                except (TypeError, ValueError):
                    continue
                if n_int in allowed_nos and n_int not in nos:
                    nos.append(n_int)
            if not nos:
                return None
            cleaned.append({'type': 'productNos', 'data': nos})
            product_nos_final = nos
            counts['productNos'] += 1
        else:
            # 알 수 없는 타입은 무시
            continue

    # 필수 블록 확인
    if counts['intro'] < 1 or counts['outro'] < 1:
        return None
    if counts['title'] < 1 or counts['comparison'] < 1:
        return None
    if counts['productNos'] < 1:
        return None

    # 간단한 순서 검증: 첫 블록 intro, 마지막 블록 outro
    if cleaned[0]['type'] != 'intro' or cleaned[-1]['type'] != 'outro':
        return None

    return cleaned, product_nos_final


async def generate_one(question: str, products_text: str, allowed_nos: set[int]) -> dict | None:
    system_prompt = build_system_prompt(load_prompt('compare/answer_system.txt'))
    user_prompt = load_prompt('compare/answer_user.txt').format(
        question=question,
        products_text=products_text,
    )
    parsed = await chat_json(
        MODEL_MAIN, system_prompt, user_prompt, temperature=TEMP_COMPARE_ANSWER
    )

    blocks_raw = parsed.get('content', [])
    cleaned = _clean_content(blocks_raw, allowed_nos)
    if cleaned is None:
        return None
    content, product_nos = cleaned
    return {'content': content, 'productNos': product_nos}


async def process_questions(items: list[dict], content_map: dict) -> dict[int, dict]:
    semaphore = asyncio.Semaphore(COMPARE_MAX_CONCURRENT)
    results: dict[int, dict] = {}

    async def _one(i: int):
        async with semaphore:
            item = items[i]
            content_nos = item['content_nos']
            products_text = format_products(content_nos, content_map)
            if not products_text:
                print(f"   ⚠ [{item['id']}] 상품 상세를 찾지 못해 스킵")
                return
            try:
                parsed = await generate_one(
                    item['question'], products_text, set(content_nos)
                )
            except Exception as e:
                print(f"   ⚠ [{item['id']}] 답변 생성 실패: {e}")
                return
            if parsed is None:
                print(f"   ⚠ [{item['id']}] content 스키마 부적합 → 재시도 대상")
                return
            results[i] = parsed
            print(f"   [{item['id']}] 답변 생성 완료 (blocks {len(parsed['content'])}개)")

    await asyncio.gather(*[_one(i) for i in range(len(items))])
    return results


async def main():
    # 1. 시트 읽기
    print("1. 시트 읽는 중...")
    df_compare = read_google_sheet(sheet_name='compare_prepared')
    df_prepared = read_google_sheet(sheet_name='prepared_data')
    print(f"   compare_prepared: {df_compare.shape}")
    print(f"   prepared_data: {df_prepared.shape}")

    if df_compare.empty:
        print("✗ compare_prepared 시트가 비어 있습니다.")
        sys.exit(1)

    content_map = build_content_map(df_prepared)

    # 2. 아이템 준비
    items = []
    for _, row in df_compare.iterrows():
        try:
            content_nos = json.loads(row.get('content_list', '[]'))
        except (json.JSONDecodeError, TypeError):
            content_nos = []
        content_nos = [int(x) for x in content_nos if isinstance(x, (int, str)) and str(x).strip().lstrip('-').isdigit()]
        items.append({
            'id': row['id'],
            'question': row['question'],
            'content_nos': content_nos,
        })

    empty_items = [it['id'] for it in items if not it['content_nos']]
    if empty_items:
        print(f"✗ content_list가 비어 있는 질문이 있습니다: {empty_items}. match 단계를 먼저 실행하세요.")
        sys.exit(1)

    # 3. 답변 생성 (재시도 포함)
    print(f"\n2. 비교 답변 생성 (동시 {COMPARE_MAX_CONCURRENT}개)...")
    start = time.time()
    all_results: dict[int, dict] = {}
    for attempt in range(1, MAX_RETRY_ROUNDS + 1):
        pending = [i for i in range(len(items)) if i not in all_results]
        if not pending:
            break
        label = f"라운드 {attempt}/{MAX_RETRY_ROUNDS}" if attempt > 1 else "처리"
        print(f"\n   {label}: {len(pending)}건...")
        pending_items = [items[i] for i in pending]
        round_results = await process_questions(pending_items, content_map)
        for local_idx, value in round_results.items():
            all_results[pending[local_idx]] = value

    elapsed = time.time() - start
    print(f"\n   완료: {elapsed:.1f}초")

    missing = [items[i]['id'] for i in range(len(items)) if i not in all_results]
    if missing:
        print(f"\n✗ {MAX_RETRY_ROUNDS}회 재시도 후에도 {len(missing)}건 누락: {missing}")
        sys.exit(1)

    # 4. compare_qna 시트 구성
    print("\n3. compare_qna 시트 저장 중...")
    out_rows = []
    for i, item in enumerate(items):
        res = all_results[i]
        out_rows.append({
            'id': item['id'],
            'question': item['question'],
            'content_list': json.dumps(item['content_nos'], ensure_ascii=False),
            'productNos': json.dumps(res['productNos'], ensure_ascii=False),
            'content': json.dumps(res['content'], ensure_ascii=False),
        })
    df_out = pd.DataFrame(out_rows, columns=[
        'id', 'question', 'content_list', 'productNos', 'content',
    ])

    write_dataframe_to_sheet(df_out, sheet_name='compare_qna')
    print(f"Successfully wrote {len(df_out)} rows to 'compare_qna' sheet")


if __name__ == '__main__':
    asyncio.run(main())
