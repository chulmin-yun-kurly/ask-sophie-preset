"""
전체 파이프라인 실행기 (QnA + 상품)

사용법:
    python run_pipeline.py                          # 기본: olive_oil, QnA → 상품
    python run_pipeline.py --product olive_oil qna  # 명시적 상품 지정
    python run_pipeline.py qna                      # QnA 파이프라인만
    python run_pipeline.py product                  # 상품 파이프라인만

개별 단계 실행은 각 파이프라인 실행기를 사용하세요:
    python run_qna_pipeline.py [--product ID] [prepare|qna|invert|cluster|answer|suggest|export|dashboard]
    python run_product_pipeline.py [--product ID] [product|export|dashboard]
"""
import argparse
import subprocess
import sys
import os
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_pipeline(script: str, label: str, product_id: str) -> bool:
    print(f"\n{'#'*60}")
    print(f"  {label} (상품: {product_id})")
    print(f"{'#'*60}\n")

    start = time.time()
    result = subprocess.run(
        [sys.executable, script, '--product', product_id],
        cwd=ROOT_DIR,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n✗ {label} 실패 ({elapsed:.1f}초)")
        return False

    print(f"\n✓ {label} 완료 ({elapsed:.1f}초)")
    return True


def main():
    parser = argparse.ArgumentParser(description='전체 파이프라인 실행기')
    parser.add_argument('--product', default='olive_oil', help='상품 ID (기본: olive_oil)')
    parser.add_argument('targets', nargs='*', help='실행할 파이프라인 (qna, product)')
    args = parser.parse_args()

    pipelines = {
        'qna': ('run_qna_pipeline.py', 'QnA 파이프라인'),
        'product': ('run_product_pipeline.py', '상품 파이프라인'),
    }

    if not args.targets:
        to_run = [pipelines['qna'], pipelines['product']]
    else:
        to_run = []
        for t in args.targets:
            if t in pipelines:
                to_run.append(pipelines[t])
            else:
                print(f"알 수 없는 대상: {t}")
                print(f"사용 가능: {', '.join(pipelines.keys())}")
                sys.exit(1)

    total_start = time.time()

    for script, label in to_run:
        if not run_pipeline(script, label, args.product):
            print("\n파이프라인 중단.")
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'#'*60}")
    print(f"  전체 파이프라인 완료 (총 {total_elapsed:.1f}초)")
    print(f"{'#'*60}")


if __name__ == '__main__':
    main()
