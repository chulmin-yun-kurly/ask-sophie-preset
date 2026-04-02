import streamlit as st

st.set_page_config(page_title="Ask Sophie 대시보드", layout="wide")

pg = st.navigation(
    [
        st.Page("asdataview.py", title="QnA 그룹 관리", default=True),
        st.Page("asproductview.py", title="상품 데이터", url_path="product"),
    ],
)
pg.run()
