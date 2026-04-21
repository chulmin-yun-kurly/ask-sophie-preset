"""
product_data 및 product_qna 시트의 답변 텍스트를 교정합니다.

product_data 교정 대상: intro, story, outro
product_qna 교정 대상: answer_intro, answer_outro, subtopics[].description
"""
import asyncio
import json
import pandas as pd
from config import CORRECT_BATCH_SIZE, CORRECT_MAX_CONCURRENT
from sheet_reader import read_google_sheet, write_dataframe_to_sheet
from steps.shared.correct_text import correct_texts


def _extract_product_data_items(df: pd.DataFrame) -> list[dict]:
    """product_data에서 교정 대상 필드를 추출합니다."""
    items = []
    for idx, row in df.iterrows():
        fields = {}
        for col in ('intro', 'story', 'outro'):
            val = row.get(col, '')
            if val and str(val).strip():
                fields[col] = str(val)
        if fields:
            items.append({'index': idx, 'fields': fields})
    return items


def _extract_product_qna_items(df: pd.DataFrame) -> list[dict]:
    """product_qna에서 교정 대상 필드를 추출합니다."""
    items = []
    for idx, row in df.iterrows():
        fields = {}

        intro = row.get('answer_intro', '')
        if intro and str(intro).strip():
            fields['answer_intro'] = str(intro)

        outro = row.get('answer_outro', '')
        if outro and str(outro).strip():
            fields['answer_outro'] = str(outro)

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
    return items


def _apply_product_qna_corrections(df: pd.DataFrame, corrections: dict[int, dict]) -> int:
    """product_qna 교정 결과를 DataFrame에 반영합니다. 반환: 변경된 행 수."""
    changed = 0
    for idx, fields in corrections.items():
        if 'answer_intro' in fields:
            df.at[idx, 'answer_intro'] = fields['answer_intro']

        if 'answer_outro' in fields:
            df.at[idx, 'answer_outro'] = fields['answer_outro']

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
    return changed


async def main():
    # ── product_data 교정 ──
    print("1. product_data 시트 읽는 중...")
    df_product = read_google_sheet(sheet_name='product_data')
    print(f"   product_data: {df_product.shape}")

    items_product = _extract_product_data_items(df_product)
    print(f"   교정 대상: {len(items_product)}행")

    if items_product:
        print(f"\n2. product_data 교정 실행...")
        corrections_product = await correct_texts(items_product, CORRECT_BATCH_SIZE, CORRECT_MAX_CONCURRENT)

        changed = 0
        for idx, fields in corrections_product.items():
            for col in ('intro', 'story', 'outro'):
                if col in fields:
                    df_product.at[idx, col] = fields[col]
            changed += 1
        print(f"   반영 완료: {changed}행")

        write_dataframe_to_sheet(df_product, sheet_name='product_data')
        print(f"   product_data 저장 완료 ({len(df_product)}행)")
    else:
        print("   product_data 교정할 항목 없음")

    # ── product_qna 교정 ──
    print(f"\n3. product_qna 시트 읽는 중...")
    df_qna = read_google_sheet(sheet_name='product_qna')
    print(f"   product_qna: {df_qna.shape}")

    items_qna = _extract_product_qna_items(df_qna)
    print(f"   교정 대상: {len(items_qna)}행")

    if items_qna:
        print(f"\n4. product_qna 교정 실행...")
        corrections_qna = await correct_texts(items_qna, CORRECT_BATCH_SIZE, CORRECT_MAX_CONCURRENT)

        changed = _apply_product_qna_corrections(df_qna, corrections_qna)
        print(f"   반영 완료: {changed}행")

        write_dataframe_to_sheet(df_qna, sheet_name='product_qna')
        print(f"   product_qna 저장 완료 ({len(df_qna)}행)")
    else:
        print("   product_qna 교정할 항목 없음")

    print("\nproduct 교정 완료")


if __name__ == '__main__':
    asyncio.run(main())
