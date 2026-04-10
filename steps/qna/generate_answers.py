"""
qna_group 시트의 대표 질문에 대해 답변과 검색 키워드를 LLM으로 생성합니다.
prepared_data에서 실제 상품 정보를 가져와 프롬프트에 포함합니다.
"""
import json
import os
import asyncio
import pandas as pd
from config import MODEL_MAIN, CLUSTER_MAX_CONCURRENT, CLUSTER_ANSWER_BATCH_SIZE, TEMP_QNA_ANSWER
from llm_client import load_prompt, build_system_prompt, chat_json
from sheet_reader import read_google_sheet, write_dataframe_to_sheet

RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'resource')


def build_content_map(df_prepared: pd.DataFrame) -> dict:
    """prepared_data에서 content_no → 상품 정보 매핑을 생성합니다."""
    content_map = {}
    for _, row in df_prepared.iterrows():
        cno = int(row['content_no'])
        content_map[cno] = {
            'content_nm': row.get('content_nm', ''),
            'key_description': row.get('key_description', ''),
        }
    return content_map


def format_content_info(content_list_json: str, content_map: dict) -> str:
    """content_list JSON에서 실제 상품 정보 텍스트를 생성합니다."""
    try:
        content_nos = json.loads(content_list_json)
    except (json.JSONDecodeError, TypeError):
        return ""

    lines = []
    for cno in content_nos:
        cno = int(cno)
        info = content_map.get(cno)
        if info and info['content_nm']:
            desc = info['key_description']
            if desc:
                lines.append(f"  - {info['content_nm']}: {desc}")
            else:
                lines.append(f"  - {info['content_nm']}")
    return "\n".join(lines)


async def main():
    # 1. 시트 읽기
    print("1. 시트 읽는 중...")
    df = read_google_sheet(sheet_name='qna_group')
    print(f"   qna_group: {df.shape}")

    with open(os.path.join(RESOURCE_DIR, 'categories.json'), 'r', encoding='utf-8') as f:
        categories = json.load(f)
    category_id_map = {c['name']: c['id'] for c in categories}

    df_prepared = read_google_sheet(sheet_name='prepared_data')
    print(f"   prepared_data: {df_prepared.shape}")

    content_map = build_content_map(df_prepared)
    print(f"   상품 매핑: {len(content_map)}개")

    # ID 생성 (c01_s000 형식)
    ids = []
    for _, row in df.iterrows():
        cat_id = category_id_map.get(row['category'], 0)
        sub_group = int(row['sub_group'])
        ids.append(f"c{cat_id:02d}_s{sub_group:03d}")
    df.insert(0, 'id', ids)
    print(f"   ID 생성 완료 ({len(ids)}개)")

    # 2. 대표 질문 + 상품 정보 준비
    print("\n2. 대표 질문 답변 + 검색 키워드 생성 중...")

    answer_system_prompt = build_system_prompt(load_prompt('qna/answer_system.txt'))
    answer_user_template = load_prompt('qna/answer_user.txt')

    all_reps = []
    for idx, row in df.iterrows():
        content_info = format_content_info(
            row.get('content_list', '[]'), content_map
        )
        all_reps.append({
            'df_idx': idx,
            'question': row['representative'],
            'content_info': content_info,
        })

    results_map = {}
    semaphore = asyncio.Semaphore(CLUSTER_MAX_CONCURRENT)

    async def generate_answers_batch(batch):
        """배치 답변 생성. 반환: {batch_내_position: answer_dict}"""
        questions_text = ""
        for i, item in enumerate(batch):
            questions_text += f"\n  {i}. {item['question']}"
            if item['content_info']:
                questions_text += f"\n  [추천 상품 목록]\n{item['content_info']}"

        user_prompt = answer_user_template.format(questions_text=questions_text)
        parsed = await chat_json(MODEL_MAIN, answer_system_prompt, user_prompt, temperature=TEMP_QNA_ANSWER)

        batch_results = {}
        for ans in parsed.get('answers', []):
            if not isinstance(ans, dict):
                continue
            ans_idx = int(ans.get('index', -1))
            if 0 <= ans_idx < len(batch):
                batch_results[ans_idx] = {
                    'question_echo': ans.get('question_echo', ''),
                    'answer_intro': ans.get('answer_intro', ''),
                    'subtopics': ans.get('subtopics', []),
                    'answer_outro': ans.get('answer_outro', ''),
                    'search_keywords': ans.get('search_keywords', []),
                }
        return batch_results

    total_batches = (len(all_reps) + CLUSTER_ANSWER_BATCH_SIZE - 1) // CLUSTER_ANSWER_BATCH_SIZE

    def _verify_echo(batch_items, batch_results):
        """question_echo로 답변-질문 매핑 검증. 불일치 항목의 인덱스 목록 반환."""
        mismatched = []
        for pos, ans in batch_results.items():
            echo = ans.get('question_echo', '')
            expected = batch_items[pos]['question']
            # echo의 앞 10자가 질문 원문에 포함되는지 확인
            if echo and len(echo) >= 5 and echo[:10] not in expected:
                mismatched.append(pos)
        return mismatched

    async def run_batch(batch_idx, batch_items):
        async with semaphore:
            print(f"   배치 {batch_idx + 1}/{total_batches} 처리 중...")
            try:
                batch_results = await generate_answers_batch(batch_items)
                need_individual_retry = False

                if len(batch_results) != len(batch_items):
                    # 개수 누락
                    print(f"   ⚠ 배치 {batch_idx + 1}: {len(batch_results)}/{len(batch_items)}개만 반환, "
                          f"전체 폐기 후 개별 재시도")
                    need_individual_retry = True
                else:
                    # 개수 일치 → question_echo로 내용 밀림 검증
                    mismatched = _verify_echo(batch_items, batch_results)
                    if mismatched:
                        print(f"   ⚠ 배치 {batch_idx + 1}: 답변 밀림 감지 (인덱스 {mismatched}), "
                              f"전체 폐기 후 개별 재시도")
                        need_individual_retry = True

                if need_individual_retry:
                    for i, item in enumerate(batch_items):
                        single_result = await generate_answers_batch([item])
                        if 0 in single_result:
                            ans = single_result[0]
                            ans.pop('question_echo', None)
                            results_map[item['df_idx']] = ans
                        else:
                            print(f"   ✗ 개별 재시도도 실패: {item['question'][:40]}")
                else:
                    for pos, ans in batch_results.items():
                        ans.pop('question_echo', None)
                        results_map[batch_items[pos]['df_idx']] = ans

                print(f"   배치 {batch_idx + 1}/{total_batches} 완료")
            except Exception as e:
                print(f"   배치 {batch_idx + 1}/{total_batches} ERROR: {e}")

    tasks = []
    for i in range(0, len(all_reps), CLUSTER_ANSWER_BATCH_SIZE):
        batch_idx = i // CLUSTER_ANSWER_BATCH_SIZE
        batch = all_reps[i:i + CLUSTER_ANSWER_BATCH_SIZE]
        tasks.append(run_batch(batch_idx, batch))
    await asyncio.gather(*tasks)

    print(f"   생성 완료 ({len(results_map)}개)")

    # 3. DataFrame 업데이트
    print("\n3. 결과 저장 중...")
    df['answer_intro'] = df.index.map(lambda i: results_map.get(i, {}).get('answer_intro', ''))
    df['subtopics'] = df.index.map(
        lambda i: json.dumps(results_map.get(i, {}).get('subtopics', []), ensure_ascii=False)
    )
    df['answer_outro'] = df.index.map(lambda i: results_map.get(i, {}).get('answer_outro', ''))
    df['search_keywords'] = df.index.map(
        lambda i: json.dumps(results_map.get(i, {}).get('search_keywords', []), ensure_ascii=False)
    )

    # 요약 출력
    for _, row in df.iterrows():
        print(f"   [{row['category']}] {row['representative']}")
        intro = row['answer_intro'][:60] if row['answer_intro'] else ''
        print(f"     intro: {intro}...")
        subtopics = json.loads(row['subtopics']) if row['subtopics'] else []
        print(f"     subtopics: {len(subtopics)}개")
        kws = json.loads(row['search_keywords']) if row['search_keywords'] else []
        if kws:
            print(f"     키워드: {', '.join(kws)}")

    write_dataframe_to_sheet(df, sheet_name='qna_group')
    print(f"\nSuccessfully wrote {len(df)} rows to 'qna_group' sheet")


if __name__ == '__main__':
    asyncio.run(main())
