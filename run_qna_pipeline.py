"""
QnA 파이프라인 실행기

사용법:
    python run_qna_pipeline.py                          # 전체 실행
    python run_qna_pipeline.py --product olive_oil      # 상품 지정
    python run_qna_pipeline.py prepare                  # 데이터 준비만
    python run_qna_pipeline.py --product honey prepare  # 상품 지정 + 단계 선택
    python run_qna_pipeline.py --product olive_oil qa   # 그룹 지정 (qa: prepare ~ answer)

단일 단계: prepare, qna, invert, cluster, answer, suggest, export
그룹    : qa (prepare → qna → invert → cluster → answer), suggest, export
"""
import argparse
import subprocess
import sys
import os
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ('steps/qna/prepare_data.py', '데이터 준비 (key_description, topic_keyword 생성)'),
    ('steps/qna/make_qna_data.py', '질문 생성 (카테고리별)'),
    ('steps/qna/invert_questions.py', '질문 역전 & 동일 질문 통합'),
    ('steps/qna/cluster_questions.py', '질문 클러스터링 & 대표 질문 선정'),
    ('steps/qna/generate_answers.py', '대표 질문 답변 + 검색 키워드 생성'),
    ('steps/qna/build_suggestions.py', '연관 추천 생성'),
    ('steps/qna/export_qna_json.py', 'QnA JSON 파일 내보내기'),
]

STEP_MAP = {
    'prepare': [STEPS[0]],
    'qna': [STEPS[1]],
    'invert': [STEPS[2]],
    'cluster': [STEPS[3]],
    'answer': [STEPS[4]],
    'suggest': [STEPS[5]],
    'export': [STEPS[6]],
}

# Phase 그룹: run_pipeline.py의 Phase 오케스트레이션에서 사용
GROUP_MAP = {
    'qa': ['prepare', 'qna', 'invert', 'cluster', 'answer'],
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
    parser = argparse.ArgumentParser(description='QnA 파이프라인 실행기')
    parser.add_argument('--product', default='olive_oil', help='상품 ID (기본: olive_oil)')
    parser.add_argument('--test', type=int, default=None, help='테스트 모드 (N개 상품만 처리)')
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
        print(f"\n[TEST] {args.test}개 상품, {'랜덤' if args.test_random else 'top N'}")
        # 테스트 모드: export 단계 제외 (시트 출력까지만)
        export_scripts = {s for s, _ in STEP_MAP.get('export', [])}
        steps = [(s, d) for s, d in steps if s not in export_scripts]

    total_start = time.time()
    print(f"QnA 파이프라인 시작: {len(steps)}개 단계 (상품: {args.product})")

    for script, description in steps:
        if not run_step(script, description, args.product, extra_env):
            print("\n파이프라인 중단.")
            sys.exit(1)

    total_elapsed = time.time() - total_start
    print(f"\n{'='*60}")
    print(f"  QnA 파이프라인 완료 (총 {total_elapsed:.1f}초)")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
