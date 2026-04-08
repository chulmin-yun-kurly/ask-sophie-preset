"""
output/{product_id}/ 의 JSON 파일들을 합쳐서 dashboard/dashboard.json 을 생성합니다.

읽는 파일:
  - output/{product_id}/qna_result.json
  - output/{product_id}/content_map.json
  - output/{product_id}/product_data.json (없으면 빈 dict)
"""
import json
import os
from product_config import get_output_dir


def main():
    output_dir = get_output_dir()
    print(f"1. {output_dir} 파일 읽는 중...")

    with open(os.path.join(output_dir, 'qna_result.json'), 'r', encoding='utf-8') as f:
        qna = json.load(f)
    print(f"   qna_result.json (카테고리 {qna['total_categories']}개, 그룹 {qna['total_groups']}개)")

    with open(os.path.join(output_dir, 'content_map.json'), 'r', encoding='utf-8') as f:
        content_map = json.load(f)
    print(f"   content_map.json (상품 {len(content_map)}개)")

    product_data = {}
    product_path = os.path.join(output_dir, 'product_data.json')
    if os.path.exists(product_path):
        with open(product_path, 'r', encoding='utf-8') as f:
            product_data = json.load(f)
        print(f"   product_data.json (상품 {len(product_data)}개)")
    else:
        print("   product_data.json 없음, 스킵")

    # 2. 통합
    print("\n2. dashboard.json 생성 중...")
    dashboard = {
        **qna,
        'content_map': content_map,
        'product_data': product_data,
    }

    os.makedirs('dashboard', exist_ok=True)
    dashboard_file = 'dashboard/dashboard.json'
    with open(dashboard_file, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료")
    print(f"   {dashboard_file}")


if __name__ == '__main__':
    main()
