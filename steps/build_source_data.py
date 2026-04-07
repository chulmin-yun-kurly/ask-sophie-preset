"""
4개 시트(상품_코어_테이블, OCR_results, OCR_results_2, new_description)를 읽어
merged_final 형태의 원천 데이터를 생성합니다.

description 우선순위: new_description 파싱 결과 > OCR 기반 JSON > 빈 문자열

사용법:
    python -m steps.build_source_data
    python -m steps.build_source_data --sheet-url https://docs.google.com/spreadsheets/d/XXXX/edit
    python -m steps.build_source_data --products 상품테이블 --new-desc 신규상세 --ocr OCR --ocr2 OCR2 --output 결과
"""
import argparse
import json
import pandas as pd
from sheet_reader import read_google_sheet, write_dataframe_to_sheet
from parse_description_sheet import parse_row

GV_TYPE_MAP = {
    'A01': 'main_title',
    'A04': 'kurlys_checkpoint_1',
    'A05': 'kurlys_checkpoint_2',
    'A06': 'kurlys_tip_1',
    'A07': 'kurlys_pick',
    'A08': 'kurlys_tip_2',
    'A15': 'about_brand',
}
ALLOWED_GV_TYPES = list(GV_TYPE_MAP.keys())

# 기본 시트 이름
DEFAULT_SHEETS = {
    'products': '상품_코어_테이블',
    'new_desc': 'new_description',
    'ocr': 'OCR_results',
    'ocr2': 'OCR_results_2',
    'output': 'merged_final',
}


def _read_sheet(sheet_url: str | None, sheet_name: str) -> pd.DataFrame:
    """sheet_url이 있으면 URL 기반, 없으면 기본 스프레드시트에서 읽기."""
    if sheet_url:
        return read_google_sheet(sheet_url=f"{sheet_url}#gid=0", sheet_name=sheet_name)
    return read_google_sheet(sheet_name=sheet_name)


def step1_load_products(sheet_url: str | None, sheet_name: str) -> pd.DataFrame:
    """상품_코어_테이블에서 is_display=1 상품 리스트를 생성합니다."""
    print(f"1. '{sheet_name}' 읽는 중...")
    df = _read_sheet(sheet_url, sheet_name)
    print(f"   원본: {len(df)}행")

    df['is_display'] = df['is_display'].astype(int)
    df = df[df['is_display'] == 1]
    df = df.sort_values('deal_no').drop_duplicates(subset='content_no', keep='first')
    df = df[['content_no', 'content_nm', 'master_cd']].reset_index(drop=True)
    print(f"   is_display=1 + 중복 제거 후: {len(df)}행")
    return df


def step2_parse_new_description(sheet_url: str | None, sheet_name: str) -> dict:
    """new_description 시트에서 파싱된 description을 생성합니다."""
    print(f"\n2. '{sheet_name}' 읽는 중...")
    df = _read_sheet(sheet_url, sheet_name)
    print(f"   원본: {len(df)}행")

    desc_map = {}
    empty_count = 0
    for _, row in df.iterrows():
        content_no = str(row.get('contents_product_no', ''))
        if not content_no:
            continue

        raw_desc = row.get('description', '')
        parsed = parse_row(raw_desc)

        # 모든 값이 빈 문자열이면 "없음"으로 처리
        if all(v == '' for v in parsed.values()):
            empty_count += 1
            continue

        # 빈 키 제거 후 JSON 직렬화
        parsed_clean = {k: v for k, v in parsed.items() if v}
        desc_map[content_no] = json.dumps(parsed_clean, ensure_ascii=False)

    print(f"   파싱 성공: {len(desc_map)}건, 빈 결과: {empty_count}건")
    return desc_map


def step3_build_ocr_description(sheet_url: str | None, sheet_name: str, product_content_nos: set) -> dict:
    """OCR_results에서 OCR 기반 description JSON을 생성합니다."""
    print(f"\n3. '{sheet_name}' 읽는 중...")
    df_ocr = _read_sheet(sheet_url, sheet_name)
    print(f"   원본: {len(df_ocr)}행")

    # gv_type 필터
    df_ocr = df_ocr[df_ocr['gv_type'].isin(ALLOWED_GV_TYPES)]
    print(f"   gv_type 필터 후: {len(df_ocr)}행")

    # 필요한 상품만 필터 (new_description에 없는 것들)
    df_ocr = df_ocr[df_ocr['goodsno'].isin(product_content_nos)]

    # 불필요 컬럼 제거
    drop_cols = [c for c in ['gv_image01', 'image_url', 'master_cd'] if c in df_ocr.columns]
    df_ocr = df_ocr.drop(columns=drop_cols)

    # 중복 제거: table_update_dt 내림차순 → 최신만 유지
    df_ocr = df_ocr.sort_values('table_update_dt', ascending=False)
    df_ocr = df_ocr.drop_duplicates(
        subset=['goodsno', 'gv_type', 'gv_lagertitle', 'gv_order'],
        keep='first'
    )
    print(f"   중복 제거 후: {len(df_ocr)}행")

    # HTML 태그 제거
    df_ocr['gv_contents'] = df_ocr['gv_contents'].str.replace(r'<[^>]+>', '', regex=True)
    df_ocr['gv_contents'] = df_ocr['gv_contents'].str.replace('&#12539;', '', regex=False)

    # content_no별 그룹화 → JSON 생성
    ocr_map = {}
    for content_no, group in df_ocr.groupby('goodsno'):
        entries = []
        for _, row in group.iterrows():
            if pd.isna(row['gv_type']):
                continue
            entry = {
                'gv_type': GV_TYPE_MAP.get(row['gv_type'], row['gv_type']),
                'gv_sub_title': row['gv_lagertitle'] if pd.notna(row.get('gv_lagertitle')) else None,
                'gv_order': row['gv_order'] if pd.notna(row.get('gv_order')) else None,
                'gv_contents': row['gv_contents'] if pd.notna(row.get('gv_contents')) else None,
                'gv_contents_ocr': row['ocr_result'] if pd.notna(row.get('ocr_result')) else None,
            }
            entries.append(entry)
        if entries:
            ocr_map[str(content_no)] = json.dumps(entries, ensure_ascii=False)

    print(f"   OCR description 생성: {len(ocr_map)}건")
    return ocr_map


def step4_load_origin(sheet_url: str | None, sheet_name: str) -> dict:
    """OCR_results_2에서 master_cd → origin 매핑을 생성합니다."""
    print(f"\n4. '{sheet_name}' 읽는 중...")
    df = _read_sheet(sheet_url, sheet_name)
    print(f"   원본: {len(df)}행")

    df = df[['master_cd', 'origin']].drop_duplicates(subset='master_cd', keep='first')
    origin_map = {}
    for _, row in df.iterrows():
        mc = row['master_cd']
        if mc and pd.notna(mc):
            origin_map[mc] = row['origin'] if pd.notna(row['origin']) else ''

    print(f"   origin 매핑: {len(origin_map)}건")
    return origin_map


def build_source_data(
    sheet_url: str | None = None,
    sheet_names: dict | None = None,
    output_json: str | None = None,
):
    """원천 데이터를 생성합니다."""
    names = {**DEFAULT_SHEETS, **(sheet_names or {})}

    # Step 1: 기본 상품 리스트
    df_products = step1_load_products(sheet_url, names['products'])

    # Step 2: new_description 파싱
    new_desc_map = step2_parse_new_description(sheet_url, names['new_desc'])

    # Step 3: OCR fallback (new_description에 없는 상품만 대상)
    all_content_nos = set(df_products['content_no'].astype(str))
    need_ocr = all_content_nos - set(new_desc_map.keys())
    print(f"\n   new_description 매칭: {len(all_content_nos) - len(need_ocr)}건")
    print(f"   OCR fallback 대상: {len(need_ocr)}건")

    ocr_desc_map = step3_build_ocr_description(sheet_url, names['ocr'], need_ocr) if need_ocr else {}

    # Step 4: origin
    origin_map = step4_load_origin(sheet_url, names['ocr2'])

    # Step 5: 최종 병합
    print("\n5. 최종 병합 중...")
    descriptions = []
    origins = []
    stats = {'new_desc': 0, 'ocr': 0, 'empty': 0}

    for _, row in df_products.iterrows():
        cno = str(row['content_no'])
        mcd = row['master_cd']

        if cno in new_desc_map:
            descriptions.append(new_desc_map[cno])
            stats['new_desc'] += 1
        elif cno in ocr_desc_map:
            descriptions.append(ocr_desc_map[cno])
            stats['ocr'] += 1
        else:
            descriptions.append('')
            stats['empty'] += 1

        origins.append(origin_map.get(mcd, ''))

    df_products['description'] = descriptions
    df_products['origin'] = origins

    df_final = df_products[['content_no', 'content_nm', 'description', 'origin']]

    print(f"\n   결과: {len(df_final)}행")
    print(f"   description 출처 — new_description: {stats['new_desc']}건, OCR: {stats['ocr']}건, 빈값: {stats['empty']}건")

    # 시트에 저장
    output_name = names['output']
    print(f"\n6. '{output_name}' 시트에 저장 중...")
    if sheet_url:
        write_dataframe_to_sheet(df_final, sheet_name=output_name, sheet_url=sheet_url)
    else:
        write_dataframe_to_sheet(df_final, sheet_name=output_name)
    print(f"완료! {len(df_final)}행 저장됨")

    # JSON 파일 저장
    if output_json:
        records = []
        for _, row in df_final.iterrows():
            desc = row['description']
            try:
                desc_parsed = json.loads(desc) if desc else None
            except (json.JSONDecodeError, TypeError):
                desc_parsed = desc or None
            records.append({
                'content_no': row['content_no'],
                'content_nm': row['content_nm'],
                'description': desc_parsed,
                'origin': row['origin'] or None,
            })

        with open(output_json, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"JSON 저장: {output_json} ({len(records)}건)")


def main():
    parser = argparse.ArgumentParser(description='원천 데이터(merged_final) 생성')
    parser.add_argument('--sheet-url', default=None,
                        help='스프레드시트 URL (미지정 시 기본 스프레드시트 사용)')
    parser.add_argument('--products', default=None, help='상품 코어 테이블 시트명')
    parser.add_argument('--new-desc', default=None, help='new_description 시트명')
    parser.add_argument('--ocr', default=None, help='OCR_results 시트명')
    parser.add_argument('--ocr2', default=None, help='OCR_results_2 시트명')
    parser.add_argument('--output', default=None, help='출력 시트명')
    parser.add_argument('--output-json', default=None,
                        help='결과를 JSON 파일로도 저장 (예: output/source_data.json)')
    args = parser.parse_args()

    sheet_names = {}
    if args.products:
        sheet_names['products'] = args.products
    if args.new_desc:
        sheet_names['new_desc'] = args.new_desc
    if args.ocr:
        sheet_names['ocr'] = args.ocr
    if args.ocr2:
        sheet_names['ocr2'] = args.ocr2
    if args.output:
        sheet_names['output'] = args.output

    build_source_data(
        sheet_url=args.sheet_url,
        sheet_names=sheet_names if sheet_names else None,
        output_json=args.output_json,
    )


if __name__ == '__main__':
    main()
