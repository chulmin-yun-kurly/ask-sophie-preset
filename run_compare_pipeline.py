"""
비교(compare) 파이프라인 실행기

사용법:
    python run_compare_pipeline.py                             # 전체 실행
    python run_compare_pipeline.py --product olive_oil         # 상품 지정
    python run_compare_pipeline.py prepare                     # compare_question 로드 및 id 부여
    python run_compare_pipeline.py --product olive_oil match   # 매칭만
    python run_compare_pipeline.py --product olive_oil answer  # 답변 생성만
    python run_compare_pipeline.py --product olive_oil qa      # 그룹 지정 (qa: prepare → match → answer)

단일 단계: prepare, match, answer, correct, suggest, export
그룹    : qa (prepare → match → answer → correct), suggest, export
"""
import argparse
import subprocess
import sys
import os
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ('steps/compare/prepare_compare.py', 'compare_question 로드 및 id 부여'),
    ('steps/compare/match_products.py', '임베딩 top-K + LLM 필터로 상품 매칭'),
    ('steps/compare/generate_compare_answer.py', '비교축 중심 답변 생성'),
    ('steps/compare/correct_answers.py', '답변 텍스트 문법/표현 교정'),
    ('steps/compare/build_suggestions.py', '비교 질문 연관 추천(suggest) 생성'),
    ('steps/compare/export_compare_json.py', '비교 QnA JSONL 내보내기'),
]

STEP_MAP = {
    'prepare': [STEPS[0]],
    'match': [STEPS[1]],
    'answer': [STEPS[2]],
    'correct': [STEPS[3]],
    'suggest': [STEPS[4]],
    'export': [STEPS[5]],
}

# Phase 그룹: run_pipeline.py의 Phase 오케스트레이션에서 사용
GROUP_MAP = {
    'qa': ['prepare', 'match', 'answer', 'correct'],
    'suggest': ['suggest'],
    'export': ['export'],
}


def _test_env_vars(args) -> dict:
    """테스트 모드 환경변수를 구성합니다."""
    env = {}
    if getattr(args, 'test', None):
        env['TEST_ENABLED'] = '1'
        env['TEST_SAMPLE_SIZE'] = str(args.test)
        if getattr(args, 'test_random', False):
            env['TEST_RANDOM'] = '1'
        if getattr(args, 'test_sheet_id', None):
            env['TEST_SHEET_ID'] = args.test_sheet_id
        if getattr(args, 'test_comment', None):
            env['TEST_COMMENT'] = args.test_comment
    return env


def run_step(script: str, description: str, product_id: str, extra_env: dict = None) -> bool:
    print(f"\n{'='*60}")
    print(f"  {description}")
    print(f"  → {script}")
    print(f"{'='*60}\n")

    start = time.time()
    env = os.environ.copy()
    env['PYTHONPATH'] = ROOT_DIR + os.pathsep + env.get('PYTHONPATH', '')
    env['PRODUCT_ID'] = product_id
    if extra_env:
        env.update(extra_env)
    result = subprocess.run([sys.executable, script], env=env)
    elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\n✗ {script} 실패 (exit code: {result.returncode}, {elapsed:.1f}초)")
        return False

    print(f"\n✓ {script} 완료 ({elapsed:.1f}초)")
    return True


def main():
    parser = argparse.ArgumentParser(description='비교(compare) 파이프라인 실행기')
    parser.add_argument('--product', default='olive_oil', help='상품 ID (기본: olive_oil)')
    parser.add_argument('--test', type=int, default=None, help='테스트 모드 (N개 질문만 처리)')
    parser.add_argument('--test-random', action='store_true', help='랜덤 샘플링 (기본: top N)')
    parser.add_argument('--test-sheet-id', default=None, help='기존 테스트 시트 ID')
    parser.add_argument('--test-comment', default=None, help='테스트 시트 제목 코멘트')
    parser.add_argument('targets', nargs='*', help='실행할 단계')
    args = parser.parse_args()

    from product_config import set_current_product
    set_current_product(args.product)

    if not args.targets:
        steps = STEPS
    else:
        steps = []
        for t in args.targets:
            if t in GROUP_MAP:
                for step_name in GROUP_MAP[t]:
                    steps.extend(STEP_MAP[step_name])
            elif t in STEP_MAP:
                steps.extend(STEP_MAP[t])
            else:
                print(f"알 수 없는 단계/그룹: {t}")
                print(f"사용 가능 단계: {', '.join(STEP_MAP.keys())}")
                print(f"사용 가능 그룹: {', '.join(GROUP_MAP.keys())}")
                sys.exit(1)

    # 테스트 모드 설정
    extra_env = _test_env_vars(args)
    if args.test:
        if not args.test_sheet_id:
            from test_config import create_test_spreadsheet
            sheet_id = create_test_spreadsheet(args.test_comment or '')
            extra_env['TEST_SHEET_ID'] = sheet_id
        print(f"\n[TEST] {args.test}개 질문, {'랜덤' if args.test_random else 'top N'}")
        # 테스트 모드: export 단계 제외 (시트 출력까지만)
        export_scripts = {s for s, _ in STEP_MAP.get('export', [])}
        steps = [(s, d) for s, d in steps if s not in export_scripts]

    total_start = time.time()
    print(f"비교 파이프라인 시작: {len(steps)}개 단계 (상품: {args.product})")

    for script, description in steps:
        if not run_step(script, description, args.product, extra_env):
            print("\n파이프라인 중단.")
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  비교 파이프라인 완료 (총 {total_elapsed:.1f}초)")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
