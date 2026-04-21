"""
qna_group 시트의 답변 텍스트를 교정합니다.
교정 대상: answer_intro, answer_outro, subtopics[].description
"""
import asyncio
import json
import pandas as pd
from config import CORRECT_BATCH_SIZE, CORRECT_MAX_CONCURRENT
from sheet_reader import read_google_sheet, write_dataframe_to_sheet
from steps.shared.correct_text import correct_texts


async def main():
    # 1. 시트 읽기
    print("1. qna_group 시트 읽는 중...")
    df = read_google_sheet(sheet_name='qna_group')
    print(f"   qna_group: {df.shape}")

    # 2. 교정 대상 필드 추출
    print("\n2. 교정 대상 추출 중...")
    items = []
    for idx, row in df.iterrows():
        fields = {}

        # 직접 컬럼
        intro = row.get('answer_intro', '')
        if intro and str(intro).strip():
            fields['answer_intro'] = str(intro)

        outro = row.get('answer_outro', '')
        if outro and str(outro).strip():
            fields['answer_outro'] = str(outro)

        # subtopics JSON에서 description 추출
        subtopics_raw = row.get('subtopics', '')
        if subtopics_raw and str(subtopics_raw).strip():
            try:
                subtopics = json.loads(str(subtopics_raw))
                if isinstance(subtopics, list):
                    for i, st in enumerate(subtopics):
                        desc = st.get('description', '') if isinstance(st, dict) else ''
                        if desc and desc.strip():
                            fields[f'description_{i}'] = desc
            except (json.JSONDecodeError, TypeError):
                pass

        if fields:
            items.append({'index': idx, 'fields': fields})

    print(f"   교정 대상: {len(items)}행")
    if not items:
        print("   교정할 항목이 없습니다.")
        return

    # 3. 교정 실행
    print(f"\n3. 교정 실행 (배치 {CORRECT_BATCH_SIZE}, 동시 {CORRECT_MAX_CONCURRENT})...")
    corrections = await correct_texts(items, CORRECT_BATCH_SIZE, CORRECT_MAX_CONCURRENT)
    print(f"   교정 완료: {len(corrections)}행")

    # 4. 교정 결과 반영
    print("\n4. 결과 반영 중...")
    changed = 0
    for idx, fields in corrections.items():
        if 'answer_intro' in fields:
            df.at[idx, 'answer_intro'] = fields['answer_intro']

        if 'answer_outro' in fields:
            df.at[idx, 'answer_outro'] = fields['answer_outro']

        # subtopics description 재삽입
        desc_fields = {k: v for k, v in fields.items() if k.startswith('description_')}
        if desc_fields:
            subtopics_raw = df.at[idx, 'subtopics'] if 'subtopics' in df.columns else ''
            try:
                subtopics = json.loads(str(subtopics_raw))
                if isinstance(subtopics, list):
                    for key, corrected in desc_fields.items():
                        i = int(key.split('_', 1)[1])
                        if i < len(subtopics) and isinstance(subtopics[i], dict):
                            subtopics[i]['description'] = corrected
                    df.at[idx, 'subtopics'] = json.dumps(subtopics, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                pass

        changed += 1

    print(f"   반영 완료: {changed}행 교정됨")

    # 5. 시트 저장
    print("\n5. 결과 저장 중...")
    write_dataframe_to_sheet(df, sheet_name='qna_group')
    print(f"Successfully wrote {len(df)} rows to 'qna_group' sheet")


if __name__ == '__main__':
    asyncio.run(main())
