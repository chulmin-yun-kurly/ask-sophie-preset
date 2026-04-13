"""
compare_qna 시트를 BE 스키마 JSONL로 저장합니다.

출력:
  output/<product>/questions/question_compare.jsonl (ai_agent_question)
  output/<product>/answers/answer_compare.jsonl   (ai_agent_answer, answerType=COMPARE)

answer 구조는 resource/admin_schema.md 의 3.2 COMPARE 예시를 따르며,
content 배열 끝에 suggestions 블록을 덧붙입니다.
"""
import json
import os
from sheet_reader import read_google_sheet
from product_config import get_current_product, get_output_dir


def _parse_json_list(raw) -> list:
    if raw is None or raw == '':
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def main():
    print("1. compare_qna 시트 읽는 중...")
    df = read_google_sheet(sheet_name='compare_qna')
    print(f"   Read Shape: {df.shape}")
    if df.empty:
        print("✗ compare_qna 시트가 비어 있습니다.")
        return

    output_dir = get_output_dir()
    os.makedirs(os.path.join(output_dir, 'questions'), exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'answers'), exist_ok=True)

    keyword = get_current_product().product_name if get_current_product() else ''

    questions_file = os.path.join(output_dir, 'questions', 'question_compare.jsonl')
    answers_file = os.path.join(output_dir, 'answers', 'answer_compare.jsonl')

    q_count = 0
    a_count = 0

    with open(questions_file, 'w', encoding='utf-8') as fq, \
         open(answers_file, 'w', encoding='utf-8') as fa:
        for _, row in df.iterrows():
            qid = str(row.get('id', '')).strip()
            question_text = str(row.get('question', '')).strip()
            if not qid or not question_text:
                continue

            # question JSONL
            q_line = {
                'questionId': qid,
                'keyword': keyword,
                'isEntry': False,
                'isActive': False,
                'content': {
                    'answerType': 'COMPARE',
                    'category': '',
                    'representative': question_text,
                    'relatedQuestions': [],
                },
            }
            fq.write(json.dumps(q_line, ensure_ascii=False) + '\n')
            q_count += 1

            # answer JSONL: 저장된 content 블록 + suggestions 블록 덧붙임
            content = _parse_json_list(row.get('content', '[]'))
            suggests = _parse_json_list(row.get('suggest', '[]'))

            # 기존 content 내에 suggestions가 있다면 제거 후 마지막에 재부착
            content = [c for c in content if isinstance(c, dict) and c.get('type') != 'suggestions']
            content.append({'type': 'suggestions', 'data': suggests})

            a_line = {
                'answerId': f'a_{qid}',
                'questionId': qid,
                'isActive': False,
                'answers': [{'content': content}],
            }
            fa.write(json.dumps(a_line, ensure_ascii=False) + '\n')
            a_count += 1

    print(f"\n저장 완료")
    print(f"   {questions_file} ({q_count}줄)")
    print(f"   {answers_file} ({a_count}줄)")


if __name__ == '__main__':
    main()
