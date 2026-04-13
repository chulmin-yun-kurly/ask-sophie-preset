# AI Agent Q&A 스키마 명세서

---

## 1. ai_agent_question

질문 데이터를 관리하는 컬렉션입니다. 검색 키워드 또는 상품번호 기반으로 진입 질문과 후속 질문을 구성합니다.

### 1.1 필드 정의

| 필드 | 필수 여부 | 타입 | 설명 |
|------|-----------|------|------|
| `_id` | O | ObjectId | PK |
| `keyword` | X | String | 질문 노출 검색어 |
| `productNo` | X | Long | 상품번호 |
| `isEntry` | O | Boolean | 진입 섹션 노출 여부 |
| `content` | O | Object | 질문 콘텐츠 |
| `content.answerType` | O | String | 답변 유형 (`RECOMMEND`, `COMPARE`, `INFO`, `SUMMARY`) |
| `content.category` | O | String | 질문 분류 (컬리특화, 페어링 등) |
| `content.representative` | O | String | 대표 질문 |
| `content.relatedQuestions` | X | String[] | 유사 질문 목록 (랜덤으로 사용 가능) |
| `isActive` | X (default: `false`) | Boolean | 활성 여부 |
| `createdAt` | X | Date | 생성일시 |
| `updatedAt` | X | Date | 수정일시 |
| `createdBy` | X | String | 생성자 |
| `updatedBy` | X | String | 수정자 |

### 1.2 answerType 값

| 값 | 설명 |
|----|------|
| `RECOMMEND` | 상품 추천 |
| `COMPARE` | 상품 비교 |
| `INFO` | 정보 제공 |
| `SUMMARY` | 상품 요약 |

### 1.3 예시 데이터

```json
{
  "_id": "q1",
  "keyword": "올리브 오일",
  "isEntry": true,
  "isActive": false,
  "content": {
    "category": "KURLY",
    "representative": "올리브오일 추천해줘",
    "relatedQuestions": ["좋은 올리브오일 알려줘", "올리브오일 어떤 거 사야 해?"]
  }
}
```

```json
{
  "_id": "q2",
  "keyword": "올리브 오일",
  "isEntry": false,
  "isActive": false,
  "content": {
    "category": "PAIRING",
    "representative": "올리브오일 종류별 차이 알려줘",
    "relatedQuestions": ["엑스트라버진이랑 퓨어 올리브오일 차이가 뭐야?"]
  }
}
```

```json
{
  "_id": "q3",
  "keyword": "올리브 오일",
  "isEntry": false,
  "isActive": false,
  "content": {
    "category": "INFO",
    "representative": "올리브오일 산도가 뭐야?",
    "relatedQuestions": ["산도를 왜 봐야 돼?", "올리브오일 산도 기준 알려줘"]
  }
}
```

```json
{
  "_id": "q4",
  "productNo": 520123,
  "isEntry": false,
  "isActive": false,
  "content": {
    "category": "INFO",
    "representative": "이 상품에 대해 알려줘",
    "relatedQuestions": []
  }
}
```

---

## 2. ai_agent_answer

질문에 대한 답변 데이터를 관리하는 컬렉션입니다. 하나의 질문에 여러 가지 답변 변형(variation)을 가질 수 있으며, 그 중 하나를 택해 응답합니다.

### 2.1 필드 정의

| 필드 | 필수 여부 | 타입 | 설명 |
|------|-----------|------|------|
| `_id` | O | ObjectId | PK |
| `questionId` | O | ObjectId | `ai_agent_question` 참조값 |
| `answers` | O | Object[] | 질문에 가능한 여러 가지 답변 (택1로 응답) |
| `answers[].content` | O | Object[] | 답변 컴포넌트 리스트. `{"type": String, "data": Object}` 형태 |
| `isActive` | X (default: `false`) | Boolean | 활성 여부 |
| `createdAt` | X | Date | 생성일시 |
| `updatedAt` | X | Date | 수정일시 |
| `createdBy` | X | String | 생성자 |
| `updatedBy` | X | String | 수정자 |

### 2.2 답변 컴포넌트 (content type)

답변은 다양한 컴포넌트를 조합하여 구성됩니다.

| type | data 타입 | 설명 |
|------|-----------|------|
| `intro` | String | 도입부 텍스트 |
| `outro` | String | 마무리 텍스트 |
| `headline` | String | 헤드라인 |
| `title` | String | 소제목 (`#` 마크다운 형식) |
| `description` | String | 설명 텍스트 |
| `productNos` | Long[] | 상품번호 목록 |
| `comparison` | Object | 비교 테이블 (`headers`, `rows`) |
| `bulletList` | String[] | 불릿 리스트 |
| `suggestions` | Object | 후속 질문 ID 목록 (`{keyword: String[], product: String[]}`) |

### 2.3 컴포넌트별 상세 및 예시

#### intro

```json
{"type": "intro", "data": "컬리에는 MD가 산지를 직접 방문하고 시식해서 고른 올리브오일이 있어요."}
```

#### outro

```json
{"type": "outro", "data": "처음이라면 파미고로 시작해보시고, 올리브오일 맛에 눈을 뜨셨다면 핀카듀에르나스를 경험해보세요."}
```

#### headline

```json
{"type": "headline", "data": "추천상품"}
```

#### title

```json
{"type": "title", "data": "# 매일 한 스푼, 건강하게 드시려는 분에게"}
```

#### description

```json
{"type": "description", "data": "쓴맛이 적고 부드러워서 공복에 그냥 마시거나 요거트에 뿌리기 좋아요."}
```

#### productNos

```json
{"type": "productNos", "data": [5049154]}
```

#### comparison

```json
{
  "type": "comparison",
  "data": {
    "headers": ["", "엑스트라버진", "퓨어"],
    "rows": [
      {"label": "산도", "values": ["0.8% 이하", "1.5% 이하"]},
      {"label": "착유 방식", "values": ["냉압착", "정제 혼합"]},
      {"label": "적합 용도", "values": ["생식·피니시", "가열 요리"]}
    ]
  }
}
```

#### bulletList

```json
{
  "type": "bulletList",
  "data": [
    "🕐 수확 2시간 내 착유 — 갓 딴 올리브를 바로 오일로 만들어 신선함이 차원이 달라요",
    "🏅 산도 0.3% 미만 · 폴리페놀 400mg↑ — 숫자가 곧 품질 증명. 국제 인증 SIQEV까지 획득했어요.",
    "🇪🇸 컬리 단독 항공수입 — MD가 스페인 농장을 직접 답사하고 가져온, 오직 컬리에서만 만날 수 있는 오일이에요."
  ]
}
```

#### suggestions

```json
{
  "type": "suggestions",
  "data": {
    "keyword": ["q2", "q3"],
    "product": ["pq_5049153", "pqq_5049153_1"]
  }
}
```

- `keyword`: 키워드(qna_group, compare 등) 후속 질문 ID 목록.
- `product`: 상품 관련 후속 질문 ID 목록 (`pq_*`, `pqq_*`).
- 분류된 항목이 없으면 빈 리스트(`[]`).

---

## 3. answerType별 답변 예시

### 3.1 RECOMMEND (상품 추천)

```json
{
  "_id": "a1",
  "questionId": "q1",
  "isActive": false,
  "answers": [
    {
      "content": [
        {"type": "intro", "data": "컬리에는 MD가 산지를 직접 방문하고 시식해서 고른 올리브오일이 있어요. 어떤 용도로 쓰실지에 따라 추천해드릴게요."},
        {"type": "title", "data": "# 매일 한 스푼, 건강하게 드시려는 분에게"},
        {"type": "description", "data": "쓴맛이 적고 부드러워서 공복에 그냥 마시거나 요거트에 뿌리기 좋아요."},
        {"type": "productNos", "data": [5049153, 5045208]},
        {"type": "title", "data": "# 요리 마무리에 특별한 풍미를 더하고 싶은 분에게"},
        {"type": "description", "data": "수확 직후 빠르게 착유해서 신선한 아로마가 살아있어요. 샐러드, 파스타 피니싱에 뿌리면 요리가 달라집니다."},
        {"type": "productNos", "data": [5049154]},
        {"type": "outro", "data": "처음이라면 파미고로 시작해보시고, 올리브오일 맛에 눈을 뜨셨다면 핀카듀에르나스를 경험해보세요."},
        {"type": "suggestions", "data": {"keyword": ["q2", "q3"], "product": []}}
      ]
    }
  ]
}
```

### 3.2 COMPARE (상품 비교)

```json
{
  "_id": "a1",
  "questionId": "q1",
  "isActive": false,
  "answers": [
    {
      "content": [
        {"type": "intro", "data": "올리브오일은 등급과 착유 방식에 따라 맛과 용도가 달라요."},
        {"type": "title", "data": "# 어떤 차이가 있을까요?"},
        {"type": "description", "data": "엑스트라버진은 산도 0.8% 이하의 최고 등급이에요. 생식이나 피니시 오일로 적합해요."},
        {
          "type": "comparison",
          "data": {
            "headers": ["", "엑스트라버진", "퓨어"],
            "rows": [
              {"label": "산도", "values": ["0.8% 이하", "1.5% 이하"]},
              {"label": "착유 방식", "values": ["냉압착", "정제 혼합"]},
              {"label": "적합 용도", "values": ["생식·피니시", "가열 요리"]}
            ]
          }
        },
        {"type": "description", "data": "가열 요리가 목적이라면 퓨어, 샐러드나 빵에 찍어 먹는다면 엑스트라버진을 선택하세요."},
        {"type": "productNos", "data": [5049153, 5045209]},
        {"type": "outro", "data": "용도에 맞는 올리브오일을 고르면 요리의 완성도가 달라져요."},
        {"type": "suggestions", "data": {"keyword": ["q1", "q3"], "product": []}}
      ]
    }
  ]
}
```

### 3.3 INFO (정보 제공)

```json
{
  "_id": "a3",
  "questionId": "q3",
  "isActive": false,
  "answers": [
    {
      "content": [
        {"type": "intro", "data": "올리브오일 품질을 판단하는 핵심 지표예요."},
        {"type": "title", "data": "# 산도란?"},
        {"type": "description", "data": "산도는 올리브오일 속 유리지방산 함량을 나타내요. 낮을수록 신선하고 품질이 높아요.\n* 엑스트라버진: 0.8% 이하\n* 버진: 2.0% 이하\n* 퓨어: 정제유 혼합으로 기준 상이"},
        {"type": "outro", "data": "산도와 수확 연도, 두 가지만 확인해도 좋은 올리브오일을 고를 수 있어요."},
        {"type": "suggestions", "data": {"keyword": ["q1", "q2"], "product": []}}
      ]
    }
  ]
}
```

### 3.4 SUMMARY (상품 요약)

```json
{
  "_id": "a4",
  "questionId": "q4",
  "isActive": false,
  "answers": [
    {
      "content": [
        {"type": "headline", "data": "# 200년 농장의 첫 수확, 딱 한 번"},
        {"type": "productNos", "data": [5049153]},
        {"type": "title", "data": "# 특장점"},
        {
          "type": "bulletList",
          "data": [
            "🕐 수확 2시간 내 착유 — 갓 딴 올리브를 바로 오일로 만들어 신선함이 차원이 달라요",
            "🏅 산도 0.3% 미만 · 폴리페놀 400mg↑ — 숫자가 곧 품질 증명. 국제 인증 SIQEV까지 획득했어요.",
            "🇪🇸 컬리 단독 항공수입 — MD가 스페인 농장을 직접 답사하고 가져온, 오직 컬리에서만 만날 수 있는 오일이에요."
          ]
        },
        {"type": "title", "data": "# 스토리"},
        {"type": "description", "data": "1828년부터 4대째 올리브를 키워온 스페인 코르도바의 핀카 듀에르나스 농장. 수령 50년 이상 나무에서 2025년 가장 먼저 딴 퍼스트 하비스트 올리브만 골라 한정 수량으로 만들었어요."},
        {"type": "title", "data": "# 이런 분께 추천해요"},
        {
          "type": "bulletList",
          "data": [
            "올리브오일로 아침 한 스푼 습관을 시작하고 싶은 분",
            "산도·폴리페놀 스펙이 명확한 프리미엄 오일을 찾는 분",
            "샐러드·요거트에 뿌려 먹는 피니시 오일을 찾는 분"
          ]
        },
        {"type": "suggestions", "data": {"keyword": ["q2"], "product": ["pqq_5049153_1", "pqq_5049153_2"]}}
      ]
    }
  ]
}
```
