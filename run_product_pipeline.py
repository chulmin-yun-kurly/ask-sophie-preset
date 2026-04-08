"""
상품 파이프라인 실행기

사용법:
    python run_product_pipeline.py                          # 전체 실행
    python run_product_pipeline.py --product olive_oil      # 상품 지정
    python run_product_pipeline.py product                  # 상품 소개 생성만
    python run_product_pipeline.py --product honey export   # 상품 지정 + 단계 선택
"""
import argparse
import subprocess
import sys
import os
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ('steps/product/generate_products.py', '상품 소개/홍보 텍스트 생성'),
    ('steps/product/generate_product_question.py', '상품별 질문 생성'),
    ('steps/product/generate_product_answer.py', '상품별 답변 생성'),
    ('steps/product/build_product_suggestions.py', '관련 질문(suggest) 매핑'),
    ('steps/product/export_product_json.py', '상품 JSON 파일 내보내기'),
]

STEP_MAP = {
    'product': [STEPS[0]],
    'question': [STEPS[1]],
    'answer': [STEPS[2]],
    'suggest': [STEPS[3]],
    'export': [STEPS[4]],
}


def run_step(script: str, description: str, product_id: str) -> bool:
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"  → {script}")
    print(f"{'='*60}\n")

    start = time.time()
    env = os.environ.copy()
    env['PYTHONPATH'] = ROOT_DIR + os.pathsep + env.get('PYTHONPATH', '')
    env['PRODUCT_ID'] = product_id
    result = subprocess.run([sys.executable, script], env=env)
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n✗ {script} 실패 (exit code: {result.returncode}, {elapsed:.1f}초)")
        return False

    print(f"\n✓ {script} 완료 ({elapsed:.1f}초)")
    return True


def main():
    parser = argparse.ArgumentParser(description='상품 파이프라인 실행기')
    parser.add_argument('--product', default='olive_oil', help='상품 ID (기본: olive_oil)')
    parser.add_argument('targets', nargs='*', help='실행할 단계')
    args = parser.parse_args()

    from product_config import set_current_product
    set_current_product(args.product)

    if not args.targets:
        steps = STEPS
    else:
        steps = []
        for t in args.targets:
            if t in STEP_MAP:
                steps.extend(STEP_MAP[t])
            else:
                print(f"알 수 없는 단계: {t}")
                print(f"사용 가능: {', '.join(STEP_MAP.keys())}")
                sys.exit(1)

    total_start = time.time()
    print(f"상품 파이프라인 시작: {len(steps)}개 단계 (상품: {args.product})")

    for script, description in steps:
        if not run_step(script, description, args.product):
            print("\n파이프라인 중단.")
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  상품 파이프라인 완료 (총 {total_elapsed:.1f}초)")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
