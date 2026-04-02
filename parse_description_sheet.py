"""
구글 스프레드시트의 description 컬럼(상품 상세 JSON)을 파싱하여
구조화된 컬럼들을 추가합니다.

사용법:
    python parse_description_sheet.py
"""
import json
import pandas as pd
from sheet_reader import read_google_sheet, write_dataframe_to_sheet
from parse_product_content import parse_exposed_content, strip_html

SHEET_URL = 'https://docs.google.com/spreadsheets/d/1wns-ZF40PY5ISq3GIrqo_ANBvmy2N7dVnz4OrxB1BlE/edit?gid=252909041#gid=252909041'


def extract_block_text(blocks: list[dict], block_type: str) -> str:
    """특정 블록 타입의 텍스트를 추출합니다."""
    parts = []
    for b in blocks:
        if b['blockType'] != block_type:
            continue
        for m in b['modules']:
            text = m.get('text', '')
            if text:
                parts.append(text)
            for item in m.get('items', []):
                if isinstance(item, dict):
                    content = item.get('content', '')
                    if content:
                        parts.append(content)
    return '\n'.join(parts).strip()


def extract_check_points(blocks: list[dict]) -> dict[str, str]:
    """CHECK_POINT 블록에서 titleType별 내용을 추출합니다."""
    result = {}
    for b in blocks:
        if b['blockType'] != 'CHECK_POINT':
            continue
        for m in b['modules']:
            if m.get('type') != 'CHECK_POINT_LIST':
                continue
            for item in m.get('items', []):
                title_type = item.get('titleType', '')
                content = item.get('content', '')
                if title_type and content:
                    if title_type in result:
                        result[title_type] += '\n' + content
                    else:
                        result[title_type] = content
    return result


def extract_intro(blocks: list[dict]) -> dict[str, str]:
    """INTRO 블록에서 제목과 본문을 추출합니다."""
    title = ''
    subtitle = ''
    body = ''
    for b in blocks:
        if b['blockType'] != 'INTRO':
            continue
        for m in b['modules']:
            mod_type = m.get('type', '')
            text = m.get('text', '')
            if not text:
                continue
            if mod_type in ('TITLE_4',):
                subtitle = text
            elif mod_type in ('TITLE_1', 'TITLE_2', 'TITLE_3'):
                title = text
            elif mod_type == 'TEXT':
                body = text
    return {'title': title, 'subtitle': subtitle, 'body': body}


def parse_row(description_json: str) -> dict:
    """description JSON을 파싱하여 구조화된 딕셔너리를 반환합니다."""
    result = {
        'intro_subtitle': '',
        'intro_title': '',
        'intro_body': '',
        'pick_info': '',
        'cp_ingredient': '',
        'cp_production': '',
        'cp_usage': '',
        'cp_brand': '',
        'cp_certificate': '',
        'review': '',
        'tip': '',
        'custom': '',
    }

    try:
        data = json.loads(description_json)
    except (json.JSONDecodeError, TypeError):
        return result

    blocks = parse_exposed_content(data)

    # INTRO
    intro = extract_intro(blocks)
    result['intro_subtitle'] = intro['subtitle']
    result['intro_title'] = intro['title']
    result['intro_body'] = intro['body']

    # PICK
    result['pick_info'] = extract_block_text(blocks, 'PICK')

    # CHECK_POINT
    cps = extract_check_points(blocks)
    result['cp_ingredient'] = cps.get('INGREDIENT', '') or cps.get('INGREDIENT_2', '')
    if 'INGREDIENT' in cps and 'INGREDIENT_2' in cps:
        result['cp_ingredient'] = cps['INGREDIENT'] + '\n' + cps['INGREDIENT_2']
    result['cp_production'] = cps.get('PRODUCTION_DISTRIBUTION_PROCESS', '')
    result['cp_usage'] = cps.get('USAGE', '')
    result['cp_brand'] = cps.get('BRAND_WINNING', '')
    result['cp_certificate'] = cps.get('CERTIFICATE_WINNING', '')

    # REVIEW (상품위원회 한줄평)
    review_parts = []
    for b in blocks:
        if b['blockType'] != 'REVIEW':
            continue
        for m in b['modules']:
            if m.get('type') == 'REVIEW_LIST':
                for item in m.get('items', []):
                    title = item.get('title', '')
                    content = item.get('content', '')
                    if title and content:
                        review_parts.append(f"[{title}] {content}")
                    elif content:
                        review_parts.append(content)
    result['review'] = '\n'.join(review_parts)

    # TIP
    result['tip'] = extract_block_text(blocks, 'TIP')

    # CUSTOM
    result['custom'] = extract_block_text(blocks, 'CUSTOM')

    return result


def main():
    # 1. 시트 읽기
    print("1. 스프레드시트 읽는 중...")
    df = read_google_sheet(sheet_url=SHEET_URL)
    print(f"   Shape: {df.shape}, 컬럼: {df.columns.tolist()}")

    # 2. description 파싱
    print("\n2. description 파싱 중...")
    parsed_rows = []
    for idx, row in df.iterrows():
        parsed = parse_row(row.get('description', ''))
        parsed_rows.append(parsed)

    df_parsed = pd.DataFrame(parsed_rows)
    print(f"   파싱 완료: {len(df_parsed)}행, 추가 컬럼 {len(df_parsed.columns)}개")

    # 3. 원본 + 파싱 결과 병합
    df_result = pd.concat([df, df_parsed], axis=1)

    # 요약 출력
    print("\n   컬럼별 비어있지 않은 행 수:")
    for col in df_parsed.columns:
        non_empty = (df_parsed[col].str.strip() != '').sum()
        print(f"     {col}: {non_empty}/{len(df_parsed)}")

    # 4. 시트에 저장
    print("\n3. 시트에 저장 중...")
    write_dataframe_to_sheet(
        df_result,
        sheet_name='parsed_description',
        sheet_url=SHEET_URL,
    )
    print("완료!")


if __name__ == '__main__':
    main()
