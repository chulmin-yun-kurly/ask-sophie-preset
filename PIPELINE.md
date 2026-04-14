# 파이프라인 실행 가이드

## 전체 구조

```
                              run_pipeline.py
                                    │
                 ┌──────────────────┼──────────────────┐
                 │                  │                   │
          run_qna_pipeline    run_product_pipeline   run_compare_pipeline
                 │                  │                   │
     ┌───────────┴───┐    ┌────────┴────┐     ┌───────┴───────┐
     │   Phase 1: QA │    │  Phase 1: QA│     │   Phase 1: QA │
     │  prepare      │    │  product    │     │   prepare     │
     │  qna          │    │  question   │     │   match       │
     │  invert       │    │  answer     │     │   answer      │
     │  cluster      │    └─────────────┘     └───────────────┘
     │  answer       │            │                   │
     └───────────────┘    ┌──────┴──────┐     ┌──────┴──────┐
             │            │Phase 2: Sug.│     │Phase 2: Sug.│
     ┌───────┴───────┐   │  suggest    │     │  suggest    │
     │Phase 2: Suggest│   └─────────────┘     └─────────────┘
     │  suggest       │           │                   │
     └───────────────┘    ┌──────┴──────┐     ┌──────┴──────┐
             │            │Phase 3: Exp.│     │Phase 3: Exp.│
     ┌───────┴───────┐   │  export     │     │  export     │
     │Phase 3: Export │   └─────────────┘     └─────────────┘
     │  export        │           │                   │
     └───────────────┘           │                   │
             │                    │                   │
             └──────────────────┼───────────────────┘
                                │
                        Phase 4: Merge
                       steps/merge_jsonl.py
```

**Phase 구조**: 전 상품의 QA가 완료된 후에 Suggest를 실행하므로, 모든 파이프라인의 질문이 Suggest 후보 풀에 포함됩니다.

---

## 전체 파이프라인 실행

```bash
# 기본 (olive_oil, qna+product+compare → merge)
python run_pipeline.py

# 상품 지정
python run_pipeline.py --product cheese

# 여러 상품
python run_pipeline.py --product olive_oil,cheese

# 전 상품 순차
python run_pipeline.py --product all

# 전 상품 동시 (Phase별 barrier 유지)
python run_pipeline.py --product all --parallel

# 특정 파이프라인만
python run_pipeline.py --product cheese qna           # QnA만
python run_pipeline.py --product cheese qna compare   # QnA + 비교만
python run_pipeline.py merge                           # JSONL 통합만

# 테스트 모드 (N개 상품만 샘플링, 별도 시트에 기록)
python run_pipeline.py --test 5                        # 상위 5개 상품
python run_pipeline.py --test 5 --test-random          # 랜덤 5개
python run_pipeline.py --test 3 --test-comment "v2"    # 시트 제목에 코멘트
```

---

## QnA 파이프라인 (`run_qna_pipeline.py`)

Google Sheet의 상품 데이터로부터 소비자 질문을 생성하고, 클러스터링·답변·추천을 거쳐 JSONL로 내보냅니다.

```
 [merged_final 시트]
        │
        ▼
   1. prepare ─────→ [prepared_data 시트]     key_description, topic_keyword 생성
        │
        ▼
   2. qna ─────────→ [qna_data 시트]          카테고리별 소비자 질문 생성
        │
        ▼
   3. invert ──────→ inverted_questions.csv    질문별 상품 목록으로 역전
        │
        ▼
   4. cluster ─────→ [qna_group 시트]          유사 질문 병합 + 대표 질문 선정
        │
        ▼
   5. answer ──────→ [qna_group 시트]          답변 + 검색 키워드 생성
        │
        ▼
   6. suggest ─────→ [qna_group 시트]          연관 추천 매핑
        │                                       (풀: qna_group + compare_qna)
        ▼
   7. export ──────→ question_qna.jsonl        JSONL 내보내기
                      answer_qna.jsonl
```

```bash
python run_qna_pipeline.py --product olive_oil              # 전체 실행
python run_qna_pipeline.py --product olive_oil qa           # Phase 1만 (prepare~answer)
python run_qna_pipeline.py --product olive_oil suggest      # Phase 2만
python run_qna_pipeline.py --product olive_oil export       # Phase 3만
python run_qna_pipeline.py --product olive_oil prepare      # 개별 단계
python run_qna_pipeline.py --product olive_oil cluster answer  # 복수 단계
```

### 출력 파일

| 파일 | 설명 |
|------|------|
| `output/{product}/qna_result.json` | QnA 전체 결과 (카테고리별 그룹) |
| `output/{product}/content_map.json` | 상품번호 → 상품명 매핑 |
| `output/{product}/questions/question_qna.jsonl` | 질문 JSONL (answerType: RECOMMEND) |
| `output/{product}/answers/answer_qna.jsonl` | 답변 JSONL |

---

## 상품 파이프라인 (`run_product_pipeline.py`)

개별 상품 소개 텍스트 → 상품별 질문/답변 → JSONL 내보내기

```
 [prepared_data 시트]
        │
        ▼
   1. product ─────→ [product_data 시트]       소개/홍보 텍스트 생성
        │
        ▼
   2. question ────→ [product_qna 시트]        상품별 질문 생성
        │
        ▼
   3. answer ──────→ [product_qna 시트]        상품별 답변 생성
        │
        ▼
   4. suggest ─────→ [product_data/qna 시트]   연관 추천 매핑
        │                                       (풀: qna_group + compare_qna)
        ▼
   5. export ──────→ question_product.jsonl     JSONL 내보내기
                      answer_product.jsonl       (answerType: SUMMARY)
                      question_product_qna.jsonl
                      answer_product_qna.jsonl   (answerType: INFO)
```

```bash
python run_product_pipeline.py --product olive_oil          # 전체 실행
python run_product_pipeline.py --product olive_oil qa       # Phase 1만
python run_product_pipeline.py --product olive_oil product  # 개별 단계
```

### 출력 파일

| 파일 | 설명 |
|------|------|
| `output/{product}/product_data.json` | 상품 소개 전체 결과 |
| `output/{product}/questions/question_product.jsonl` | 상품 소개 질문 JSONL (answerType: SUMMARY) |
| `output/{product}/answers/answer_product.jsonl` | 상품 소개 답변 JSONL |
| `output/{product}/questions/question_product_qna.jsonl` | 상품별 QnA 질문 JSONL (answerType: INFO) |
| `output/{product}/answers/answer_product_qna.jsonl` | 상품별 QnA 답변 JSONL |

---

## 비교 파이프라인 (`run_compare_pipeline.py`)

수동 입력된 비교 질문에 대해 상품을 매칭하고, 비교축 중심 답변을 생성합니다.

```
 [compare_question 시트]
        │
        ▼
   1. prepare ─────→ [compare_prepared 시트]   id 부여 + related_questions 생성
        │
        ▼
   2. match ───────→ [compare_prepared 시트]   임베딩 top-K + LLM 필터로 상품 매칭
        │
        ▼
   3. answer ──────→ [compare_qna 시트]        비교 테이블 포함 답변 생성
        │
        ▼
   4. suggest ─────→ [compare_qna 시트]        연관 추천 매핑
        │                                       (풀: qna_group + compare_qna)
        ▼
   5. export ──────→ question_compare.jsonl     JSONL 내보내기
                      answer_compare.jsonl       (answerType: COMPARE)
```

```bash
python run_compare_pipeline.py --product olive_oil          # 전체 실행
python run_compare_pipeline.py --product olive_oil qa       # Phase 1만
python run_compare_pipeline.py --product olive_oil match    # 개별 단계
```

### 출력 파일

| 파일 | 설명 |
|------|------|
| `output/{product}/questions/question_compare.jsonl` | 비교 질문 JSONL (answerType: COMPARE) |
| `output/{product}/answers/answer_compare.jsonl` | 비교 답변 JSONL |

---

## JSONL 통합 (merge)

전 상품의 JSONL 파일을 통합하여 `output/integrated/`에 최종 파일 생성.
각 상품의 `id_prefix`를 사용하여 ID 충돌을 방지합니다.

```bash
python run_pipeline.py merge                               # 전 상품
python run_pipeline.py --product olive_oil,cheese merge     # 지정 상품만
PYTHONPATH=. python steps/merge_jsonl.py                    # 직접 실행
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

## Suggest 풀 구성

모든 파이프라인의 suggest 단계는 동일한 후보 풀을 사용합니다:

| 풀 소스 | 포함 데이터 |
|---------|-----------|
| `qna_group` 시트 | QnA 대표 질문 (id: `c01_s000` 형식) |
| `compare_qna` 시트 | 비교 질문 (id: `compare_001` 형식) |

JSONL export 시 suggest ID는 접두사 기반으로 `keyword`/`product`로 분류됩니다:
- `pq_*`, `pqq_*` → `product` 배열
- 그 외 → `keyword` 배열

---

## 테스트 모드

일부 데이터만으로 파이프라인을 빠르게 검증합니다. 별도 Google Sheet에 결과를 기록하며, merge 단계는 자동 생략됩니다.

```bash
python run_pipeline.py --test 5                            # 상위 5개 상품 샘플링
python run_pipeline.py --test 5 --test-random              # 랜덤 5개 상품
python run_pipeline.py --test 3 --test-comment "프롬프트v2"  # 시트 제목에 코멘트
python run_pipeline.py --test 3 --test-sheet-id SHEET_ID   # 기존 테스트 시트 재사용
```

---

## 사전 준비 (새 상품 추가 시)

1. `products/{product_id}.yaml` — 상품 설정
2. `products/categories/{product_id}.txt` — 질문 카테고리 정의
3. `prompts/shared/knowledge/{product_id}.md` — 상품 도메인 지식
4. Google Sheet에 원천 데이터(`merged_final`) 준비

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

## 출력 디렉토리 구조

```
output/
  olive_oil/                        # 상품별 출력
    qna_result.json
    product_data.json
    content_map.json
    inverted_questions.csv
    questions/
      question_qna.jsonl            # answerType: RECOMMEND
      question_product.jsonl        # answerType: SUMMARY
      question_product_qna.jsonl    # answerType: INFO
      question_compare.jsonl        # answerType: COMPARE
    answers/
      answer_qna.jsonl
      answer_product.jsonl
      answer_product_qna.jsonl
      answer_compare.jsonl
  cheese/                           # 동일 구조
    ...
  integrated/                       # 전 상품 통합
    question_{timestamp}.jsonl
    answer_{timestamp}.jsonl
```

---

## 하이라이팅

LLM이 생성하는 답변 텍스트에 `<strong>...</strong>` 태그로 핵심 키워드를 강조합니다.

| 파이프라인 | 적용 필드 |
|-----------|----------|
| QnA | description |
| Product (소개) | features, story, recommendation |
| Product (QnA) | description |
| Compare | description, bulletList |

JSONL export 시 `strip_html()`은 화이트리스트 방식으로 `<strong>` 태그만 보존하고 나머지 HTML 태그를 제거합니다.

---

## 설정 (`config.py`)

### LLM 모델

| 변수 | 모델 | 용도 |
|------|------|------|
| `MODEL_MAIN` | gpt-5.4-mini | 데이터 준비, 질문 생성, 홍보 텍스트 |
| `MODEL_LIGHT` | gpt-5.4-mini | 클러스터 병합, 답변, suggest, related_question |
| `MODEL_EMBEDDING` | text-embedding-3-small | 임베딩 (클러스터링, suggest 후보, 비교 매칭) |

### Temperature

| 변수 | 값 | 용도 |
|------|-----|------|
| `TEMP_PREPARE` | 0.3 | 데이터 준비 |
| `TEMP_QNA_GENERATE` | 1.0 | QnA 질문 생성 |
| `TEMP_QNA_ANSWER` | 0.5 | QnA 답변 생성 |
| `TEMP_CLUSTER_MERGE` | 0.1 | 클러스터 병합 |
| `TEMP_SUGGEST` | 0.3 | suggest 매핑 |
| `TEMP_PRODUCT_GENERATE` | 0.5 | 상품 소개 텍스트 |
| `TEMP_PRODUCT_QUESTION` | 1.0 | 상품별 질문 생성 |
| `TEMP_PRODUCT_ANSWER` | 0.5 | 상품별 답변 |
| `TEMP_COMPARE_MATCH` | 0.2 | 비교 상품 필터링 |
| `TEMP_COMPARE_ANSWER` | 0.5 | 비교 답변 |
| `TEMP_COMPARE_RELATED` | 0.7 | related_question 변형 |

### 배치 / 동시성

| 변수 | 값 | 설명 |
|------|-----|------|
| `PREPARE_BATCH_SIZE` | 5 | prepare / generate_products 배치 |
| `PREPARE_MAX_CONCURRENT` | 5 | prepare / generate_products 동시성 |
| `QNA_BATCH_SIZE` | 5 | make_qna_data 배치 |
| `QNA_MAX_CONCURRENT` | 5 | make_qna_data 동시성 |
| `CLUSTER_MAX_QUESTIONS` | 10 | 클러스터당 최대 질문 수 |
| `CLUSTER_MAX_CONCURRENT` | 10 | 클러스터링 동시성 |
| `CLUSTER_ANSWER_BATCH_SIZE` | 5 | 답변 생성 배치 |
| `EMBEDDING_BATCH_SIZE` | 100 | 임베딩 배치 |
| `COMPARE_CANDIDATE_COUNT` | 30 | 비교 임베딩 top-K |
| `COMPARE_FINAL_MIN` / `MAX` | 5 / 10 | LLM 최종 선택 범위 |
| `COMPARE_BATCH_SIZE` | 5 | 비교 질문 배치 |
| `COMPARE_MAX_CONCURRENT` | 5 | 비교 동시성 |
| `COMPARE_SUGGEST_COUNT` | 10 | 비교 suggest 개수 |
| `COMPARE_SUGGEST_CANDIDATE_COUNT` | 50 | 비교 suggest 후보 수 |
| `COMPARE_RELATED_QUESTION_COUNT` | 4 | 비교 질문 변형 개수 |
| `MIN_CONTENT_COUNT` | 3 | 클러스터 최소 상품 수 (미만 제외) |

---

## 프롬프트 치환 규칙

`llm_client.load_prompt()` 호출 시 자동 치환:

| 플레이스홀더 | 소스 | 설명 |
|-------------|------|------|
| `{product_name}` | `products/{product_id}.yaml` → `product_name` | 상품명 |
| `{categories}` | `products/categories/{categories_file}` | 질문 카테고리 정의 |

배경 지식은 `build_system_prompt()` 호출 시 시스템 프롬프트 끝에 자동 결합.
