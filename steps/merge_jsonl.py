"""
전체 상품의 JSONL 파일들을 통합하여 output/integrated/ 에 최종 파일을 생성합니다.

각 상품의 id_prefix를 사용하여 ID 충돌을 방지합니다.
예: id_prefix="0" → c01_s000 → 0_c01_s000

사용법:
    python steps/merge_jsonl.py                                # 전 상품 통합
    python steps/merge_jsonl.py --products olive_oil,cheese    # 지정 상품만 통합
"""
import argparse
import json
import os
import glob
from datetime import datetime
from product_config import load_all_product_configs, load_product_config, ProductConfig

INTEGRATED_DIR = os.path.join('output', 'integrated')


def prefix_id(id_value: str, prefix: str) -> str:
    """ID 앞에 prefix를 붙입니다."""
    return f"{prefix}_{id_value}"


def prefix_question(line: str, prefix: str) -> str:
    """question JSONL 라인의 questionId에 prefix를 붙입니다."""
    obj = json.loads(line)
    obj['questionId'] = prefix_id(obj['questionId'], prefix)
    return json.dumps(obj, ensure_ascii=False)


def prefix_answer(line: str, prefix: str) -> str:
    """answer JSONL 라인의 answerId, questionId, suggestions에 prefix를 붙입니다."""
    obj = json.loads(line)
    obj['answerId'] = prefix_id(obj['answerId'], prefix)
    obj['questionId'] = prefix_id(obj['questionId'], prefix)

    # answers[].content[] 내의 suggestions data도 prefix
    for answer in obj.get('answers', []):
        for item in answer.get('content', []):
            if item.get('type') == 'suggestions':
                data = item.get('data')
                if isinstance(data, dict):
                    # {keyword: [...], product: [...]} 형식
                    for key in data:
                        if isinstance(data[key], list):
                            data[key] = [prefix_id(s, prefix) for s in data[key]]
                elif isinstance(data, list):
                    # 하위 호환: flat list 형식
                    item['data'] = [prefix_id(s, prefix) for s in data]

    return json.dumps(obj, ensure_ascii=False)


def merge_product_files(config: ProductConfig, file_type: str, prefix_fn, out_file):
    """한 상품의 JSONL 파일들을 읽어 prefix를 적용하고 출력 파일에 씁니다."""
    input_dir = os.path.join('output', config.product_id, file_type)
    if not os.path.isdir(input_dir):
        print(f"   [{config.product_name}] {file_type}/ 디렉토리 없음 — 건너뜀")
        return 0

    files = sorted(glob.glob(os.path.join(input_dir, '*.jsonl')))
    total = 0
    for f in files:
        count = 0
        with open(f, 'r', encoding='utf-8') as inp:
            for line in inp:
                line = line.strip()
                if line:
                    prefixed = prefix_fn(line, config.id_prefix)
                    out_file.write(prefixed + '\n')
                    count += 1
        print(f"   [{config.product_name}] {os.path.basename(f)}: {count}줄")
        total += count
    return total


def main():
    parser = argparse.ArgumentParser(description='상품별 JSONL 통합')
    parser.add_argument('--products', default='',
                        help='쉼표로 구분한 상품 ID 목록 (미지정 시 전체)')
    args = parser.parse_args()

    if args.products:
        product_ids = [p.strip() for p in args.products.split(',') if p.strip()]
        configs = [load_product_config(pid) for pid in product_ids]
    else:
        configs = load_all_product_configs()
    if not configs:
        print("상품 설정이 없습니다.")
        return

    os.makedirs(INTEGRATED_DIR, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    print(f"통합 대상 상품: {', '.join(c.product_name for c in configs)}\n")

    # questions 통합
    print("1. questions 통합 중...")
    q_path = os.path.join(INTEGRATED_DIR, f'question_{timestamp}.jsonl')
    q_total = 0
    with open(q_path, 'w', encoding='utf-8') as out:
        for config in configs:
            q_total += merge_product_files(config, 'questions', prefix_question, out)

    # answers 통합
    print(f"\n2. answers 통합 중...")
    a_path = os.path.join(INTEGRATED_DIR, f'answer_{timestamp}.jsonl')
    a_total = 0
    with open(a_path, 'w', encoding='utf-8') as out:
        for config in configs:
            a_total += merge_product_files(config, 'answers', prefix_answer, out)

    print(f"\n통합 완료")
    print(f"   {q_path} ({q_total}줄)")
    print(f"   {a_path} ({a_total}줄)")


if __name__ == '__main__':
    main()
