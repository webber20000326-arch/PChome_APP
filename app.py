# -*- coding: utf-8 -*-
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="PChome 商品價格分析", page_icon="🛒", layout="wide")

API_URL = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
SORT_OPTIONS = {
    "銷量高到低 (sale/dc)": "sale/dc",
    "價格低到高 (prc/ac)": "prc/ac",
    "價格高到低 (prc/dc)": "prc/dc",
    "相關度 (rnk/dc)": "rnk/dc",
}
PRICE_BINS = [0, 300, 500, 1000, 2000, 5000, float("inf")]
PRICE_LABELS = ["300以下", "301-500", "501-1000", "1001-2000", "2001-5000", "5000以上"]


def fetch_pages(keyword: str, pages: int, sort: str, delay: float, progress=None) -> pd.DataFrame:
    """依頁數爬取 PChome 搜尋結果，回傳 DataFrame。"""
    frames = []
    for i in range(1, pages + 1):
        resp = requests.get(
            API_URL,
            params={"q": keyword, "page": i, "sort": sort},
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        prods = resp.json().get("prods", [])
        if not prods:  # 沒有更多資料就提前結束
            break
        frames.append(pd.DataFrame(prods))
        if progress is not None:
            progress.progress(i / pages, text=f"已完成第 {i} / {pages} 頁")
        if i < pages:
            time.sleep(delay)  # 避免請求過快
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


@st.cache_data(show_spinner=False, ttl=600)
def cached_fetch(keyword: str, pages: int, sort: str, delay: float) -> pd.DataFrame:
    return fetch_pages(keyword, pages, sort, delay)


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """整理欄位、價格區間與分類。"""
    out = df.copy()
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out = out.dropna(subset=["price"])
    out["價格區間"] = pd.cut(out["price"], bins=PRICE_BINS, labels=PRICE_LABELS, right=True)
    if "cateId" in out.columns:
        out["分類"] = out["cateId"].astype(str).str[:4]
    else:
        out["分類"] = "未分類"
    out["商品"] = out["name"].astype(str).str.slice(0, 15)
    return out.reset_index(drop=True)


# ---------------- UI ----------------
st.title("🛒 PChome 商品價格分析")
st.caption("輸入商品名稱與頁數，爬取 PChome 24h 搜尋結果並視覺化價格分布")

with st.sidebar:
    st.header("搜尋設定")
    keyword = st.text_input("產品名稱", value="行動電源")
    pages = st.number_input("爬取頁數", min_value=1, max_value=20, value=2, step=1)
    sort_label = st.selectbox("排序方式", list(SORT_OPTIONS.keys()))
    delay = st.slider("每頁間隔秒數", 0.0, 10.0, 2.0, 0.5)
    run = st.button("開始爬取", type="primary", use_container_width=True)

if run:
    if not keyword.strip():
        st.warning("請輸入產品名稱")
        st.stop()
    try:
        bar = st.progress(0.0, text="開始爬取…")
        raw = fetch_pages(keyword.strip(), int(pages), SORT_OPTIONS[sort_label], delay, bar)
        bar.empty()
    except requests.RequestException as e:
        st.error(f"請求失敗：{e}")
        st.stop()
    except ValueError:
        st.error("回傳內容不是有效的 JSON，可能被網站阻擋或網址已變更")
        st.stop()

    if raw.empty:
        st.info("查無資料，請換個關鍵字試試")
        st.stop()
    st.session_state["df"] = prepare(raw)
    st.session_state["keyword"] = keyword.strip()

if "df" in st.session_state:
    df = st.session_state["df"]
    kw = st.session_state["keyword"]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("商品數", f"{len(df):,}")
    c2.metric("平均價格", f"{df['price'].mean():,.0f}")
    c3.metric("最高價格", f"{df['price'].max():,.0f}")
    c4.metric("最低價格", f"{df['price'].min():,.0f}")

    tab_line, tab_pie, tab_sun, tab_data = st.tabs(["折線圖", "圓餅圖", "旭日圖", "資料表"])

    with tab_line:
        max_n = int(len(df))
        n = st.slider("顯示前幾筆", 1, max_n, min(70, max_n)) if max_n > 1 else 1
        sub = df.head(n).reset_index().rename(columns={"index": "序號"})
        fig = px.line(
            sub, x="序號", y="price", markers=True,
            hover_data=["name"], title=f"PChome「{kw}」商品售價",
            labels={"price": "價格"},
        )
        fig.add_hline(
            y=df["price"].mean(), line_dash="dash", line_color="red",
            annotation_text=f"平均 {df['price'].mean():,.0f}",
        )
        st.plotly_chart(fig, use_container_width=True)

    with tab_pie:
        pie_df = df["價格區間"].value_counts().reindex(PRICE_LABELS).dropna().reset_index()
        pie_df.columns = ["價格區間", "商品數"]
        fig = px.pie(pie_df, names="價格區間", values="商品數",
                     title=f"「{kw}」價格區間占比", hole=0.3)
        fig.update_traces(textinfo="percent+label")
        st.plotly_chart(fig, use_container_width=True)

    with tab_sun:
        depth = st.radio("旭日圖層級", ["價格區間 → 分類", "價格區間 → 分類 → 商品"], horizontal=True)
        path = ["價格區間", "分類"] if depth.count("→") == 1 else ["價格區間", "分類", "商品"]
        sun_df = df.assign(商品數=1)
        sun_df["價格區間"] = sun_df["價格區間"].astype(str)
        fig = px.sunburst(sun_df, path=path, values="商品數",
                          title=f"「{kw}」價格區間 / 分類結構")
        st.plotly_chart(fig, use_container_width=True)

    with tab_data:
        show_cols = [c for c in ["name", "price", "價格區間", "分類"] if c in df.columns]
        st.dataframe(df[show_cols], use_container_width=True)
        st.download_button(
            "下載 CSV",
            data=df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
            file_name=f"PCHOME_{kw}.csv",
            mime="text/csv",
        )
else:
    st.info("請在左側輸入產品名稱與頁數，按「開始爬取」")
