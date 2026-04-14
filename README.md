# Ask Sophie — Data Analyzer

상품 데이터를 기반으로 소비자 질문·답변·비교 데이터를 생성하는 파이프라인.
QnA, 상품 소개, 상품 비교 세 가지 파이프라인을 Phase 단위로 실행합니다.

## 파이프라인 개요

```
                         run_pipeline.py
          ┌──────────────────┬──────────────────┐
          │                  │                   │
       QnA 파이프라인    상품 파이프라인     비교 파이프라인
    (run_qna_pipeline)  (run_product_pipeline) (run_compare_pipeline)

━━━━ Phase 1: QA ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   prepare            product              prepare
   qna                question             match
   invert             answer               answer
   cluster
   answer

━━━━ Phase 2: Suggest ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   suggest             suggest              suggest
          ↘               ↓               ↙
          공통 풀: qna_group + compare_qna

━━━━ Phase 3: Export ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   export              export               export
     │                   │                     │
     ▼                   ▼                     ▼
  RECOMMEND          SUMMARY / INFO         COMPARE
  question_qna       question_product       question_compare
  answer_qna         question_product_qna   answer_compare
                     answer_product
                     answer_product_qna

━━━━ Phase 4: Merge ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                   steps/merge_jsonl.py
                          │
                          ▼
              output/integrated/*.jsonl
```

## 빠른 시작

```bash
# 환경 변수 설정
export OPENAI_API_KEY=sk-...

# 기본 실행 (olive_oil, 전체 파이프라인)
python run_pipeline.py

# 상품 지정
python run_pipeline.py --product cheese

# 전 상품 동시 실행
python run_pipeline.py --product all --parallel

# 테스트 모드 (5개 상품만 샘플링, 별도 시트)
python run_pipeline.py --test 5
```

## 개별 파이프라인 실행

### QnA 파이프라인

```
merged_final → prepare → qna → invert → cluster → answer → suggest → export
                                                                         ↓
                                                        question_qna.jsonl (RECOMMEND)
                                                        answer_qna.jsonl
```

```bash
python run_qna_pipeline.py --product olive_oil              # 전체
python run_qna_pipeline.py --product olive_oil qa           # Phase 1 (prepare~answer)
python run_qna_pipeline.py --product olive_oil suggest      # Phase 2
python run_qna_pipeline.py --product olive_oil export       # Phase 3
python run_qna_pipeline.py --product olive_oil prepare      # 개별 단계
```

### 상품 파이프라인

```
prepared_data → product → question → answer → suggest → export
                                                          ↓
                                         question_product.jsonl (SUMMARY)
                                         answer_product.jsonl
                                         question_product_qna.jsonl (INFO)
                                         answer_product_qna.jsonl
```

```bash
python run_product_pipeline.py --product olive_oil          # 전체
python run_product_pipeline.py --product olive_oil qa       # Phase 1
python run_product_pipeline.py --product olive_oil product  # 개별 단계
```

### 비교 파이프라인

```
compare_question → prepare → match → answer → suggest → export
                                                          ↓
                                         question_compare.jsonl (COMPARE)
                                         answer_compare.jsonl
```

```bash
python run_compare_pipeline.py --product olive_oil          # 전체
python run_compare_pipeline.py --product olive_oil qa       # Phase 1
python run_compare_pipeline.py --product olive_oil match    # 개별 단계
```

## 출력 디렉토리 구조

```
output/
  {product}/
    qna_result.json                 # QnA 전체 결과
    product_data.json               # 상품 소개 전체 결과
    content_map.json                # 상품번호 → 상품명 매핑
    inverted_questions.csv          # 질문 역전 중간 산출물
    questions/
      question_qna.jsonl            # RECOMMEND
      question_product.jsonl        # SUMMARY
      question_product_qna.jsonl    # INFO
      question_compare.jsonl        # COMPARE
    answers/
      answer_qna.jsonl
      answer_product.jsonl
      answer_product_qna.jsonl
      answer_compare.jsonl
  integrated/                       # 전 상품 통합 (merge)
    question_{timestamp}.jsonl
    answer_{timestamp}.jsonl
```

## 새 상품 추가

1. `products/{product_id}.yaml` 작성

```yaml
product_id: olive_oil
product_name: "올리브오일"
sheet_id: "GOOGLE_SHEET_ID"
knowledge_file: "olive_oil.md"
categories_file: "olive_oil.txt"
id_prefix: "0"                    # JSONL 통합 시 ID 충돌 방지용
```

2. `products/categories/{product_id}.txt` — 질문 카테고리 정의
3. `prompts/shared/knowledge/{product_id}.md` — 상품 도메인 지식
4. Google Sheet에 `merged_final` 시트 준비

## 테스트 모드

일부 데이터만으로 파이프라인을 빠르게 검증합니다. 별도 Google Sheet에 결과를 기록하며, merge 단계는 자동 생략됩니다.

```bash
python run_pipeline.py --test 5                             # 상위 5개 상품
python run_pipeline.py --test 5 --test-random               # 랜덤 5개
python run_pipeline.py --test 3 --test-comment "프롬프트v2"   # 시트 제목에 코멘트
python run_pipeline.py --test 3 --test-sheet-id SHEET_ID    # 기존 시트 재사용
```

## 설정 (`config.py`)

모든 설정은 `config.py`에서 중앙 관리됩니다.

| 구분 | 주요 변수 |
|------|----------|
| 모델 | `MODEL_MAIN` (gpt-5.4-mini), `MODEL_LIGHT` (gpt-5.4-mini), `MODEL_EMBEDDING` (text-embedding-3-small) |
| Temperature | 단계별 0.1~1.0 (`TEMP_PREPARE`, `TEMP_QNA_GENERATE`, `TEMP_QNA_ANSWER`, ...) |
| 배치/동시성 | 단계별 배치 크기 및 동시 요청 수 (`*_BATCH_SIZE`, `*_MAX_CONCURRENT`) |
| 비교 파이프라인 | 후보 수, 선택 범위, suggest 개수, related_question 개수 |
| 기타 | `SKIP_EMPTY_DESC`, `MIN_CONTENT_COUNT` |

상세 설정은 [PIPELINE.md](PIPELINE.md) 참조.

## 주요 유틸리티

| 파일 | 설명 |
|------|------|
| `config.py` | 전역 설정 (모델, 배치, temperature 등) |
| `llm_client.py` | OpenAI 클라이언트, 프롬프트 로더, 임베딩, strip_html |
| `sheet_reader.py` | Google Sheets 읽기/쓰기 |
| `product_config.py` | 상품 YAML 로더 |
| `test_config.py` | 테스트 모드 설정 및 시트 생성 |

## 데모 페이지

```bash
# 로컬 실행
streamlit run app.py

# Docker 실행
docker build -t ask-sophie-demo .
docker run -d -p 8502:8501 --name sophie-demo ask-sophie-demo
```

`output/` 디렉토리의 JSON 기반으로 동작 (Google Sheets 의존성 없음).
