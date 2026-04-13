"""
compare_question 시트를 읽어 id를 부여하고, 각 질문의 의미가 같은
변형(related_questions) N개를 LLM으로 생성하여 compare_prepared 시트로 저장합니다.

생성 개수는 config.COMPARE_RELATED_QUESTION_COUNT로 조정합니다.
related_questions 컬럼은 JSON 배열 문자열로 저장됩니다.
"""
import asyncio
import json
import sys
import pandas as pd
from config import (
    MODEL_LIGHT,
    COMPARE_MAX_CONCURRENT,
    COMPARE_RELATED_QUESTION_COUNT,
    TEMP_COMPARE_RELATED,
)
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet


async def generate_related_questions(questions: list[str], count: int) -> list[list[str]]:
    """원본 질문 목록에 대해 각 count개씩 변형 질문을 생성합니다.

    실패하거나 빈 응답인 경우 빈 리스트를 반환합니다.
    응답이 부족하면 받은 만큼만, 초과하면 앞에서부터 count개 사용합니다.
    원본과 동일한 변형, 중복은 제거합니다.
    """
    if count <= 0:
        return [[] for _ in questions]

    system_prompt = build_system_prompt(
        load_prompt('compare/related_question_system.txt').format(count=count)
    )
    user_template = load_prompt('compare/related_question_user.txt')

    semaphore = asyncio.Semaphore(COMPARE_MAX_CONCURRENT)
    results: list[list[str]] = [[] for _ in questions]

    async def _one(idx: int, q: str):
        async with semaphore:
            user_prompt = user_template.format(question=q, count=count)
            try:
                parsed = await chat_json(
                    MODEL_LIGHT, system_prompt, user_prompt,
                    temperature=TEMP_COMPARE_RELATED,
                )
            except Exception as e:
                print(f"   ⚠ [{idx}] related_questions 생성 실패: {e}")
                return

            raw = parsed.get('related_questions', [])
            if not isinstance(raw, list):
                return

            seen: set[str] = {q.strip()}
            picked: list[str] = []
            for item in raw:
                if not isinstance(item, str):
                    continue
                s = item.strip()
                if not s or s in seen:
                    continue
                picked.append(s)
                seen.add(s)
                if len(picked) >= count:
                    break
            results[idx] = picked

    await asyncio.gather(*[_one(i, q) for i, q in enumerate(questions)])
    return results


async def main():
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

    questions = df['question'].astype(str).str.strip().tolist()

    # 3. id 부여 (compare_001 포맷)
    ids = [f"compare_{i+1:03d}" for i in range(len(df))]

    # 4. related_questions LLM 생성
    print(f"\nrelated_questions 생성 중 "
          f"(질문당 {COMPARE_RELATED_QUESTION_COUNT}개, 동시 {COMPARE_MAX_CONCURRENT}개)...")
    related_lists = await generate_related_questions(questions, COMPARE_RELATED_QUESTION_COUNT)
    for i, (q, related) in enumerate(zip(questions, related_lists)):
        print(f"   [{ids[i]}] {q}")
        for r in related:
            print(f"     → related: {r}")
        if not related:
            print(f"     → related: (없음)")

    # 5. compare_prepared 스키마에 맞춰 DataFrame 구성
    df_out = pd.DataFrame({
        'id': ids,
        'question': questions,
        'related_questions': [json.dumps(rs, ensure_ascii=False) for rs in related_lists],
        'candidate_list': ['[]'] * len(df),
        'content_list': ['[]'] * len(df),
        'match_rationale': [''] * len(df),
    })

    # 6. 저장
    write_dataframe_to_sheet(df_out, sheet_name='compare_prepared')
    print(f"Successfully wrote {len(df_out)} rows to 'compare_prepared' sheet")


if __name__ == '__main__':
    asyncio.run(main())
