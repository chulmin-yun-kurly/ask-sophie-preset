"""
output/integrated/ 의 최신 JSONL 파일을 AWS S3에 업로드합니다.

사용법:
    python steps/upload_s3.py                    # 최신 파일 업로드
    python steps/upload_s3.py --dry-run          # 업로드 없이 대상 파일 확인
    python steps/upload_s3.py --profile kurly     # 특정 AWS 프로필 사용
"""
import argparse
import glob
import os
import re

import boto3

INTEGRATED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'output', 'integrated',
)

S3_BUCKET = 'kurly-search-data-dev'
S3_PREFIX_QUESTIONS = 'search_ai_agent/questions/'
S3_PREFIX_ANSWERS = 'search_ai_agent/answers/'


def find_latest_file(pattern: str) -> str | None:
    """패턴에 맞는 파일 중 타임스탬프가 가장 최신인 파일을 반환합니다."""
    files = sorted(glob.glob(os.path.join(INTEGRATED_DIR, pattern)))
    return files[-1] if files else None


def upload_file(s3_client, local_path: str, s3_prefix: str, dry_run: bool) -> bool:
    """파일을 S3에 업로드합니다."""
    filename = os.path.basename(local_path)
    s3_key = s3_prefix + filename

    if dry_run:
        print(f"  [DRY-RUN] {local_path} → s3://{S3_BUCKET}/{s3_key}")
        return True

    print(f"  업로드 중: {local_path} → s3://{S3_BUCKET}/{s3_key}")
    s3_client.upload_file(local_path, S3_BUCKET, s3_key)
    print(f"  완료: s3://{S3_BUCKET}/{s3_key}")
    return True


def main():
    parser = argparse.ArgumentParser(description='통합 JSONL 파일을 S3에 업로드')
    parser.add_argument('--dry-run', action='store_true',
                        help='업로드 없이 대상 파일만 확인')
    parser.add_argument('--profile', default=None,
                        help='AWS 프로필 이름 (기본: default credential chain)')
    args = parser.parse_args()

    # 최신 파일 찾기
    q_file = find_latest_file('question_*.jsonl')
    a_file = find_latest_file('answer_*.jsonl')

    if not q_file and not a_file:
        print(f"업로드할 파일이 없습니다. ({INTEGRATED_DIR})")
        return

    print("업로드 대상:")
    if q_file:
        print(f"  questions: {q_file}")
    if a_file:
        print(f"  answers:   {a_file}")
    print()

    # S3 클라이언트 생성
    session_kwargs = {}
    if args.profile:
        session_kwargs['profile_name'] = args.profile

    session = boto3.Session(**session_kwargs)
    s3_client = session.client('s3')

    # 업로드
    success = True
    if q_file:
        if not upload_file(s3_client, q_file, S3_PREFIX_QUESTIONS, args.dry_run):
            success = False
    if a_file:
        if not upload_file(s3_client, a_file, S3_PREFIX_ANSWERS, args.dry_run):
            success = False

    if success:
        print("\nS3 업로드 완료" + (" (dry-run)" if args.dry_run else ""))
    else:
        print("\nS3 업로드 중 오류 발생")


if __name__ == '__main__':
    main()
