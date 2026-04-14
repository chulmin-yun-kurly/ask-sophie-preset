"""
파이프라인 전역 설정
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── 상품 ──────────────────────────────────────────
PRODUCT_ID = os.environ.get('PRODUCT_ID', 'olive_oil')

# ── OpenAI ────────────────────────────────────────
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

# 모델
MODEL_MAIN = 'gpt-5.4-mini'         # 데이터 준비, 질문 생성
MODEL_LIGHT = 'gpt-5.4-mini'       # 클러스터 병합, 레이블, 답변
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

# 비교 파이프라인
COMPARE_CANDIDATE_COUNT = 30        # 임베딩 top-K 후보 수
COMPARE_FINAL_MIN = 5               # LLM 최종 선택 하한
COMPARE_FINAL_MAX = 10              # LLM 최종 선택 상한
COMPARE_BATCH_SIZE = 5              # 질문 배치 크기
COMPARE_MAX_CONCURRENT = 5          # 동시 요청 수
COMPARE_SUGGEST_COUNT = 10          # 비교 질문 suggest 개수
COMPARE_SUGGEST_CANDIDATE_COUNT = 50  # suggest 후보 수 (임베딩 top-K)
COMPARE_RELATED_QUESTION_COUNT = 4  # 비교 질문당 생성할 related_question(변형) 개수

# ── Temperature ─────────────────────────────────
TEMP_PREPARE = 0.3              # 데이터 준비 (key_description, topic_keyword)
TEMP_QNA_GENERATE = 1.0         # QnA 질문 생성
TEMP_QNA_ANSWER = 0.5           # QnA 답변 생성
TEMP_CLUSTER_MERGE = 0.1        # 클러스터 병합
TEMP_SUGGEST = 0.3              # suggest 매핑
TEMP_PRODUCT_GENERATE = 0.5     # 상품 소개 텍스트 생성
TEMP_PRODUCT_QUESTION = 1.0     # 상품별 질문 생성
TEMP_PRODUCT_ANSWER = 0.5       # 상품별 답변 생성
TEMP_COMPARE_MATCH = 0.2        # 비교 파이프라인: 상품 필터링
TEMP_COMPARE_ANSWER = 0.5       # 비교 파이프라인: 답변 생성
TEMP_COMPARE_RELATED = 0.7      # 비교 파이프라인: related_question 변형 생성

# ── 기타 ──────────────────────────────────────────
SKIP_EMPTY_DESC = True              # description 없는 상품 스킵
MIN_CONTENT_COUNT = 3               # 최종 결과에서 content_count 최소값 (미만은 제외)
