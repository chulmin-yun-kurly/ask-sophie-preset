"""
전체 파이프라인 실행기 (QnA + 상품)

사용법:
    python run_pipeline.py                              # 기본: olive_oil, QnA → 상품 → merge
    python run_pipeline.py --product olive_oil qna      # 명시적 상품 지정
    python run_pipeline.py --product all                # 전 상품 순차 실행
    python run_pipeline.py --product all --parallel     # 전 상품 동시 실행
    python run_pipeline.py --product all qna            # 전 상품 QnA만
    python run_pipeline.py merge                        # JSONL 통합만

개별 단계 실행은 각 파이프라인 실행기를 사용하세요:
    python run_qna_pipeline.py [--product ID] [prepare|qna|invert|cluster|answer|suggest|export|dashboard]
    python run_product_pipeline.py [--product ID] [product|export|dashboard]
"""
import argparse
import subprocess
import sys
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def run_pipeline(script: str, label: str, product_id: str) -> bool:
    print(f"\n{'#'*60}")
    print(f"  {label} (상품: {product_id})")
    print(f"{'#'*60}\n")

    start = time.time()
    env = os.environ.copy()
    env['PRODUCT_ID'] = product_id
    env['PYTHONPATH'] = ROOT_DIR + os.pathsep + env.get('PYTHONPATH', '')
    result = subprocess.run(
        [sys.executable, script, '--product', product_id],
        cwd=ROOT_DIR,
        env=env,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n✗ {label} 실패 ({elapsed:.1f}초)")
        return False

    print(f"\n✓ {label} 완료 ({elapsed:.1f}초)")
    return True


def run_merge() -> bool:
    """전 상품 JSONL 통합 (상품 무관)"""
    print(f"\n{'#'*60}")
    print(f"  JSONL 통합 (전 상품)")
    print(f"{'#'*60}\n")

    start = time.time()
    env = os.environ.copy()
    env['PYTHONPATH'] = ROOT_DIR + os.pathsep + env.get('PYTHONPATH', '')
    result = subprocess.run(
        [sys.executable, 'steps/merge_jsonl.py'],
        cwd=ROOT_DIR,
        env=env,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n✗ JSONL 통합 실패 ({elapsed:.1f}초)")
        return False

    print(f"\n✓ JSONL 통합 완료 ({elapsed:.1f}초)")
    return True


def _run_product_pipelines(product_id: str, to_run: list) -> bool:
    """한 상품에 대해 파이프라인 목록을 순차 실행합니다. (subprocess용)"""
    for script, label in to_run:
        if not run_pipeline(script, label, product_id):
            return False
    return True


def run_all_sequential(product_ids: list, to_run: list) -> bool:
    """전 상품을 순차적으로 실행합니다."""
    for pid in product_ids:
        print(f"\n{'='*60}")
        print(f"  ▶ 상품: {pid}")
        print(f"{'='*60}")
        if not _run_product_pipelines(pid, to_run):
            print(f"\n✗ {pid} 파이프라인 실패. 중단.")
            return False
    return True


def run_all_parallel(product_ids: list, to_run: list) -> bool:
    """전 상품을 동시에 실행합니다. (상품별 병렬, 상품 내 단계는 순차)"""
    print(f"\n전 상품 동시 실행: {', '.join(product_ids)}")

    with ProcessPoolExecutor(max_workers=len(product_ids)) as executor:
        futures = {
            executor.submit(_run_product_pipelines, pid, to_run): pid
            for pid in product_ids
        }
        failed = []
        for future in as_completed(futures):
            pid = futures[future]
            try:
                if not future.result():
                    failed.append(pid)
            except Exception as e:
                print(f"\n✗ {pid} 예외: {e}")
                failed.append(pid)

    if failed:
        print(f"\n✗ 실패한 상품: {', '.join(failed)}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='전체 파이프라인 실행기')
    parser.add_argument('--product', default='olive_oil',
                        help='상품 ID 또는 "all" (기본: olive_oil)')
    parser.add_argument('--parallel', action='store_true',
                        help='전 상품 동시 실행 (--product all 과 함께 사용)')
    parser.add_argument('targets', nargs='*', help='실행할 파이프라인 (qna, product, merge)')
    args = parser.parse_args()

    pipelines = {
        'qna': ('run_qna_pipeline.py', 'QnA 파이프라인'),
        'product': ('run_product_pipeline.py', '상품 파이프라인'),
    }

    valid_targets = set(pipelines.keys()) | {'merge'}

    if not args.targets:
        to_run = [pipelines['qna'], pipelines['product']]
    else:
        to_run = []
        for t in args.targets:
            if t in pipelines:
                to_run.append(pipelines[t])
            elif t == 'merge':
                pass  # merge는 아래에서 별도 처리
            else:
                print(f"알 수 없는 대상: {t}")
                print(f"사용 가능: {', '.join(sorted(valid_targets))}")
                sys.exit(1)

    total_start = time.time()

    # 파이프라인 실행
    if to_run:
        if args.product == 'all':
            from product_config import load_all_product_configs
            product_ids = [c.product_id for c in load_all_product_configs()]
            print(f"전체 상품 대상: {', '.join(product_ids)}")

            if args.parallel:
                success = run_all_parallel(product_ids, to_run)
            else:
                success = run_all_sequential(product_ids, to_run)

            if not success:
                print("\n파이프라인 중단.")
                sys.exit(1)
        else:
            for script, label in to_run:
                if not run_pipeline(script, label, args.product):
                    print("\n파이프라인 중단.")
                    sys.exit(1)

    # JSONL 통합 (전체 실행 또는 명시적 merge 지정 시) — 전 상품 통합
    if not args.targets or 'merge' in args.targets:
        if not run_merge():
            print("\n파이프라인 중단.")
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'#'*60}")
    print(f"  전체 파이프라인 완료 (총 {total_elapsed:.1f}초)")
    print(f"{'#'*60}")


if __name__ == '__main__':
    main()
