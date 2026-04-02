"""
두 스프레드시트를 조인하고, 파싱된 description 컬럼을 생성합니다.

1. description 시트: contents_product_no, description(원본 JSON), is_active
2. prepared_data 시트: content_no, content_nm, description, origin

작업:
- description 시트의 원본 JSON을 parse_product_content로 파싱
- prepared_data와 content_no 기준 outer join
- intro_title이 있는 행은 파싱 결과를 JSON으로 만들어 description 대체
- intro_title이 없는 행은 기존 description 유지
- 결과를 description 시트에 새 시트(joined_data)로 저장

사용법:
    python build_joined_description.py
"""
import json
import pandas as pd
from sheet_reader import read_google_sheet, write_dataframe_to_sheet
from parse_description_sheet import parse_row

# 시트 URL
DESCRIPTION_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1zOzLfY9eq1qitjvVUZjEqAOBQYe4mhgzqu2pbG7w_NE/edit?gid=847742278#gid=847742278'
PREPARED_DATA_SHEET_URL = 'https://docs.google.com/spreadsheets/d/19c8o63Lck04VWeOHyEXiEcYDBv92LcISR17xP7UZpfs/edit?gid=1853755425#gid=1853755425'
OUTPUT_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1zOzLfY9eq1qitjvVUZjEqAOBQYe4mhgzqu2pbG7w_NE/edit'
OUTPUT_SHEET_NAME = 'joined_data'

PARSED_COLS = [
    'intro_subtitle', 'intro_body', 'pick_info',
    'cp_ingredient', 'cp_production', 'cp_usage',
    'cp_brand', 'cp_certificate', 'review', 'tip', 'custom',
]


def main():
    # 1. 시트 읽기
    print("1. 시트 읽는 중...")
    df_desc = read_google_sheet(sheet_url=DESCRIPTION_SHEET_URL)
    print(f"   description 시트: {df_desc.shape}")

    df_prepared = read_google_sheet(sheet_url=PREPARED_DATA_SHEET_URL)
    print(f"   prepared_data 시트: {df_prepared.shape}")

    # 2. description 파싱
    print("\n2. description 파싱 중...")
    parsed_rows = [parse_row(row.get('description', '')) for _, row in df_desc.iterrows()]
    df_parsed = pd.concat([df_desc, pd.DataFrame(parsed_rows)], axis=1)
    df_parsed_clean = df_parsed.drop(columns=['description'])
    print(f"   파싱 완료: {len(df_parsed_clean)}행")

    # 3. 조인
    print("\n3. 조인 중...")
    df_parsed_clean['contents_product_no'] = df_parsed_clean['contents_product_no'].astype(str).str.strip()
    df_prepared['content_no'] = df_prepared['content_no'].astype(str).str.strip()

    merged = pd.merge(
        df_prepared, df_parsed_clean,
        left_on='content_no', right_on='contents_product_no',
        how='outer', indicator=True,
    )

    both = (merged['_merge'] == 'both').sum()
    left_only = (merged['_merge'] == 'left_only').sum()
    right_only = (merged['_merge'] == 'right_only').sum()
    print(f"   both: {both}, left_only: {left_only}, right_only: {right_only}")

    merged = merged.drop(columns=['contents_product_no', '_merge'])

    # 4. intro_title 있는 행의 description을 파싱 결과 JSON으로 대체
    print("\n4. description 재구성 중...")
    updated = 0
    for idx, row in merged.iterrows():
        intro_title = row.get('intro_title')
        if not intro_title or str(intro_title).strip() == '':
            continue

        desc_obj = {'intro_title': str(intro_title).strip()}
        for col in PARSED_COLS:
            val = row.get(col)
            if val and str(val).strip():
                desc_obj[col] = str(val).strip()

        merged.at[idx, 'description'] = json.dumps(desc_obj, ensure_ascii=False)
        updated += 1

    print(f"   description 대체: {updated}개")
    print(f"   기존 유지: {len(merged) - updated}개")

    # 5. 저장
    print("\n5. 시트에 저장 중...")
    write_dataframe_to_sheet(
        merged,
        sheet_name=OUTPUT_SHEET_NAME,
        sheet_url=OUTPUT_SHEET_URL,
    )
    print("완료!")


if __name__ == '__main__':
    main()
