"""
compare_question 시트를 읽어 id를 부여하고 compare_prepared 시트로 저장합니다.
"""
import sys
import pandas as pd
from sheet_reader import read_google_sheet, write_dataframe_to_sheet


def main():
    # 1. compare_question 시트 읽기
    df = read_google_sheet(sheet_name='compare_question')
    print(f"Read Shape: {df.shape}")

    if 'question' not in df.columns:
        print("✗ compare_question 시트에 'question' 컬럼이 없습니다.")
        sys.exit(1)

    # 2. 빈 question 제거
    df = df[df['question'].astype(str).str.strip() != ''].reset_index(drop=True)
    if df.empty:
        print("✗ 비교 질문이 하나도 없습니다.")
        sys.exit(1)

    # 3. id 부여 (compare_001 포맷)
    ids = [f"compare_{i+1:03d}" for i in range(len(df))]

    # 4. compare_prepared 스키마에 맞춰 DataFrame 구성
    df_out = pd.DataFrame({
        'id': ids,
        'question': df['question'].astype(str).str.strip(),
        'candidate_list': ['[]'] * len(df),
        'content_list': ['[]'] * len(df),
        'match_rationale': [''] * len(df),
    })

    # 5. 저장
    write_dataframe_to_sheet(df_out, sheet_name='compare_prepared')
    print(f"Successfully wrote {len(df_out)} rows to 'compare_prepared' sheet")


if __name__ == '__main__':
    main()
