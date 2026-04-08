# 파이프라인 실행 가이드

## 사전 준비 (새 상품 추가 시)

1. `products/{product_id}.yaml` — 상품 설정 (product_name, sheet_id, knowledge_file, categories_file, id_prefix)
2. `products/categories/{product_id}.txt` — 질문 카테고리 정의
3. `prompts/shared/knowledge/{product_id}.md` — 상품 도메인 지식
4. Google Sheet에 원천 데이터 준비

---

## 전체 파이프라인 실행

```bash
# 기본 (olive_oil, QnA → 상품 → JSONL 통합)
python run_pipeline.py

# 상품 지정
python run_pipeline.py --product cheese

# 특정 파이프라인만
python run_pipeline.py --product cheese qna        # QnA만
python run_pipeline.py --product cheese product     # 상품만
python run_pipeline.py merge                        # JSONL 통합만 (전 상품)
```

---

## QnA 파이프라인 (`run_qna_pipeline.py`)

Google Sheet의 상품 데이터 → 고객 질문 생성 → 답변 생성 → JSONL 내보내기

```bash
# 전체 실행
python run_qna_pipeline.py --product olive_oil

# 단계별 실행
python run_qna_pipeline.py --product olive_oil prepare   # 1. 데이터 준비 (key_description, topic_keyword)
python run_qna_pipeline.py --product olive_oil qna       # 2. 질문 생성 (카테고리별)
python run_qna_pipeline.py --product olive_oil invert    # 3. 질문 역전 & 동일 질문 통합
python run_qna_pipeline.py --product olive_oil cluster   # 4. 질문 클러스터링 & 대표 질문 선정
python run_qna_pipeline.py --product olive_oil answer    # 5. 답변 + 검색 키워드 생성
python run_qna_pipeline.py --product olive_oil suggest   # 6. 연관 추천 생성
python run_qna_pipeline.py --product olive_oil export    # 7. QnA JSON/JSONL 내보내기
```

### 출력 파일

| 파일 | 설명 |
|------|------|
| `output/{product_id}/qna_result.json` | QnA 전체 결과 (카테고리별 그룹) |
| `output/{product_id}/content_map.json` | 상품번호 → 상품명 매핑 |
| `output/{product_id}/questions/question_qna.jsonl` | 질문 JSONL |
| `output/{product_id}/answers/answer_qna.jsonl` | 답변 JSONL |

---

## 상품 파이프라인 (`run_product_pipeline.py`)

개별 상품 소개 텍스트 생성 → 상품별 질문/답변 생성 → JSONL 내보내기

```bash
# 전체 실행
python run_product_pipeline.py --product olive_oil

# 단계별 실행
python run_product_pipeline.py --product olive_oil product    # 1. 상품 소개/홍보 텍스트 생성
python run_product_pipeline.py --product olive_oil question   # 2. 상품별 질문 생성
python run_product_pipeline.py --product olive_oil answer     # 3. 상품별 답변 생성
python run_product_pipeline.py --product olive_oil suggest    # 4. 관련 질문(suggest) 매핑
python run_product_pipeline.py --product olive_oil export     # 5. 상품 JSON/JSONL 내보내기
```

### 출력 파일

| 파일 | 설명 |
|------|------|
| `output/{product_id}/product_data.json` | 상품 소개 전체 결과 |
| `output/{product_id}/questions/question_product.jsonl` | 상품 질문 JSONL |
| `output/{product_id}/questions/question_product_qna.jsonl` | 상품 QnA 질문 JSONL |
| `output/{product_id}/answers/answer_product.jsonl` | 상품 답변 JSONL |
| `output/{product_id}/answers/answer_product_qna.jsonl` | 상품 QnA 답변 JSONL |

---

## JSONL 통합 (merge)

전 상품의 JSONL 파일을 통합하여 `output/integrated/`에 최종 파일 생성.
각 상품의 `id_prefix`를 사용하여 ID 충돌을 방지합니다.

```bash
# run_pipeline.py 통해 실행
python run_pipeline.py merge

# 직접 실행
PYTHONPATH=. python steps/merge_jsonl.py
```

### 출력 파일

| 파일 | 설명 |
|------|------|
| `output/integrated/question_{timestamp}.jsonl` | 전 상품 질문 통합 |
| `output/integrated/answer_{timestamp}.jsonl` | 전 상품 답변 통합 |

### ID 프리픽스 규칙

| 상품 | id_prefix | 예시 |
|------|-----------|------|
| olive_oil | 0 | `0_c01_s000`, `0_pq_5000325` |
| cheese | 1 | `1_c01_s000`, `1_pq_1234567` |

---

## 출력 디렉토리 구조

```
output/
  olive_oil/                    # 상품별 출력
    qna_result.json
    product_data.json
    content_map.json
    inverted_questions.csv
    questions/
      question_qna.jsonl
      question_product.jsonl
      question_product_qna.jsonl
    answers/
      answer_qna.jsonl
      answer_product.jsonl
      answer_product_qna.jsonl
  cheese/                       # 동일 구조
    ...
  integrated/                   # 전 상품 통합
    question_{timestamp}.jsonl
    answer_{timestamp}.jsonl
```

---

## 상품 설정 구조

```
products/
  olive_oil.yaml                # 상품 설정
  cheese.yaml
  categories/
    olive_oil.txt               # 질문 카테고리 정의 (상품별)
    cheese.txt

prompts/
  shared/
    knowledge/
      olive_oil.md              # 도메인 지식 (상품별)
      cheese.md
    persona.txt                 # 공통 페르소나
```

### YAML 설정 예시

```yaml
product_id: olive_oil
product_name: "올리브오일"
sheet_id: "19c8o63Lck04VWeOHyEXiEcYDBv92LcISR17xP7UZpfs"
knowledge_file: "olive_oil.md"
categories_file: "olive_oil.txt"
id_prefix: "0"
```

---

## 프롬프트 치환 규칙

`llm_client.load_prompt()` 호출 시 자동 치환:

| 플레이스홀더 | 소스 | 설명 |
|-------------|------|------|
| `{product_name}` | `products/{product_id}.yaml` → `product_name` | 상품명 |
| `{categories}` | `products/categories/{categories_file}` | 질문 카테고리 정의 |

배경 지식은 `build_system_prompt()` 호출 시 시스템 프롬프트 끝에 자동 결합.

---

## 설정 (`config.py`)

### LLM 모델

| 변수 | 모델 | 용도 |
|------|------|------|
| `MODEL_MAIN` | gpt-4.1 | 데이터 준비, 질문 생성, 홍보 텍스트 생성 |
| `MODEL_LIGHT` | gpt-4.1-mini | 클러스터 병합, 레이블, 답변, 연관 추천 생성 |
| `MODEL_EMBEDDING` | text-embedding-3-small | 질문 유사도 기반 클러스터링, 연관 추천 후보 선정 |

### 배치 / 동시성

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `PREPARE_BATCH_SIZE` | 1 | prepare_data / generate_products 배치 크기 |
| `PREPARE_MAX_CONCURRENT` | 5 | prepare_data / generate_products 동시 요청 수 |
| `QNA_BATCH_SIZE` | 5 | make_qna_data 배치 크기 |
| `QNA_MAX_CONCURRENT` | 5 | make_qna_data 동시 요청 수 |
| `CLUSTER_MAX_QUESTIONS` | 10 | 클러스터당 최대 질문 수 |
| `CLUSTER_MAX_CONCURRENT` | 10 | 클러스터링 LLM 동시 요청 수 |
| `CLUSTER_ANSWER_BATCH_SIZE` | 20 | 답변 생성 배치 크기 |
| `EMBEDDING_BATCH_SIZE` | 100 | 임베딩 배치 크기 |
| `MIN_CONTENT_COUNT` | 3 | 클러스터링 결과에서 content_count 최소값 (미만 제외) |
