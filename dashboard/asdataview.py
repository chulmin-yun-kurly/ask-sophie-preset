"""
QnA 그룹 관리 데모 페이지
"""
import streamlit as st
import pandas as pd
import json
import os

st.title("QnA 그룹 관리")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_PATH = os.path.join(APP_DIR, 'dashboard.json')


# ── 데이터 로드 ──────────────────────────────────
@st.cache_data(ttl=120)
def load_data():
    with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    content_nm_map = data.get('content_map', {})
    product_map = data.get('product_data', {})

    rows = []
    cat_id_map = {}
    for cat_data in data['categories']:
        cat_id_map[cat_data['category']] = cat_data['category_id']
        for group in cat_data['groups']:
            rows.append({
                'id': group.get('id', ''),
                'category': cat_data['category'],
                'sub_group': group['sub_group'],
                'sub_group_label': group['sub_group_label'],
                'representative': group['representative'],
                'answer_intro': group.get('answer_intro', ''),
                'subtopics': json.dumps(group.get('subtopics', []), ensure_ascii=False),
                'answer_outro': group.get('answer_outro', ''),
                'search_keywords': json.dumps(group.get('search_keywords', []), ensure_ascii=False),
                'suggest': json.dumps(group.get('suggest', []), ensure_ascii=False),
                'question_count': group['question_count'],
                'content_count': group['content_count'],
                'question_list': json.dumps(group.get('questions', []), ensure_ascii=False),
                'content_list': json.dumps(group.get('content_list', []), ensure_ascii=False),
            })

    df = pd.DataFrame(rows)
    return df, cat_id_map, content_nm_map, product_map


# ── 상단 컨트롤: 새로고침 / JSON Import / 카테고리 필터 ──
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 2, 4])

with ctrl_col1:
    if st.button("새로고침"):
        st.cache_data.clear()
        st.rerun()

with ctrl_col2:
    uploaded = st.file_uploader("JSON Import", type=['json'], label_visibility="collapsed")
    if uploaded is not None:
        try:
            new_data = json.loads(uploaded.read().decode('utf-8'))
            if 'categories' not in new_data:
                st.error("유효하지 않은 JSON")
            else:
                with open(DASHBOARD_PATH, 'w', encoding='utf-8') as f:
                    json.dump(new_data, f, ensure_ascii=False, indent=2)
                st.success(f"Import 완료! ({len(new_data['categories'])}개 카테고리)")
                st.cache_data.clear()
                st.rerun()
        except json.JSONDecodeError:
            st.error("JSON 파싱 실패")

df, cat_id_map, content_nm_map, product_map = load_data()

# id → representative 매핑 (suggest 표시용)
id_rep_map = {}
for _, row in df.iterrows():
    gid = row.get('id', '')
    if gid:
        id_rep_map[gid] = row['representative']

categories = sorted(df['category'].unique().tolist(), key=lambda c: cat_id_map.get(c, 99))

with ctrl_col3:
    selected_cats = st.multiselect(
        "카테고리 선택",
        categories,
        default=categories,
        label_visibility="collapsed"
    )

filtered = df[df['category'].isin(selected_cats)].copy()

# ── 요약 정보 ────────────────────────────────────
col1, col2, col3 = st.columns(3)
col1.metric("카테고리", len(selected_cats))
col2.metric("그룹 수", len(filtered))
col3.metric("총 질문 수", filtered['question_count'].sum())

# ── 카테고리별 표시 ──────────────────────────────
for cat in selected_cats:
    cat_df = filtered[filtered['category'] == cat].copy()
    cat_id = cat_id_map.get(cat, '?')

    with st.expander(f"[{cat_id}] {cat} ({len(cat_df)}개 그룹, {cat_df['question_count'].sum()}개 질문)", expanded=False):
        # 편집 가능한 테이블
        display_cols = ['sub_group', 'sub_group_label', 'representative', 'answer_intro', 'search_keywords', 'question_count', 'content_count']
        for col in display_cols:
            if col not in cat_df.columns:
                cat_df[col] = ''

        st.data_editor(
            cat_df[display_cols],
            use_container_width=True,
            num_rows="dynamic",
            key=f"editor_{cat}",
            column_config={
                'sub_group': st.column_config.NumberColumn("그룹", width="small"),
                'sub_group_label': st.column_config.TextColumn("레이블", width="medium"),
                'representative': st.column_config.TextColumn("대표 질문", width="large"),
                'answer_intro': st.column_config.TextColumn("답변 요약", width="large"),
                'search_keywords': st.column_config.TextColumn("검색 키워드", width="medium"),
                'question_count': st.column_config.NumberColumn("질문수", width="small"),
                'content_count': st.column_config.NumberColumn("상품수", width="small"),
            }
        )

        # 상세 보기
        for idx, row in cat_df.iterrows():
            st.caption(f"**그룹 {row['sub_group']} [{row['sub_group_label']}]**")

            # 대표 질문
            st.markdown(f"**{row['representative']}**")

            # 질문 리스트
            questions = json.loads(row['question_list']) if isinstance(row['question_list'], str) else []
            if questions:
                for q in questions:
                    st.markdown(f"- {q}")

            # 답변 (answer_intro + subtopics + answer_outro)
            answer_intro = row.get('answer_intro', '')
            subtopics = json.loads(row['subtopics']) if isinstance(row.get('subtopics', ''), str) and row.get('subtopics') else []
            answer_outro = row.get('answer_outro', '')

            if answer_intro or subtopics or answer_outro:
                answer_parts = []
                if answer_intro:
                    answer_parts.append(answer_intro)
                for st_item in subtopics:
                    subtitle = st_item.get('subtitle', '')
                    desc = st_item.get('description', '')
                    if subtitle:
                        answer_parts.append(subtitle)
                    if desc:
                        answer_parts.append(desc)
                if answer_outro:
                    answer_parts.append(answer_outro)
                answer_html = ''.join(answer_parts)
                st.html(f'<div style="background:#f8f9fa;padding:12px 16px;border-radius:8px;margin:8px 0;font-size:14px;line-height:1.7">{answer_html}</div>')

            # content_list + 상품명 + URL + product 토글
            content_list = json.loads(row['content_list']) if isinstance(row.get('content_list', ''), str) and row.get('content_list') else []
            if content_list:
                for c in content_list:
                    cno = str(c).strip()
                    nm = content_nm_map.get(cno, '')
                    label = f"{nm} ({cno})" if nm else cno
                    product = product_map.get(cno)
                    st.markdown(f"- [{label}](https://www.kurly.com/goods/{cno})")
                    if product and st.toggle(f"상품 정보", key=f"product_{row['id']}_{cno}", value=False):
                        if product.get('headline'):
                            st.html(product['headline'])
                        if product.get('strengths'):
                            st.markdown("**특장점**")
                            st.html(product['strengths'])
                        if product.get('stories'):
                            st.markdown("**스토리**")
                            st.html(product['stories'])
                        if product.get('targetUser'):
                            st.markdown("**이런 분께 추천해요**")
                            st.html(product['targetUser'])
                        product_suggests = product.get('suggest', [])
                        if product_suggests:
                            st.markdown("**관련 질문**")
                            for sid in product_suggests:
                                rep = id_rep_map.get(sid, '')
                                st.markdown(f"- `{sid}` {rep}")
                        st.markdown("---")

            # suggest (연관 추천)
            suggest_list = json.loads(row['suggest']) if isinstance(row.get('suggest', ''), str) and row.get('suggest') else []
            if suggest_list:
                st.markdown("**연관 추천**")
                for sid in suggest_list:
                    rep = id_rep_map.get(sid, '')
                    st.markdown(f"- `{sid}` {rep}")

            st.divider()

# ── 하단: JSON 다운로드 ──────────────────────────
st.markdown("---")
with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
    json_str = f.read()

st.download_button(
    "JSON 내보내기",
    json_str,
    "dashboard.json",
    "application/json",
    use_container_width=True
)
