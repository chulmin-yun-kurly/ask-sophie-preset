# QnA 데이터 파이프라인

올리브오일 상품 데이터를 기반으로 소비자 질문을 생성하고, 클러스터링하여 구조화된 QnA 데이터를 만드는 파이프라인.

## 실행 방법

```bash
# 전체 QnA 파이프라인 실행
python run_pipeline.py

# 개별 단계 실행
python run_pipeline.py prepare          # 1단계만
python run_pipeline.py qna invert       # 2~3단계만
python run_pipeline.py cluster          # 4단계만
python run_pipeline.py answer           # 5단계만 (답변+키워드 생성)
python run_pipeline.py suggest          # 6단계만 (연관 추천 생성)
python run_pipeline.py export           # 7단계만

# 별도 파이프라인
python run_pipeline.py product           # 상품 데이터 생성

# 데모 페이지 (로컬)
streamlit run app.py

# 데모 페이지 (Docker)
docker build -t ask-sophie-demo .
docker run -d -p 8502:8501 --name sophie-demo ask-sophie-demo
```

## QnA 파이프라인 단계

```
[Google Sheet: merged_final]
        │
        ▼
   1. steps/prepare_data.py ──→ [Google Sheet: prepared_data]
        │
        ▼
   2. steps/make_qna_data.py ──→ [Google Sheet: qna_data]
        │
        ▼
   3. steps/invert_questions.py ──→ output/inverted_questions.csv
        │
        ▼
   4. steps/cluster_questions.py ──→ [Google Sheet: qna_group]
        │                             (content_count < MIN_CONTENT_COUNT 필터링 포함)
        ▼
   5. steps/generate_answers.py ──→ [Google Sheet: qna_group + id/answer/keywords]
        │
        ▼
   6. steps/build_suggestions.py ──→ [Google Sheet: qna_group + suggest]
        │
        ▼
   7. steps/export_qna_json.py ──→ output/qna_result.json
                                    output/qna_result.jsonl
                                    output/content_map.json
                                    output/product_data.json
```

### 1단계: 데이터 준비 (`prepare_data.py`)

- **입력**: `merged_final` 시트 (상품명, description 등)
- **처리**: LLM(gpt-4.1)으로 각 상품의 `key_description`(핵심 설명)과 `topic_keyword`(특성 키워드) 생성
- **출력**: `prepared_data` 시트
- **프롬프트**: `prompts/system.txt`, `prompts/user.txt`
- **설정**: `PREPARE_BATCH_SIZE`, `PREPARE_MAX_CONCURRENT`, `SKIP_EMPTY_DESC` (`config.py`)

### 2단계: 질문 생성 (`make_qna_data.py`)

- **입력**: `prepared_data` 시트, `guide` 시트 (카테고리 정의)
- **처리**: LLM(gpt-4.1)으로 상품별 카테고리 기반 소비자 질문 생성 (카테고리당 1~3개)
- **출력**: `qna_data` 시트 (`question_list` 컬럼에 카테고리별 질문 JSON)
- **프롬프트**: `prompts/qna_system.txt`, `prompts/qna_user.txt`
- **설정**: `QNA_BATCH_SIZE`, `QNA_MAX_CONCURRENT` (`config.py`)

### 3단계: 질문 역전 & 통합 (`invert_questions.py`)

- **입력**: `qna_data` 시트
- **처리**:
  - 상품별 질문 → 질문별 상품 목록으로 역전
  - 완전 동일 질문의 `content_no` 합산
- **출력**: `output/inverted_questions.csv` (category, question, content_count, content_list)

### 4단계: 클러스터링 (`cluster_questions.py`)

- **입력**: `output/inverted_questions.csv`
- **처리** (7개 서브 스텝):
  1. CSV 읽기
  2. 임베딩 생성 (`text-embedding-3-small`)
  3. 카테고리별 KMeans 클러스터링 (클러스터당 최대 10개 질문 목표)
  4. LLM(gpt-4.1-mini)으로 클러스터 내 유사 질문 병합
  5. LLM(gpt-4.1-mini)으로 클러스터 레이블 생성
  6. `content_count < MIN_CONTENT_COUNT` 그룹 필터링
  7. 결과 저장
- **출력**: `qna_group` 시트
- **프롬프트**: `prompts/merge_system.txt`, `prompts/merge_user.txt`, `prompts/label_system.txt`, `prompts/label_user.txt`
- **설정**: `CLUSTER_MAX_QUESTIONS`, `CLUSTER_MAX_CONCURRENT`, `EMBEDDING_BATCH_SIZE`, `MIN_CONTENT_COUNT` (`config.py`)

### 5단계: 답변 + 검색 키워드 생성 (`generate_answers.py`)

- **입력**: `qna_group` 시트, `guide` 시트, `prepared_data` 시트
- **처리**: ID 생성(c01_s000 형식) + LLM(gpt-4.1-mini)으로 대표 질문별 답변 + 검색 키워드 생성 (소피 페르소나, 실제 상품 정보 기반)
- **출력**: `qna_group` 시트 (id, answer, search_keywords 컬럼 추가)
- **프롬프트**: `prompts/answer_system.txt`, `prompts/answer_user.txt`
- **설정**: `CLUSTER_MAX_CONCURRENT`, `CLUSTER_ANSWER_BATCH_SIZE` (`config.py`)

### 6단계: 연관 추천 생성 (`build_suggestions.py`)

- **입력**: `qna_group` 시트, `prepared_data` 시트
- **처리**:
  1. 전체 그룹의 representative를 임베딩 (`text-embedding-3-small`)
  2. 각 그룹마다 cosine similarity 상위 20개 후보 선정
  3. LLM(gpt-4.1-mini)으로 후보 중 연관 추천 5개 선정 (상품 특성 참고)
- **출력**: `qna_group` 시트 (`suggest` 컬럼 추가)
- **프롬프트**: `prompts/suggest_system.txt`, `prompts/suggest_user.txt`
- **설정**: `CLUSTER_MAX_CONCURRENT`, `EMBEDDING_BATCH_SIZE` (`config.py`)

### 7단계: JSON 내보내기 (`export_qna_json.py`)

- **입력**: `qna_group` 시트, `guide` 시트, `prepared_data` 시트, `product_data` 시트
- **처리**: category_id 포함하여 JSON 구조화 + 부가 데이터 저장
- **출력**:
  - `output/qna_result.json` — QnA 전체 구조화 데이터
  - `output/qna_result.jsonl` — 그룹 1개 = 1줄
  - `output/content_map.json` — content_no → content_nm 매핑
  - `output/product_data.json` — content_no → 홍보 텍스트 매핑

## 별도 파이프라인: 상품 데이터 (`generate_products.py`)

```
[Google Sheet: prepared_data]
        │
        ▼
   steps/product/generate_products.py ──→ [Google Sheet: product_data]
```

- **입력**: `prepared_data` 시트 (description이 있는 상품만)
- **처리**: LLM(gpt-4.1)으로 상품별 홍보 텍스트 생성
- **출력**: `product_data` 시트 (content_no, content_nm, headline, strengths, stories, targetUser)
- **프롬프트**: `prompts/product/product_system.txt`, `prompts/product/product_user.txt`
- **설정**: `PREPARE_BATCH_SIZE`, `PREPARE_MAX_CONCURRENT` (`config.py`)

## 최종 데이터 구조 (`qna_result.json`)

```json
{
  "total_categories": 6,
  "total_groups": 288,
  "total_questions": 877,
  "categories": [
    {
      "category_id": 1,
      "category": "컬리 특화",
      "groups": [
        {
          "id": "c01_s000",
          "sub_group": 0,
          "sub_group_label": "단일 품종 프리미엄",
          "representative": "단일 품종으로 만든 프리미엄 올리브오일 있을까요?",
          "answer": "단일 품종으로 깊은 풍미를 자랑하는 프리미엄 올리브오일이 있어요.",
          "search_keywords": ["단일 품종 올리브오일", "싱글 에스테이트 오일"],
          "suggest": ["c02_s003", "c05_s012"],
          "question_count": 4,
          "content_count": 4,
          "questions": ["...", "..."],
          "content_list": ["1000045312", "..."]
        }
      ]
    }
  ]
}
```

## 상품 데이터 구조 (`product_data.json`)

```json
{
  "1000045312": {
    "content_nm": "상품명",
    "headline": "<h3>핵심 매력 한 줄</h3>",
    "strengths": "<ul><li>특장점 1</li><li>특장점 2</li></ul>",
    "stories": "<p>브랜드 스토리, 생산 배경</p>",
    "targetUser": "<ul><li>이런 분께 추천</li></ul>"
  }
}
```

## 카테고리 체계 (`guide` 시트)

| ID | 카테고리 | 설명 |
|----|----------|------|
| 1 | 컬리 특화 | MD 추천, 브랜드 스토리, 산지 직송 등 |
| 2 | 품질/인증 | DOP/IGP 인증, 산도, 폴리페놀, 냉압착 등 |
| 3 | 용도/상황 | 요리 용도, 생식, 캠핑, 아이 등 |
| 4 | 페어링 | 특정 음식과의 조합 |
| 5 | 상품 특성 | 맛, 향, 품종, 용기 형태 등 |
| 6 | 명시적 정보 기반 | 용량, 원산지, 형태 등 스펙 기반 |

## 파일 구조

```
data_analyzer/
├── config.py                # 전역 설정 (API 키, 모델명, 배치/동시성 등)
├── llm_client.py            # OpenAI 클라이언트 + 공용 유틸 (chat_json, load_prompt, get_embeddings)
├── sheet_reader.py          # Google Sheets 읽기/쓰기 유틸리티
├── run_pipeline.py          # 파이프라인 실행기
├── app.py                   # Streamlit 데모 페이지 (로컬 JSON 기반)
├── Dockerfile               # 데모 페이지 Docker 이미지
├── requirements-app.txt     # 데모 페이지 의존성 (streamlit, pandas)
├── .dockerignore
├── steps/
│   ├── prepare_data.py      # 1단계: 데이터 준비
│   ├── make_qna_data.py     # 2단계: 질문 생성
│   ├── invert_questions.py  # 3단계: 질문 역전/통합
│   ├── cluster_questions.py # 4단계: 클러스터링 (MIN_CONTENT_COUNT 필터링 포함)
│   ├── generate_answers.py  # 5단계: ID 생성 + 답변 + 검색 키워드 생성
│   ├── build_suggestions.py # 6단계: 연관 추천 생성
│   ├── export_qna_json.py   # 7단계: JSON 내보내기 (qna + content_map + product_data)
│   └── product/             # 별도: 상품 데이터 파이프라인
├── prompts/
│   ├── knowledge.md         # 올리브오일 배경 지식 (모든 LLM 호출에 공통 적용)
│   ├── system.txt           # prepare_data 시스템 프롬프트
│   ├── user.txt             # prepare_data 유저 프롬프트
│   ├── qna_system.txt       # make_qna_data 시스템 프롬프트
│   ├── qna_user.txt         # make_qna_data 유저 프롬프트
│   ├── merge_system.txt     # 클러스터 내 질문 병합 시스템 프롬프트
│   ├── merge_user.txt       # 클러스터 내 질문 병합 유저 프롬프트
│   ├── label_system.txt     # 클러스터 레이블 생성 시스템 프롬프트
│   ├── label_user.txt       # 클러스터 레이블 생성 유저 프롬프트
│   ├── answer_system.txt    # 답변 생성 시스템 프롬프트 (소피 페르소나)
│   ├── answer_user.txt      # 답변 + 검색 키워드 생성 유저 프롬프트
│   ├── suggest_system.txt   # 연관 추천 시스템 프롬프트
│   ├── suggest_user.txt     # 연관 추천 유저 프롬프트
│   ├── product/product_system.txt     # 상품 텍스트 시스템 프롬프트 (소피 페르소나)
│   └── product/product_user.txt       # 상품 텍스트 유저 프롬프트
└── output/
    ├── inverted_questions.csv  # 3단계 중간 산출물
    ├── qna_result.json         # QnA 최종 산출물
    ├── content_map.json        # content_no → content_nm 매핑
    ├── product_data.json       # content_no → 상품 텍스트 매핑
    ├── questions/
    │   ├── question_qna.jsonl           # QnA 질문 JSONL
    │   ├── question_product.jsonl       # 상품 질문 JSONL
    │   └── question_product_qna.jsonl   # 상품 QnA 질문 JSONL
    └── answers/
        ├── answer_qna.jsonl             # QnA 답변 JSONL
        ├── answer_product.jsonl         # 상품 답변 JSONL
        └── answer_product_qna.jsonl     # 상품 QnA 답변 JSONL
```

## 설정 (`config.py`)

모든 설정은 `config.py`에서 중앙 관리됩니다. API 키는 환경변수 `OPENAI_API_KEY`가 있으면 우선 사용합니다.

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

## 공용 유틸리티 (`llm_client.py`)

| 함수 | 설명 |
|------|------|
| `load_prompt(filename)` | `prompts/` 디렉토리에서 프롬프트 파일 로드 |
| `load_knowledge()` | `prompts/knowledge.md` 로드 및 캐시 |
| `build_system_prompt(base_prompt)` | 시스템 프롬프트에 배경 지식 결합 |
| `chat_json(model, system, user, temperature)` | JSON 응답 LLM 호출 (입력 sanitize 포함) |
| `get_embeddings(texts, model, batch_size)` | 텍스트 임베딩 배치 생성 |

## 데모 페이지 (`app.py`)

```bash
# 로컬 실행
streamlit run app.py

# Docker 실행
docker build -t ask-sophie-demo .
docker run -d -p 8502:8501 --name sophie-demo ask-sophie-demo
```

- `output/` 디렉토리의 JSON 파일 기반 (Google Sheets 의존성 없음)
- 카테고리별 필터링 및 데이터 조회
- 레이블, 대표 질문, 답변 인라인 편집
- content_list 클릭 시 상품 텍스트 토글 표시 (product_data)
- 연관 추천(suggest) 표시
- JSON 다운로드

## Google Sheet

- 스프레드시트 ID: `19c8o63Lck04VWeOHyEXiEcYDBv92LcISR17xP7UZpfs`
- 인증: OAuth2 (`~/.config/gws/token.json`)
- 시트 목록: `merged_final`, `prepared_data`, `guide`, `qna_data`, `qna_group`, `product_data`
