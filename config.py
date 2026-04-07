"""
파이프라인 전역 설정
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── OpenAI ────────────────────────────────────────
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# 모델
MODEL_MAIN = 'gpt-5.4-mini'         # 데이터 준비, 질문 생성
MODEL_LIGHT = 'gpt-4.1-mini'       # 클러스터 병합, 레이블, 답변
MODEL_EMBEDDING = 'text-embedding-3-small'

# ── 배치 / 동시성 ────────────────────────────────
PREPARE_BATCH_SIZE = 5
PREPARE_MAX_CONCURRENT = 5

QNA_BATCH_SIZE = 5
QNA_MAX_CONCURRENT = 5

CLUSTER_MAX_QUESTIONS = 10          # 클러스터당 최대 질문 수
CLUSTER_MAX_CONCURRENT = 10
CLUSTER_ANSWER_BATCH_SIZE = 5

EMBEDDING_BATCH_SIZE = 100

# ── 기타 ──────────────────────────────────────────
SKIP_EMPTY_DESC = True              # description 없는 상품 스킵
MIN_CONTENT_COUNT = 3               # 최종 결과에서 content_count 최소값 (미만은 제외)
