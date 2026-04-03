"""
qna_data 시트에서 question_list를 읽어
카테고리별 [질문 - content_no 리스트] 형태로 변환합니다.
완전 동일 질문은 content_no를 합칩니다.
"""
import json
import pandas as pd
from sheet_reader import read_google_sheet


def main():
    # 1. qna_data 시트 읽기
    print("qna_data 시트 읽는 중...")
    df = read_google_sheet(sheet_name='qna_data')
    print(f"Read Shape: {df.shape}")

    # 2. 카테고리별로 {질문: set(content_no)} 구조로 역전
    inverted = {}

    for _, row in df.iterrows():
        content_no = int(row['content_no'])
        q_list_raw = row.get('question_list', '{}')

        if not q_list_raw or q_list_raw in ('{}', '[]', ''):
            continue

        try:
            q_dict = json.loads(q_list_raw) if isinstance(q_list_raw, str) else q_list_raw
        except json.JSONDecodeError:
            continue

        if not isinstance(q_dict, dict):
            continue

        for category, qs in q_dict.items():
            if not isinstance(qs, list):
                continue
            if category not in inverted:
                inverted[category] = {}
            for q in qs:
                if isinstance(q, str) and q.strip():
                    q = q.strip()
                    if q not in inverted[category]:
                        inverted[category][q] = set()
                    inverted[category][q].add(content_no)

    # 3. 통계 출력
    total_before = sum(
        sum(len(contents) for contents in cat.values())
        for cat in inverted.values()
    )
    total_unique = sum(len(cat) for cat in inverted.values())
    total_merged = total_before - total_unique

    print(f"\n총 질문-상품 쌍: {total_before}개")
    print(f"고유 질문 수: {total_unique}개")
    print(f"동일 질문 통합: {total_merged}건 병합됨")
    print()

    for category in inverted:
        qs = inverted[category]
        duplicates = sum(1 for v in qs.values() if len(v) > 1)
        print(f"  {category}: 고유 질문 {len(qs)}개 (중복 통합된 질문 {duplicates}개)")

    # 4. CSV로 저장
    rows = []
    for category in inverted:
        for question, content_nos in inverted[category].items():
            rows.append({
                'category': category,
                'question': question,
                'content_count': len(content_nos),
                'content_list': json.dumps(sorted(content_nos), ensure_ascii=False)
            })

    df_out = pd.DataFrame(rows)
    df_out = df_out.sort_values(['category', 'content_count'], ascending=[True, False])

    import os
    os.makedirs('output', exist_ok=True)
    output_file = 'output/inverted_questions.csv'
    df_out.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n{output_file} 저장 완료 ({len(df_out)}행)")


if __name__ == '__main__':
    main()
