"""
상품 데이터 관리 페이지
"""
import streamlit as st
import json
import os

st.title("상품 데이터 관리")

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DASHBOARD_PATH = os.path.join(APP_DIR, 'dashboard.json')


# ── 데이터 로드 ──────────────────────────────────
@st.cache_data(ttl=120)
def load_data():
    with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    product_map = data.get('product_data', {})
    content_nm_map = data.get('content_map', {})

    # id → representative 매핑 (suggest 표시용)
    id_rep_map = {}
    for cat_data in data.get('categories', []):
        for group in cat_data.get('groups', []):
            gid = group.get('id', '')
            if gid:
                id_rep_map[gid] = group.get('representative', '')

    return product_map, content_nm_map, id_rep_map


# ── 상단 컨트롤 ──────────────────────────────────
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 2, 4])

with ctrl_col1:
    if st.button("새로고침"):
        st.cache_data.clear()
        st.rerun()

with ctrl_col2:
    search_query = st.text_input("상품 검색", placeholder="상품명 또는 상품번호", label_visibility="collapsed")

product_map, content_nm_map, id_rep_map = load_data()

# ── 요약 정보 ────────────────────────────────────
st.metric("총 상품 수", len(product_map))

# ── 필터링 ────────────────────────────────────────
filtered_items = []
for cno, product in product_map.items():
    nm = product.get('content_nm', '') or content_nm_map.get(cno, '')
    if search_query:
        query = search_query.lower()
        if query not in nm.lower() and query not in cno:
            continue
    filtered_items.append((cno, nm, product))

filtered_items.sort(key=lambda x: x[1])

if search_query:
    st.caption(f"검색 결과: {len(filtered_items)}개")

# ── 상품별 표시 ───────────────────────────────────
for cno, nm, product in filtered_items:
    label = f"{nm} ({cno})" if nm else cno

    with st.expander(label, expanded=False):
        # 상품 링크
        st.markdown(f"[상품 페이지 보기](https://www.kurly.com/goods/{cno})")

        # headline
        headline = product.get('headline', '')
        if headline:
            st.markdown("**헤드라인**")
            st.html(f'<div style="font-size:16px;font-weight:600;margin:4px 0 12px">{headline}</div>')

        # strengths
        strengths = product.get('strengths', '')
        if strengths:
            st.markdown("**특장점**")
            st.html(f'<div style="background:#f8f9fa;padding:12px 16px;border-radius:8px;margin:4px 0 12px;font-size:14px;line-height:1.7">{strengths}</div>')

        # stories
        stories = product.get('stories', '')
        if stories:
            st.markdown("**스토리**")
            st.html(f'<div style="background:#f8f9fa;padding:12px 16px;border-radius:8px;margin:4px 0 12px;font-size:14px;line-height:1.7">{stories}</div>')

        # targetUser
        target_user = product.get('targetUser', '')
        if target_user:
            st.markdown("**이런 분께 추천해요**")
            st.html(f'<div style="background:#f8f9fa;padding:12px 16px;border-radius:8px;margin:4px 0 12px;font-size:14px;line-height:1.7">{target_user}</div>')

        # suggest (연관 질문)
        suggest_list = product.get('suggest', [])
        if suggest_list:
            st.markdown("**연관 질문**")
            for sid in suggest_list:
                rep = id_rep_map.get(sid, '')
                st.markdown(f"- `{sid}` {rep}")
