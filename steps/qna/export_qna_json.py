"""
qna_group 시트의 클러스터링 결과를 JSON/JSONL 파일로 구조화하여 저장합니다.
prepared_data에서 content_no → content_nm 매핑도 함께 저장합니다.
"""
import json
import os
from llm_client import strip_html
from sheet_reader import read_google_sheet
from product_config import get_current_product, get_output_dir

RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'resource')


def main():
    # 1. 카테고리 매핑 / headline 매핑 로드
    print("1. 카테고리 매핑 로드 중...")
    with open(os.path.join(RESOURCE_DIR, 'categories.json'), 'r', encoding='utf-8') as f:
        categories_list = json.load(f)
    with open(os.path.join(RESOURCE_DIR, 'answer_headlines.json'), 'r', encoding='utf-8') as f:
        answer_headlines = json.load(f)
    category_id_map = {c['name']: c['id'] for c in categories_list}
    category_type_map = {c['name']: c['type'] for c in categories_list}
    print(f"   카테고리 {len(category_id_map)}개")

    # 2. qna_group 시트 읽기
    print("\n2. qna_group 시트 읽는 중...")
    df = read_google_sheet(sheet_name='qna_group')
    print(f"   Read Shape: {df.shape}")

    # 2-1. prepared_data에서 content_no → content_nm 매핑
    print("\n   prepared_data 읽는 중...")
    df_prepared = read_google_sheet(sheet_name='prepared_data')
    content_map = {}
    for _, row in df_prepared.iterrows():
        cno = int(row['content_no'])
        content_map[cno] = row.get('content_nm', '')
    print(f"   상품 매핑: {len(content_map)}개")

    # 3. 구조화
    print("\n3. 구조화 중...")
    categories = {}

    for _, row in df.iterrows():
        cat = row['category']
        cat_id = category_id_map.get(cat, 0)
        if cat not in categories:
            categories[cat] = {
                'category_id': cat_id,
                'category': cat,
                'groups': []
            }

        sub_group = int(row['sub_group'])

        categories[cat]['groups'].append({
            'id': row.get('id', f"c{cat_id:02d}_s{sub_group:03d}"),
            'sub_group': sub_group,
            'sub_group_label': row['sub_group_label'],
            'representative': row['representative'],
            'answer_intro': row.get('answer_intro', ''),
            'subtopics': json.loads(row['subtopics']) if row.get('subtopics') else [],
            'answer_outro': row.get('answer_outro', ''),
            'search_keywords': json.loads(row['search_keywords']) if row.get('search_keywords') else [],
            'suggest': json.loads(row['suggest']) if row.get('suggest') else [],
            'question_count': int(row['question_count']),
            'content_count': int(row['content_count']),
            'questions': json.loads(row['question_list']),
            'content_list': json.loads(row['content_list'])
        })

    # category_id 순으로 정렬
    result = sorted(categories.values(), key=lambda x: x['category_id'])

    output_dir = get_output_dir()
    os.makedirs(os.path.join(output_dir, 'questions'), exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'answers'), exist_ok=True)

    # 4. JSON 저장
    output = {
        'total_categories': len(result),
        'total_groups': sum(len(c['groups']) for c in result),
        'total_questions': sum(g['question_count'] for c in result for g in c['groups']),
        'categories': result
    }

    json_file = os.path.join(output_dir, 'qna_result.json')
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    DEFAULT_KEYWORD = get_current_product().product_name

    # 6. questions.jsonl 저장 (ai_agent_question)
    questions_file = os.path.join(output_dir, 'questions', 'question_qna.jsonl')
    q_count = 0
    with open(questions_file, 'w', encoding='utf-8') as f:
        for cat in result:
            mapped_category = category_type_map.get(cat['category'], cat['category'])
            for group in cat['groups']:
                line = {
                    'questionId': group['id'],
                    'keyword': DEFAULT_KEYWORD,
                    'isEntry': False,
                    'isActive': False,
                    'content': {
                        'answerType': 'RECOMMEND',
                        'category': mapped_category,
                        'representative': group['representative'],
                        'relatedQuestions': group['questions'],
                    }
                }
                f.write(json.dumps(line, ensure_ascii=False) + '\n')
                q_count += 1

    # 7. answers.jsonl 저장 (ai_agent_answer)
    answers_file = os.path.join(output_dir, 'answers', 'answer_qna.jsonl')
    a_count = 0
    with open(answers_file, 'w', encoding='utf-8') as f:
        for cat in result:
            for group in cat['groups']:
                content = []

                # headline
                headline = answer_headlines.get('RECOMMEND', '')
                if headline:
                    content.append({'type': 'headline', 'data': headline})

                # intro
                content.append({
                    'type': 'intro',
                    'data': strip_html(group.get('answer_intro', '')),
                })

                # subtopics → title + description 반복
                for st_item in group.get('subtopics', []):
                    content.append({
                        'type': 'title',
                        'data': strip_html(st_item.get('subtitle', '')),
                    })
                    content.append({
                        'type': 'description',
                        'data': strip_html(st_item.get('description', '')),
                    })

                # productNos
                content.append({
                    'type': 'productNos',
                    'data': [int(c) for c in group.get('content_list', [])],
                })

                # outro
                content.append({
                    'type': 'outro',
                    'data': strip_html(group.get('answer_outro', '')),
                })

                # suggestions
                content.append({
                    'type': 'suggestions',
                    'data': group.get('suggest', []),
                })

                content = [c for c in content if c.get('data') is not None]

                line = {
                    'answerId': f"a_{group['id']}",
                    'questionId': group['id'],
                    'isActive': False,
                    'answers': [{'content': content}],
                }
                f.write(json.dumps(line, ensure_ascii=False) + '\n')
                a_count += 1

    # 8. content_map.json 저장 (content_no → content_nm)
    content_map_file = os.path.join(output_dir, 'content_map.json')
    with open(content_map_file, 'w', encoding='utf-8') as f:
        json.dump(content_map, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료")
    print(f"   {json_file} (카테고리 {output['total_categories']}개, 그룹 {output['total_groups']}개)")
    print(f"   {questions_file} ({q_count}줄)")
    print(f"   {answers_file} ({a_count}줄)")
    print(f"   {content_map_file} (상품 {len(content_map)}개)")


if __name__ == '__main__':
    main()
