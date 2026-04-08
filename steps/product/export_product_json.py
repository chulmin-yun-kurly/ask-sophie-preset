"""
product_data 및 product_qna 시트를 JSON 파일 및 BE 스키마 JSONL로 저장합니다.
"""
import json
import os
from llm_client import strip_html
from sheet_reader import read_google_sheet
from product_config import get_output_dir

RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'resource')

with open(os.path.join(RESOURCE_DIR, 'answer_headlines.json'), 'r', encoding='utf-8') as _f:
    ANSWER_HEADLINES = json.load(_f)


def _to_bullet_or_desc(text: str) -> dict:
    """bullet list 형식이면 bulletList, 아니면 description으로 반환합니다."""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if lines and all(l.startswith('- ') for l in lines):
        return {'type': 'bulletList', 'data': [l[2:] for l in lines]}
    return {'type': 'description', 'data': text}


def export_product(product_map: dict):
    """product_data를 JSON + JSONL로 저장합니다."""
    output_dir = get_output_dir()
    # product_data.json
    product_map_file = os.path.join(output_dir, 'product_data.json')
    with open(product_map_file, 'w', encoding='utf-8') as f:
        json.dump(product_map, f, ensure_ascii=False, indent=2)

    # product_questions.jsonl
    questions_file = os.path.join(output_dir, 'questions', 'question_product.jsonl')
    q_count = 0
    with open(questions_file, 'w', encoding='utf-8') as f:
        for cno, product in product_map.items():
            line = {
                'questionId': f'pq_{cno}',
                'productNo': cno,
                'isEntry': False,
                'isActive': False,
                'content': {
                    'answerType': 'SUMMARY',
                    'category': '',
                    'representative': '이 상품에 대해 알려줘',
                    'relatedQuestions': [],
                },
            }
            f.write(json.dumps(line, ensure_ascii=False) + '\n')
            q_count += 1

    # product_answers.jsonl
    answers_file = os.path.join(output_dir, 'answers', 'answer_product.jsonl')
    a_count = 0
    with open(answers_file, 'w', encoding='utf-8') as f:
        for cno, product in product_map.items():
            content = [
                {'type': 'headline', 'data': ANSWER_HEADLINES.get('SUMMARY', '')},
                {'type': 'intro', 'data': strip_html(product.get('intro', '')) or None},
                {'type': 'title', 'data': strip_html(product.get('headline', ''))},
                {'type': 'productNos', 'data': [cno]},
            ]

            if product.get('features', ''):
                content.append({'type': 'title', 'data': '# 특장점'})
                content.append(_to_bullet_or_desc(strip_html(product['features'])))

            if product.get('story', ''):
                content.append({'type': 'title', 'data': '# 스토리'})
                content.append(_to_bullet_or_desc(strip_html(product['story'])))

            if product.get('recommendation', ''):
                content.append({'type': 'title', 'data': '# 이런 분께 추천해요'})
                content.append(_to_bullet_or_desc(strip_html(product['recommendation'])))

            content.append({'type': 'outro', 'data': strip_html(product.get('outro', '')) or None})
            content.append({'type': 'suggestions', 'data': product.get('suggest', [])})

            content = [c for c in content if c.get('data') is not None]

            line = {
                'answerId': f'pa_{cno}',
                'questionId': f'pq_{cno}',
                'isActive': False,
                'answers': [{'content': content}],
            }
            f.write(json.dumps(line, ensure_ascii=False) + '\n')
            a_count += 1

    print(f"   {product_map_file} (상품 {len(product_map)}개)")
    print(f"   {questions_file} ({q_count}줄)")
    print(f"   {answers_file} ({a_count}줄)")


def export_product_qna(df_qna, product_map: dict):
    """product_qna 시트를 INFO 타입 JSONL로 저장합니다."""
    output_dir = get_output_dir()
    pqq_file = os.path.join(output_dir, 'questions', 'question_product_qna.jsonl')
    pqa_file = os.path.join(output_dir, 'answers', 'answer_product_qna.jsonl')
    q_count = 0
    a_count = 0

    with open(pqq_file, 'w', encoding='utf-8') as fq, \
         open(pqa_file, 'w', encoding='utf-8') as fa:
        for _, row in df_qna.iterrows():
            cno = int(row['content_no'])
            q_num = int(row['q_number'])
            q_id = f'pqq_{cno}_{q_num}'
            a_id = f'pqa_{cno}_{q_num}'

            # suggest 가져오기 (product_qna 시트 또는 product_map에서)
            suggest_raw = row.get('suggest', '[]')
            if isinstance(suggest_raw, str):
                try:
                    suggests = json.loads(suggest_raw)
                except (json.JSONDecodeError, TypeError):
                    suggests = []
            else:
                suggests = suggest_raw if suggest_raw else []

            # question JSONL
            q_line = {
                'questionId': q_id,
                'productNo': cno,
                'isEntry': False,
                'isActive': False,
                'content': {
                    'answerType': 'INFO',
                    'category': row.get('category', ''),
                    'representative': row.get('question', ''),
                    'relatedQuestions': [],
                },
            }
            fq.write(json.dumps(q_line, ensure_ascii=False) + '\n')
            q_count += 1

            # answer JSONL (INFO 구조: intro → title/description × N → outro → suggestions)
            subtopics_raw = row.get('subtopics', '[]')
            if isinstance(subtopics_raw, str):
                try:
                    subtopics = json.loads(subtopics_raw)
                except (json.JSONDecodeError, TypeError):
                    subtopics = []
            else:
                subtopics = subtopics_raw if subtopics_raw else []

            content = [
                {'type': 'headline', 'data': ANSWER_HEADLINES.get('INFO', '')},
                {'type': 'intro', 'data': strip_html(row.get('answer_intro', ''))},
            ]
            for st in subtopics:
                content.append({'type': 'title', 'data': f"# {strip_html(st.get('subtitle', ''))}"})
                content.append({'type': 'description', 'data': strip_html(st.get('description', ''))})
            content.append({'type': 'outro', 'data': strip_html(row.get('answer_outro', ''))})
            content.append({'type': 'suggestions', 'data': suggests})

            content = [c for c in content if c.get('data') is not None]

            a_line = {
                'answerId': a_id,
                'questionId': q_id,
                'isActive': False,
                'answers': [{'content': content}],
            }
            fa.write(json.dumps(a_line, ensure_ascii=False) + '\n')
            a_count += 1

    print(f"   {pqq_file} ({q_count}줄)")
    print(f"   {pqa_file} ({a_count}줄)")


def main():
    print("1. product_data 시트 읽는 중...")
    df_product = read_google_sheet(sheet_name='product_data')
    print(f"   Read Shape: {df_product.shape}")

    # 구조화
    print("\n2. 구조화 중...")
    product_map = {}
    for _, row in df_product.iterrows():
        cno = int(row['content_no'])
        product_map[cno] = {
            'content_nm': row.get('content_nm', ''),
            'headline': row.get('headline', ''),
            'features': row.get('features', ''),
            'story': row.get('story', ''),
            'recommendation': row.get('recommendation', ''),
            'suggest': json.loads(row['suggest']) if row.get('suggest') else [],
        }

    output_dir = get_output_dir()
    os.makedirs(os.path.join(output_dir, 'questions'), exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'answers'), exist_ok=True)

    # product JSONL 저장
    print("\n3. product JSONL 저장 중...")
    export_product(product_map)

    # product_qna JSONL 저장
    print("\n4. product_qna JSONL 저장 중...")
    try:
        df_qna = read_google_sheet(sheet_name='product_qna')
        print(f"   product_qna: {len(df_qna)}건")
        export_product_qna(df_qna, product_map)
    except Exception as e:
        print(f"   product_qna 시트 없음 또는 오류, 스킵: {e}")

    print(f"\n저장 완료")


if __name__ == '__main__':
    main()
