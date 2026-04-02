# BE WIP - ask sophie beta

---

## ai_agent_question

| 필드 | 필수여부 | 타입 | 설명 |
|------|----------|------|------|
| `_id` | O | `ObjectId` | PK |
| `keyword` | X | `String` | 질문노출 검색어 |
| `productNo` | X | `Long` | 상품번호 |
| `isEntry` | O | `Boolean` | 진입 섹션 노출 여부 |
| `content` | O | `Object` | |
| `content.answerType` | O | `String` | `RECOMMEND` 상품 추천 / `COMPARE` 상품비교 / `INFO` 정보제공 / `SUMMARY` 상품요약 |
| `content.category` | O | `String` | 질문 분류 (컬리특화, 페어링 `PAIRING`, ..) |
| `content.representative` | O | `String` | 대표 질문 |
| `content.relatedQuestions` | X | `String[]` | 유사 질문 목록 (랜덤으로 사용가능) |
| `isActive` | X (default: `false`) | `Boolean` | 활성 여부 |
| `createdAt` | X | `Date` | |
| `updatedAt` | X | `Date` | |
| `createdBy` | X | `String` | |
| `updatedBy` | X | `String` | |

### Example

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
  "productNo": "520123",
  "isEntry": false,
  "isActive": false,
  "content": {
    "category": "..",
    "representative": "이 상품에 대해 알려줘",
    "relatedQuestions": []
  }
}
```

---

## ai_agent_answer

| 필드 | 필수여부 | 타입 | 설명 |
|------|----------|------|------|
| `_id` | O | `ObjectId` | PK |
| `questionId` | O | `ObjectId` | `ai_agent_question` 참조값 |
| `content` | O | `Object[]` | 답변 컴포넌트 리스트 |
| \|--- | | `{"type": String, "data": Object}` 형태 | type 종류: `intro`, `outro`, `headline`, `title`, `description`, `productNos`, `comparison`, `suggestions` |
| `isActive` | X (default: `false`) | `Boolean` | 활성 여부 |
| `createdAt` | X | `Date` | |
| `updatedAt` | X | `Date` | |
| `createdBy` | X | `String` | |
| `updatedBy` | X | `String` | |

---

### 답변 content 종류

| type | data 타입 | 예시 |
|------|-----------|------|
| `intro` | `String` | `{"type": "intro", "data": "컬리에는 MD가 산지를 직접 방문하고 시식해서 고른 올리브오일이 있어요. 어떤 용도로 쓰실지에 따라 추천해드릴게요."}` |
| `outro` | `String` | `{"type": "outro", "data": "처음이라면 파미고로 시작해보시고, 올리브오일 맛에 눈을 뜨셨다면 핀카듀에르나스를 경험해보세요."}` |
| `headline` | `String` | `{"type": "headline", "data": "추천상품"}` |
| `title` | `String` | `{"type": "title", "data": "# 매일 한 스푼, 건강하게 드시려는 분에게"}` |
| `description` | `String` | `{"type": "description", "data": "쓴맛이 적고 부드러워서 공복에 그냥 마시거나 요거트에 뿌리기 좋아요."}` |
| `productNos` | `Long[]` | `{"type": "productNos", "data": [5049154]}` |
| `comparison` | `Object` | 아래 참조 |
| `suggestions` | `String[]` | `{"type": "suggestions", "data": ["q2", "q3"]}` |

#### comparison 상세 구조

```json
{
  "type": "comparison",
  "data": {
    "headers": ["", "엑스트라버진", "퓨어"],
    "rows": [
      { "label": "산도", "values": ["0.8% 이하", "1.5% 이하"] },
      { "label": "착유 방식", "values": ["냉압착", "정제 혼합"] },
      { "label": "적합 용도", "values": ["생식·피니시", "가열 요리"] }
    ]
  }
}
```

---

### Example

#### RECOMMEND (상품 추천)

> ![RECOMMEND UI](image-20260331-022859.png)

```json
{
  "_id": "a1",
  "questionId": "q1",
  "isActive": false,
  "content": [
    {"type": "intro", "data": "컬리에는 MD가 산지를 직접 방문하고 시식해서 고른 올리브오일이 있어요. 어떤 용도로 쓰실지에 따라 추천해드릴게요."},
    {"type": "title", "data": "# 매일 한 스푼, 건강하게 드시려는 분에게"},
    {"type": "description", "data": "쓴맛이 적고 부드러워서 공복에 그냥 마시거나 요거트에 뿌리기 좋아요."},
    {"type": "productNos", "data": ["5049153", "5045208"]},
    {"type": "title", "data": "# 요리 마무리에 특별한 풍미를 더하고 싶은 분에게"},
    {"type": "description", "data": "수확 직후 빠르게 착유해서 신선한 아로마가 살아있어요. 샐러드, 파스타 피니싱에 뿌리면 요리가 달라집니다."},
    {"type": "productNos", "data": ["5049154"]},
    {"type": "outro", "data": "처음이라면 파미고로 시작해보시고, 올리브오일 맛에 눈을 뜨셨다면 핀카듀에르나스를 경험해보세요."},
    {"type": "suggestions", "data": ["q2", "q3"]}
  ]
}
```

---

#### COMPARE (상품비교)

> ![COMPARE UI](image-20260331-022951.png)

```json
{
  "_id": "a1",
  "questionId": "q1",
  "isActive": false,
  "content": [
    {"type": "intro", "data": "올리브오일은 등급과 착유 방식에 따라 맛과 용도가 달라요."},
    {"type": "title", "data": "# 어떤 차이가 있을까요?"},
    {"type": "description", "data": "엑스트라버진은 산도 0.8% 이하의 최고 등급이에요. 생식이나 피니시 오일로 적합해요."},
    {"type": "comparison", "data": {"headers": ["", "엑스트라버진", "퓨어"], "rows": [{"label": "산도", "values": ["0.8% 이하", "1.5% 이하"]}, {"label": "착유 방식", "values": ["냉압착", "정제 혼합"]}, {"label": "적합 용도", "values": ["생식·피니시", "가열 요리"]}]}},
    {"type": "description", "data": "가열 요리가 목적이라면 퓨어, 샐러드나 빵에 찍어 먹는다면 엑스트라버진을 선택하세요."},
    {"type": "productNos", "data": ["5049153", "5045209"]},
    {"type": "outro", "data": "용도에 맞는 올리브오일을 고르면 요리의 완성도가 달라져요."},
    {"type": "suggestions", "data": ["q1", "q3"]}
  ]
}
```

---

#### INFO (정보제공)

> ![INFO UI](image-20260331-022930.png)

```json
{
  "_id": "a3",
  "questionId": "q3",
  "isActive": false,
  "content": [
    {"type": "intro", "data": "올리브오일 품질을 판단하는 핵심 지표예요."},
    {"type": "title", "data": "# 산도란?"},
    {"type": "description", "data": "산도는 올리브오일 속 유리지방산 함량을 나타내요. 낮을수록 신선하고 품질이 높아요.\n* 엑스트라버진: 0.8% 이하\n* 버진: 2.0% 이하\n* 퓨어: 정제유 혼합으로 기준 상이"},
    {"type": "outro", "data": "산도와 수확 연도, 두 가지만 확인해도 좋은 올리브오일을 고를 수 있어요."},
    {"type": "suggestions", "data": ["q1", "q2"]}
  ]
}
```

---

#### SUMMARY (상품요약)

> ![SUMMARY UI](image-20260331-022916.png)

```json
{
  "_id": "a4",
  "questionId": "q4",
  "isActive": false,
  "content": [
    {"type": "intro", "data": null},
    {"type": "headline", "data": "# 200년 농장의 첫 수확, 딱 한 번"},
    {"type": "productNos", "data": ["5049153"]},
    {"type": "title", "data": "# 특장점"},
    {"type": "description", "data": "🕐 수확 2시간 내 착유 — 갓 딴 올리브를 바로 오일로 만들어 신선함이 차원이 달라요\n🏅 산도 0.3% 미만 · 폴리페놀 400mg↑ — 숫자가 곧 품질 증명. 국제 인증 SIQEV까지 획득했어요\n🇪🇸 컬리 단독 항공수입 — MD가 스페인 농장을 직접 답사하고 가져온, 오직 컬리에서만 만날 수 있는 오일이에요"},
    {"type": "title", "data": "# 스토리"},
    {"type": "description", "data": "1828년부터 4대째 올리브를 키워온 스페인 코르도바의 핀카 듀에르나스 농장. 수령 50년 이상 나무에서 2025년 가장 먼저 딴 퍼스트 하비스트 올리브만 골라 한정 수량으로 만들었어요."},
    {"type": "title", "data": "# 이런 분께 추천해요"},
    {"type": "description", "data": "- 올리브오일로 아침 한 스푼 습관을 시작하고 싶은 분\n- 산도·폴리페놀 스펙이 명확한 프리미엄 오일을 찾는 분\n- 샐러드·요거트에 뿌려 먹는 피니시 오일을 찾는 분"},
    {"type": "outro", "data": null},
    {"type": "suggestions", "data": ["q1", "q3"]}
  ]
}
```
