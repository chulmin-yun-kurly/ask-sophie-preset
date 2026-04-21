"""
compare_qna 시트의 답변 텍스트를 교정합니다.
교정 대상: content[] 배열에서 type이 intro, description, outro인 블록의 data
"""
import asyncio
import json
import pandas as pd
from config import CORRECT_BATCH_SIZE, CORRECT_MAX_CONCURRENT
from sheet_reader import read_google_sheet, write_dataframe_to_sheet
from steps.shared.correct_text import correct_texts

# 교정 대상 블록 타입
TARGET_TYPES = {'intro', 'description', 'outro'}


async def main():
    # 1. 시트 읽기
    print("1. compare_qna 시트 읽는 중...")
    df = read_google_sheet(sheet_name='compare_qna')
    print(f"   compare_qna: {df.shape}")

    # 2. 교정 대상 필드 추출
    print("\n2. 교정 대상 추출 중...")
    items = []
    # 행별 블록 매핑 정보 보존 (복원 시 필요)
    row_block_maps: dict[int, list[tuple[str, int]]] = {}  # idx -> [(field_key, block_index)]

    for idx, row in df.iterrows():
        content_raw = row.get('content', '')
        if not content_raw or not str(content_raw).strip():
            continue

        try:
            blocks = json.loads(str(content_raw))
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(blocks, list):
            continue

        fields = {}
        block_map = []  # (field_key, block_index)
        type_counters: dict[str, int] = {}

        for block_idx, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            btype = block.get('type', '')
            if btype not in TARGET_TYPES:
                continue
            data = block.get('data', '')
            if not isinstance(data, str) or not data.strip():
                continue

            # flat 키 생성: intro_0, description_0, description_1, outro_0
            count = type_counters.get(btype, 0)
            type_counters[btype] = count + 1
            field_key = f"{btype}_{count}"

            fields[field_key] = data
            block_map.append((field_key, block_idx))

        if fields:
            items.append({'index': idx, 'fields': fields})
            row_block_maps[idx] = block_map

    print(f"   교정 대상: {len(items)}행")
    if not items:
        print("   교정할 항목이 없습니다.")
        return

    # 3. 교정 실행
    print(f"\n3. 교정 실행 (배치 {CORRECT_BATCH_SIZE}, 동시 {CORRECT_MAX_CONCURRENT})...")
    corrections = await correct_texts(items, CORRECT_BATCH_SIZE, CORRECT_MAX_CONCURRENT)
    print(f"   교정 완료: {len(corrections)}행")

    # 4. 교정 결과를 content JSON에 재삽입
    print("\n4. 결과 반영 중...")
    changed = 0
    for idx, fields in corrections.items():
        content_raw = df.at[idx, 'content']
        try:
            blocks = json.loads(str(content_raw))
        except (json.JSONDecodeError, TypeError):
            continue

        block_map = row_block_maps.get(idx, [])
        for field_key, block_idx in block_map:
            if field_key in fields:
                blocks[block_idx]['data'] = fields[field_key]

        df.at[idx, 'content'] = json.dumps(blocks, ensure_ascii=False)
        changed += 1

    print(f"   반영 완료: {changed}행 교정됨")

    # 5. 시트 저장
    print("\n5. 결과 저장 중...")
    write_dataframe_to_sheet(df, sheet_name='compare_qna')
    print(f"Successfully wrote {len(df)} rows to 'compare_qna' sheet")


if __name__ == '__main__':
    asyncio.run(main())
