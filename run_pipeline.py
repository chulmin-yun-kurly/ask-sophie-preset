"""
전체 파이프라인 실행기 (QnA + 상품 + 비교)

Phase 구조:
    Phase 1 (qa)      — 모든 파이프라인의 질문·답변 단계
    Phase 2 (suggest) — 모든 파이프라인의 suggest (전 상품 Q&A 완성 후)
    Phase 3 (export)  — 모든 파이프라인의 JSONL/JSON 출력
    Phase 4 (merge)   — 전 상품 JSONL 통합

사용법:
    python run_pipeline.py                                      # 기본: olive_oil, qna+product+compare → merge
    python run_pipeline.py --product olive_oil qna              # 명시적 상품 + qna만
    python run_pipeline.py --product olive_oil,cheese           # 쉼표 목록으로 일부 상품만
    python run_pipeline.py --product all                        # 전 상품 순차 실행
    python run_pipeline.py --product all --parallel             # 전 상품 동시 실행 (Phase별 barrier 유지)
    python run_pipeline.py --product all qna compare            # qna + compare만 (product 제외)
    python run_pipeline.py merge                                # JSONL 통합만 (전 상품)
    python run_pipeline.py --product olive_oil,cheese merge     # JSONL 통합만 (지정 상품)
    python run_pipeline.py --test 3                             # 테스트 모드 (3개 상품만 처리)
    python run_pipeline.py --test 3 --test-random               # 테스트 모드 (랜덤 샘플링)

개별 단계 실행은 각 파이프라인 실행기를 사용하세요:
    python run_qna_pipeline.py     [--product ID] [prepare|qna|invert|cluster|answer|suggest|export|qa]
    python run_product_pipeline.py [--product ID] [product|question|answer|suggest|export|qa]
    python run_compare_pipeline.py [--product ID] [prepare|match|answer|suggest|export|qa]
"""
import argparse
import subprocess
import sys
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# 파이프라인 정의 (key → (script, label))
PIPELINES = {
    'qna': ('run_qna_pipeline.py', 'QnA'),
    'product': ('run_product_pipeline.py', '상품'),
    'compare': ('run_compare_pipeline.py', '비교'),
}

# Phase 순서
PHASES = ['qa', 'suggest', 'export']


def run_pipeline_phase(pipeline_key: str, product_id: str, phase: str, test_args: list = None) -> bool:
    """한 파이프라인에 대해 phase를 실행한다."""
    script, label = PIPELINES[pipeline_key]
    print(f"\n{'#'*60}")
    print(f"  [{phase}] {label} (상품: {product_id})")
    print(f"{'#'*60}\n")

    start = time.time()
    env = os.environ.copy()
    env['PRODUCT_ID'] = product_id
    env['PYTHONPATH'] = ROOT_DIR + os.pathsep + env.get('PYTHONPATH', '')
    cmd = [sys.executable, script, '--product', product_id, phase]
    if test_args:
        cmd.extend(test_args)
    result = subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        env=env,
    )
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n✗ [{phase}] {label} ({product_id}) 실패 ({elapsed:.1f}초)")
        return False

    print(f"\n✓ [{phase}] {label} ({product_id}) 완료 ({elapsed:.1f}초)")
    return True


def run_merge(product_ids: list | None = None) -> bool:
    """JSONL 통합. product_ids가 주어지면 해당 상품만 통합, 없으면 전 상품."""
    scope = ', '.join(product_ids) if product_ids else '전 상품'
    print(f"\n{'#'*60}")
    print(f"  [merge] JSONL 통합 ({scope})")
    print(f"{'#'*60}\n")

    start = time.time()
    env = os.environ.copy()
    env['PYTHONPATH'] = ROOT_DIR + os.pathsep + env.get('PYTHONPATH', '')
    cmd = [sys.executable, 'steps/merge_jsonl.py']
    if product_ids:
        cmd.extend(['--products', ','.join(product_ids)])
    result = subprocess.run(cmd, cwd=ROOT_DIR, env=env)
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n✗ JSONL 통합 실패 ({elapsed:.1f}초)")
        return False

    print(f"\n✓ JSONL 통합 완료 ({elapsed:.1f}초)")
    return True


def _run_product_phase(product_id: str, pipeline_keys: list, phase: str, test_args: list = None) -> bool:
    """한 상품에 대해 phase를 모든 파이프라인 순서대로 실행한다."""
    for key in pipeline_keys:
        if not run_pipeline_phase(key, product_id, phase, test_args):
            return False
    return True


def run_phase(phase: str, pipeline_keys: list, product_ids: list, parallel: bool, test_args: list = None) -> bool:
    """한 Phase를 전 상품에 대해 실행한다.

    - 상품 내부에서는 pipeline_keys 순서대로 순차 실행
    - parallel=True 이면 상품별 병렬
    - Phase 경계는 항상 직렬 (barrier)
    """
    print(f"\n{'='*60}")
    print(f"  ▶ Phase: {phase}  (상품 {len(product_ids)}개, 파이프라인 {', '.join(pipeline_keys)})")
    print(f"{'='*60}")

    if parallel and len(product_ids) > 1:
        with ProcessPoolExecutor(max_workers=len(product_ids)) as executor:
            futures = {
                executor.submit(_run_product_phase, pid, pipeline_keys, phase, test_args): pid
                for pid in product_ids
            }
            failed = []
            for future in as_completed(futures):
                pid = futures[future]
                try:
                    if not future.result():
                        failed.append(pid)
                except Exception as e:
                    print(f"\n✗ [{phase}] {pid} 예외: {e}")
                    failed.append(pid)
        if failed:
            print(f"\n✗ [{phase}] 실패한 상품: {', '.join(failed)}")
            return False
        return True

    # 순차
    for pid in product_ids:
        if not _run_product_phase(pid, pipeline_keys, phase, test_args):
            print(f"\n✗ [{phase}] {pid} 실패. 중단.")
            return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description='전체 파이프라인 실행기 (Phase 단위)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('--product', default='olive_oil',
                        help='상품 ID, 쉼표 목록("olive_oil,cheese"), 또는 "all" (기본: olive_oil)')
    parser.add_argument('--parallel', action='store_true',
                        help='전 상품 동시 실행 (Phase 내에서만 병렬, --product all 과 함께 사용)')
    parser.add_argument('--test', type=int, default=None, help='테스트 모드 (N개 상품만 처리)')
    parser.add_argument('--test-random', action='store_true', help='랜덤 샘플링 (기본: top N)')
    parser.add_argument('--test-sheet-id', default=None, help='기존 테스트 시트 ID')
    parser.add_argument('--test-comment', default=None, help='테스트 시트 제목 코멘트')
    parser.add_argument('targets', nargs='*',
                        help='실행할 파이프라인: qna, product, compare, merge (미지정 시 qna+product+compare+merge)')
    args = parser.parse_args()

    valid_targets = set(PIPELINES.keys()) | {'merge'}

    # targets 파싱
    if not args.targets:
        pipeline_keys = ['qna', 'product', 'compare']
        run_merge_step = True
    else:
        pipeline_keys = []
        run_merge_step = False
        for t in args.targets:
            if t in PIPELINES:
                if t not in pipeline_keys:
                    pipeline_keys.append(t)
            elif t == 'merge':
                run_merge_step = True
            else:
                print(f"알 수 없는 대상: {t}")
                print(f"사용 가능: {', '.join(sorted(valid_targets))}")
                sys.exit(1)

    # 테스트 모드 CLI 인자 구성
    test_args = []
    if args.test:
        test_args.extend(['--test', str(args.test)])
        if args.test_random:
            test_args.append('--test-random')
        if args.test_comment:
            test_args.extend(['--test-comment', args.test_comment])

        # 테스트 시트 생성 (한 번만)
        if args.test_sheet_id:
            test_args.extend(['--test-sheet-id', args.test_sheet_id])
        else:
            from test_config import create_test_spreadsheet
            sheet_id = create_test_spreadsheet(args.test_comment or '')
            test_args.extend(['--test-sheet-id', sheet_id])
            print(f"\n[TEST] {args.test}개 상품, {'랜덤' if args.test_random else 'top N'}")

    total_start = time.time()

    # 상품 목록 결정 ('all' | 쉼표 목록 | 단일 ID)
    if args.product == 'all':
        from product_config import load_all_product_configs
        product_ids = [c.product_id for c in load_all_product_configs()]
    elif ',' in args.product:
        product_ids = [p.strip() for p in args.product.split(',') if p.strip()]
    else:
        product_ids = [args.product]

    if pipeline_keys:
        print(f"대상 상품: {', '.join(product_ids)}")

        # Phase 순서대로 실행 (전 상품 단위로 묶음)
        for phase in PHASES:
            if not run_phase(phase, pipeline_keys, product_ids, args.parallel, test_args or None):
                print("\n파이프라인 중단.")
                sys.exit(1)

    # Phase 4: JSONL 통합 — 전 상품 요청이 아니면 지정 상품만 통합
    if run_merge_step:
        merge_products = None if args.product == 'all' else product_ids
        if not run_merge(merge_products):
            print("\n파이프라인 중단.")
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'#'*60}")
    print(f"  전체 파이프라인 완료 (총 {total_elapsed:.1f}초)")
    print(f"{'#'*60}")


if __name__ == '__main__':
    main()
