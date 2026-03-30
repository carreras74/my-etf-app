from __future__ import annotations

import datetime as dt
import io
import json
import re
import urllib.parse
from typing import Optional

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytz
import streamlit as st
from google.oauth2.service_account import Credentials
from plotly.subplots import make_subplots

st.set_page_config(page_title="ETF 전종목 비중 추적", layout="wide")

st.markdown(
    """
<style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    h1, h2, h3, h4, h5, h6, p, div, span { color: #E0E0E0 !important; }
    .streamlit-expanderHeader { background-color: #1E1E1E !important; color: #FFFFFF !important; }
    .streamlit-expanderContent { background-color: #121212 !important; }
</style>
""",
    unsafe_allow_html=True,
)

st.title("📈 ETF 종목별 순위 변동 추이 (범프 차트)")

SPREADSHEET_ID = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TIME_SHEET_NAMES = {
    "코스닥액티브",
    "플러스배당액티브",
    "코스피액티브",
    "밸류업액티브",
    "신재생에너지액티브",
    "바이오액티브",
    "이노베이션액티브",
    "컬처액티브",
}
KOACT_SHEET_NAMES = {
    "배당성장액티브",
    "수소전력ESS인프라액티브",
    "바이오헬스케어액티브",
    "코리아밸류업액티브",
    "K수출핵심기업TOP30액티브",
    "AI인프라액티브",
    "반도체2차전지핵심소재액티브",
    # 주의: '코스닥액티브'는 TIME에도 있어 시트명이 브랜드 없이 저장되면 구분이 불가능합니다.
}
TIGER_SHEET_NAMES = {
    "TIGER 기술이전바이오액티브",
    "TIGER 코리아테크액티브",
    "TIGER 퓨처모빌리티액티브",
}
AMBIGUOUS_SHEET_NAMES = {"코스닥액티브"}


# =====================================================================
# 공통 유틸
# =====================================================================
def get_secret_json() -> dict:
    candidates = ["google_key", "GOOGLE_KEY"]
    for key in candidates:
        if key in st.secrets:
            raw = st.secrets[key]
            if isinstance(raw, dict):
                return dict(raw)
            if isinstance(raw, str) and raw.strip():
                return json.loads(raw)
    raise KeyError("st.secrets 에 google_key 또는 GOOGLE_KEY 가 없습니다.")


@st.cache_resource
def get_gspread_client() -> gspread.Client:
    creds_dict = get_secret_json()
    credentials = Credentials.from_service_account_info(creds_dict, scopes=GOOGLE_SCOPES)
    return gspread.authorize(credentials)


@st.cache_data(ttl=7200)
def load_data_from_google() -> dict[str, pd.DataFrame]:
    client = get_gspread_client()
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    results: dict[str, pd.DataFrame] = {}

    for ws in spreadsheet.worksheets():
        records = ws.get_all_records()
        if not records:
            continue
        results[ws.title] = pd.DataFrame(records)

    return results


@st.cache_data(ttl=600)
def load_ledger_data() -> pd.DataFrame:
    github_id = "carreras74"
    repo_name = "ETF_Auto_Bot"
    base_url = f"https://raw.githubusercontent.com/{github_id}/{repo_name}/main/"
    safe_ledger_name = urllib.parse.quote("매입장부.xlsx")
    ledger_url = f"{base_url}{safe_ledger_name}"

    try:
        return pd.read_excel(ledger_url)
    except Exception:
        return pd.DataFrame()


def parse_change_cell(value) -> dict:
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return {"qty_change": 0, "price": np.nan, "current_qty": np.nan, "raw": ""}

    qty_change = 0
    if "🔴▲" in text:
        match = re.search(r"🔴▲\s*([\d,]+)", text)
        if match:
            qty_change = int(match.group(1).replace(",", ""))
    elif "🔵▼" in text:
        match = re.search(r"🔵▼\s*([\d,]+)", text)
        if match:
            qty_change = -int(match.group(1).replace(",", ""))

    price_match = re.search(r"₩([\d,]+)", text)
    price = int(price_match.group(1).replace(",", "")) if price_match else np.nan

    current_qty_match = re.search(r"\|\s*Q([\d,]+)", text)
    current_qty = int(current_qty_match.group(1).replace(",", "")) if current_qty_match else np.nan

    return {
        "qty_change": qty_change,
        "price": price,
        "current_qty": current_qty,
        "raw": text,
    }


def normalize_etf_frames(raw_data: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], list[str]]:
    normalized: dict[str, pd.DataFrame] = {}
    latest_dates: list[pd.Timestamp] = []
    all_stocks: set[str] = set()

    for etf_name, df in raw_data.items():
        if df.empty or len(df.columns) == 0:
            continue

        work_df = df.copy()
        date_col = work_df.columns[0]
        work_df[date_col] = pd.to_datetime(work_df[date_col], errors="coerce")
        work_df = work_df.dropna(subset=[date_col]).sort_values(by=date_col)
        if work_df.empty:
            continue

        latest_dates.append(work_df[date_col].max())

        for col in work_df.columns[1:]:
            if not str(col).endswith("_증감"):
                all_stocks.add(str(col))

        work_df = work_df.tail(20).copy()
        work_df[date_col] = work_df[date_col].dt.strftime("%Y-%m-%d")
        normalized[etf_name] = work_df

    return normalized, latest_dates, sorted(all_stocks)


def resolve_brand(etf_name: str) -> Optional[str]:
    if etf_name in AMBIGUOUS_SHEET_NAMES:
        return None
    if etf_name in TIGER_SHEET_NAMES or etf_name.startswith("TIGER"):
        return "TIGER"
    if etf_name in TIME_SHEET_NAMES:
        return "TIME"
    if etf_name in KOACT_SHEET_NAMES or etf_name.startswith("KoAct"):
        return "KoAct"
    return None


def build_template_file() -> bytes:
    output = io.BytesIO()
    pd.DataFrame(
        [["삼성전자", "2024-03-26", "75000"]],
        columns=["종목명", "매수일자", "매수단가"],
    ).to_excel(output, index=False)
    return output.getvalue()


# =====================================================================
# 데이터 로딩
# =====================================================================
try:
    raw_etf_data = load_data_from_google()
except Exception as exc:
    if "429" in str(exc):
        st.error("⚠️ 구글 시트 API 트래픽 초과입니다. 잠시 후 새로고침해 주세요.")
    else:
        st.error(f"데이터 로드 실패: {exc}")
    st.stop()

etf_data, latest_dates_in_db, all_stocks_list = normalize_etf_frames(raw_etf_data)
if not etf_data:
    st.warning("데이터를 정상적으로 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()

base_ledger_df = load_ledger_data()

kst = pytz.timezone("Asia/Seoul")
today_kst = dt.datetime.now(kst).date()

if latest_dates_in_db:
    overall_latest_date = max(latest_dates_in_db).date()
    if overall_latest_date < today_kst and today_kst.weekday() < 5:
        st.warning(
            f"⚠️ 오늘({today_kst.strftime('%m월 %d일')}) 데이터가 아직 반영되지 않았습니다. "
            f"현재는 {overall_latest_date.strftime('%m월 %d일')}까지의 데이터를 표시합니다."
        )
    elif overall_latest_date == today_kst:
        st.success(f"✅ 오늘({today_kst.strftime('%m월 %d일')}) 최신 데이터가 반영되었습니다!")

ambiguous_existing = [name for name in etf_data.keys() if name in AMBIGUOUS_SHEET_NAMES]
if ambiguous_existing:
    st.info(
        "ℹ️ 현재 시트명만으로는 일부 ETF 운용사 구분이 불가능합니다. "
        f"특히 {', '.join(ambiguous_existing)} 는 TIME/KoAct가 겹칠 수 있어 통합 수급 집계에서 제외됩니다."
    )


# =====================================================================
# 차트 함수
# =====================================================================
def render_stock_3d_chart(stock_name: str, etf_frames: dict[str, pd.DataFrame], ledger_df: pd.DataFrame, unique_key: str) -> None:
    buy_date = None
    buy_price = None

    if not ledger_df.empty and {"종목명", "매수일자", "매수단가"}.issubset(ledger_df.columns):
        row_data = ledger_df[ledger_df["종목명"] == stock_name]
        if not row_data.empty:
            buy_date_val = row_data.iloc[0].get("매수일자")
            buy_price_val = row_data.iloc[0].get("매수단가")
            if pd.notna(buy_date_val):
                buy_date = pd.to_datetime(buy_date_val, errors="coerce")
                if pd.notna(buy_date):
                    buy_date = buy_date.strftime("%m-%d")
            if pd.notna(buy_price_val):
                if isinstance(buy_price_val, str):
                    buy_price_val = buy_price_val.replace(",", "").replace("원", "").strip()
                try:
                    buy_price = float(buy_price_val)
                except Exception:
                    buy_price = None

    best_etf = None
    max_weight = -1.0
    for etf_name, df in etf_frames.items():
        if stock_name not in df.columns:
            continue
        weight_series = pd.to_numeric(df[stock_name], errors="coerce")
        if weight_series.notna().any():
            candidate = float(weight_series.max())
            if candidate > max_weight:
                max_weight = candidate
                best_etf = etf_name

    if not best_etf:
        st.warning(f"'{stock_name}' 종목은 현재 추적 중인 ETF에 존재하지 않습니다.")
        return

    aggregated: dict[str, dict] = {}
    for etf_name, df in etf_frames.items():
        if stock_name not in df.columns:
            continue

        date_col = df.columns[0]
        diff_col = f"{stock_name}_증감"

        for _, row in df.iterrows():
            date_str = str(row[date_col]).strip()
            aggregated.setdefault(
                date_str,
                {"Weight": 0.0, "Price": np.nan, "QtyChange": 0, "AmtChange": 0.0},
            )

            if etf_name == best_etf:
                weight = pd.to_numeric(row[stock_name], errors="coerce")
                aggregated[date_str]["Weight"] = float(weight) if pd.notna(weight) else 0.0

            parsed = parse_change_cell(row[diff_col]) if diff_col in df.columns else {"qty_change": 0, "price": np.nan}
            qty_change = parsed["qty_change"]
            price = parsed["price"]

            if pd.notna(price):
                aggregated[date_str]["Price"] = price
            aggregated[date_str]["QtyChange"] += qty_change
            if pd.notna(price):
                aggregated[date_str]["AmtChange"] += (qty_change * float(price)) / 1_000_000.0

    p_df = pd.DataFrame(
        [
            {
                "Date": key,
                "Weight": value["Weight"],
                "Price": value["Price"],
                "QtyChange": value["QtyChange"],
                "AmtChange": value["AmtChange"],
            }
            for key, value in aggregated.items()
        ]
    )

    if p_df.empty:
        return

    p_df["DateObj"] = pd.to_datetime(p_df["Date"], errors="coerce")
    p_df = p_df.dropna(subset=["DateObj"]).sort_values("DateObj")
    p_df["Date"] = p_df["DateObj"].dt.strftime("%m-%d")
    p_df = p_df.drop(columns=["DateObj"])
    p_df["Price"] = p_df["Price"].ffill().bfill()
    p_df["AmtChange"] = p_df["AmtChange"].round(1)
    valid_p_df = p_df.dropna(subset=["Price"])

    st.subheader(f"📊 {stock_name} 정밀 분석 (1층: 주가&비중 / 2층: 매수금액&수량)")

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.6, 0.4],
        specs=[[{"secondary_y": True}], [{"secondary_y": True}]],
    )

    fig.update_xaxes(type="category")
    fig.add_trace(
        go.Bar(
            x=p_df["Date"],
            y=p_df["Weight"],
            name=f"{best_etf} 비중(%)",
            opacity=0.3,
            marker_color="#82B1FF",
            width=0.35,
            hovertemplate="%{x}<br>비중: %{y:.2f}%<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=valid_p_df["Date"],
            y=valid_p_df["Price"],
            name="주가(원)",
            mode="lines+markers",
            line=dict(color="#FFCA28", width=3),
            marker=dict(size=6, color="#FFCA28"),
            hovertemplate="%{x}<br>주가: %{y:,.0f}원<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    colors = ["#FF5252" if q > 0 else "#448AFF" if q < 0 else "#555555" for q in p_df["QtyChange"]]
    text_amt = p_df["AmtChange"].apply(lambda x: f"{x:,.1f}M" if x != 0 else "")

    fig.add_trace(
        go.Bar(
            x=p_df["Date"],
            y=p_df["AmtChange"],
            name="순매수 금액(백만)",
            marker_color=colors,
            width=0.35,
            offsetgroup=1,
            customdata=p_df["QtyChange"],
            text=text_amt,
            textposition="outside",
            textfont=dict(color="white", size=10),
            hovertemplate="%{x}<br>순매수: %{y:,.1f} 백만원<br>수량: %{customdata:,.0f} 주<extra></extra>",
        ),
        row=2,
        col=1,
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(
            x=p_df["Date"],
            y=p_df["QtyChange"],
            name="수량 증감(주)",
            marker_color=colors,
            width=0.35,
            offsetgroup=2,
            opacity=0.7,
            hoverinfo="skip",
        ),
        row=2,
        col=1,
        secondary_y=True,
    )

    if not p_df.empty:
        if buy_price is not None:
            fig.add_trace(
                go.Scatter(
                    x=[p_df["Date"].iloc[0], p_df["Date"].iloc[-1]],
                    y=[buy_price, buy_price],
                    mode="lines+text",
                    line=dict(color="#00E676", dash="dash", width=2),
                    name=f"내 평단가 ({buy_price:,.0f}원)",
                    text=[f"매수단가 ({buy_price:,.0f}원)", ""],
                    textposition="bottom right",
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=1,
                col=1,
                secondary_y=True,
            )

        if buy_date is not None and buy_date in p_df["Date"].values:
            max_y, min_y = (valid_p_df["Price"].max(), valid_p_df["Price"].min()) if not valid_p_df.empty else (100000, 0)
            margin = (max_y - min_y) * 0.1 if max_y != min_y else max_y * 0.1
            fig.add_trace(
                go.Scatter(
                    x=[buy_date, buy_date],
                    y=[min_y - margin, max_y + margin],
                    mode="lines+text",
                    line=dict(color="#00E676", dash="dash", width=2),
                    name="매수일자",
                    text=["매수타점", ""],
                    textposition="top right",
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=1,
                col=1,
                secondary_y=True,
            )

    fig.update_layout(
        font=dict(color="#FFFFFF"),
        height=750,
        template="plotly_dark",
        plot_bgcolor="#121212",
        paper_bgcolor="#121212",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color="#FFFFFF")),
        margin=dict(l=10, r=10, t=50, b=10),
        barmode="group",
    )
    fig.update_xaxes(showgrid=False, color="#FFFFFF")
    fig.update_yaxes(title_text="비중 (%)", secondary_y=False, row=1, col=1, showgrid=False, zeroline=False, color="#FFFFFF")
    fig.update_yaxes(title_text="주가 (원)", secondary_y=True, row=1, col=1, showgrid=True, gridcolor="#333333", zeroline=False, color="#FFFFFF")
    fig.update_yaxes(title_text="매수금액(백만)", secondary_y=False, row=2, col=1, showgrid=True, gridcolor="#333333", zeroline=True, zerolinecolor="#555555", color="#FFFFFF")
    fig.update_yaxes(title_text="수량증감(주)", secondary_y=True, row=2, col=1, showgrid=False, zeroline=True, zerolinecolor="#555555", color="#FFFFFF")

    st.plotly_chart(fig, use_container_width=True, key=f"3d_chart_{unique_key}_{stock_name}")


# =====================================================================
# 섹션 1: 범프 차트
# =====================================================================
selected_etf = st.sidebar.selectbox("ETF 선택", list(etf_data.keys()))
st.sidebar.markdown("<br>" * 15, unsafe_allow_html=True)

raw_df = etf_data[selected_etf].copy()

if len(raw_df.columns) > 3:
    date_col = raw_df.columns[0]
    stock_cols = [c for c in raw_df.columns if c != date_col and not str(c).endswith("_증감")]

    df_weight = raw_df[[date_col] + stock_cols].copy().melt(
        id_vars=[date_col], var_name="종목명", value_name="비중"
    )
    change_cols = [f"{c}_증감" for c in stock_cols if f"{c}_증감" in raw_df.columns]
    df_change = raw_df[[date_col] + change_cols].copy()
    df_change.columns = [date_col] + [c.replace("_증감", "") for c in change_cols]
    df_change = df_change.melt(id_vars=[date_col], var_name="종목명", value_name="수량증감")
    df = pd.merge(df_weight, df_change, on=[date_col, "종목명"], how="left")
else:
    df = raw_df.copy()
    df.columns = ["일자", "종목명", "비중"]
    df["수량증감"] = "-"

current_date_col = df.columns[0]
df[current_date_col] = pd.to_datetime(df[current_date_col], errors="coerce")
df["비중"] = pd.to_numeric(df["비중"], errors="coerce")
df = df.dropna(subset=[current_date_col, "비중"]).sort_values(by=current_date_col)
df[current_date_col] = df[current_date_col].dt.strftime("%m-%d")
df["순위"] = df.groupby(current_date_col)["비중"].rank(method="first", ascending=False)


def split_qty_display(val) -> str:
    parsed = parse_change_cell(val)
    change = parsed["qty_change"]
    if change > 0:
        return f"🔴▲{change:,}"
    if change < 0:
        return f"🔵▼{abs(change):,}"
    return "0"


def format_price_display(val) -> str:
    text = str(val)
    price_match = re.search(r"₩[\d,]+(?:\s*\([+-]?[\d.]+%\))?", text)
    if not price_match:
        return "-"
    price_str = price_match.group(0)
    if "(+" in price_str or "+" in price_str:
        return f"<span style='color:#FF5252'><b>{price_str}</b></span>"
    if "(-" in price_str or "-" in price_str:
        return f"<span style='color:#448AFF'><b>{price_str}</b></span>"
    return price_str


last_weights = df.groupby("종목명")["비중"].last().to_dict()
df["수량증감(주식수)"] = df["수량증감"].apply(split_qty_display)
df["종가/등락률"] = df["수량증감"].apply(format_price_display)
df["종목표시명"] = df["종목명"].apply(lambda name: f"{name}({last_weights.get(name, 0):.2f})")

latest_date_val = df[current_date_col].max()
latest_order = (
    df[df[current_date_col] == latest_date_val]
    .sort_values(by="비중", ascending=False)["종목표시명"]
    .tolist()
)

st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (최근 20영업일)")

fig = px.line(
    df,
    x=current_date_col,
    y="순위",
    color="종목표시명",
    markers=True,
    hover_name="종목표시명",
    category_orders={"종목표시명": latest_order},
    hover_data={
        "순위": False,
        "비중": True,
        "수량증감": False,
        "수량증감(주식수)": True,
        "종가/등락률": True,
        current_date_col: False,
        "종목표시명": False,
    },
)
fig.update_layout(
    font=dict(color="#FFFFFF"),
    template="plotly_dark",
    plot_bgcolor="#121212",
    paper_bgcolor="#121212",
    yaxis=dict(
        title="종목 순위 (등수)",
        autorange="reversed",
        tickmode="linear",
        dtick=1,
        showgrid=False,
        zeroline=False,
        color="#FFFFFF",
    ),
    xaxis=dict(type="category", title="날짜 (월-일)", showgrid=False, color="#FFFFFF"),
    height=800,
    legend=dict(
        title=dict(text="종목명(%)", font=dict(color="#FFFFFF")),
        font=dict(color="#FFFFFF", size=13),
        orientation="v",
        yanchor="middle",
        y=0.5,
        xanchor="left",
        x=1.02,
    ),
    hovermode="closest",
    hoverlabel=dict(bgcolor="#2A2A2A", font_size=13, font_color="white", bordercolor="#444444", align="left"),
)
st.plotly_chart(fig, use_container_width=True, key="main_bump_chart")


# =====================================================================
# 섹션 2: 통합 순매수 TOP20
# =====================================================================
st.markdown("---")
st.header("🔥 최근 5영업일 누적 순매수 찐 주도주 TOP 20 (단위: 백만원)")

merged_data = {"TIME": [], "KoAct": [], "TIGER": []}

for etf_name, df in etf_data.items():
    category = resolve_brand(etf_name)
    if not category:
        continue
    if len(df.columns) <= 3:
        continue

    date_col = df.columns[0]
    work_df = df.copy()
    work_df[date_col] = pd.to_datetime(work_df[date_col], errors="coerce")
    work_df = work_df.dropna(subset=[date_col]).sort_values(by=date_col)
    if work_df.empty:
        continue

    recent_df = work_df.tail(5)
    last_1_date = work_df.iloc[-1][date_col] if len(work_df) >= 1 else None
    last_3_dates = set(work_df[date_col].tail(3).tolist())
    last_5_dates = set(work_df[date_col].tail(5).tolist())
    latest_date_str = last_1_date.strftime("%Y-%m-%d") if last_1_date is not None else "N/A"

    change_cols = [c for c in work_df.columns if str(c).endswith("_증감")]
    for col in change_cols:
        stock_name = col.replace("_증감", "")
        amt_1d = 0.0
        amt_3d = 0.0
        amt_5d = 0.0

        for _, row in recent_df.iterrows():
            row_date = row[date_col]
            parsed = parse_change_cell(row[col])
            if pd.isna(parsed["price"]):
                daily_amt = 0.0
            else:
                daily_amt = (parsed["qty_change"] * float(parsed["price"])) / 1_000_000.0

            if row_date in last_5_dates:
                amt_5d += daily_amt
            if row_date in last_3_dates:
                amt_3d += daily_amt
            if last_1_date is not None and row_date == last_1_date:
                amt_1d += daily_amt

        if amt_5d != 0 or amt_1d != 0:
            merged_data[category].append(
                {
                    "기준일자": latest_date_str,
                    "종목명": stock_name,
                    "당일매수(백만)": amt_1d,
                    "3일매수(백만)": amt_3d,
                    "5일매수(백만)": amt_5d,
                }
            )


def draw_merged_top20(category_records, category_name, color_map):
    if not category_records:
        st.info(f"{category_name} 집계 대상 데이터가 없습니다.")
        return pd.DataFrame(columns=["기준일자", "종목명", "당일매수(백만)", "3일매수(백만)", "5일매수(백만)"])

    full_df = pd.DataFrame(category_records)
    grouped = (
        full_df.groupby("종목명")
        .agg(
            {
                "기준일자": "first",
                "당일매수(백만)": "sum",
                "3일매수(백만)": "sum",
                "5일매수(백만)": "sum",
            }
        )
        .reset_index()
    )

    grouped["5일매수(백만)"] = grouped["5일매수(백만)"].round(1)
    grouped["3일매수(백만)"] = grouped["3일매수(백만)"].round(1)
    grouped["당일매수(백만)"] = grouped["당일매수(백만)"].round(1)

    res_df = grouped.sort_values(by="5일매수(백만)", ascending=False).head(20)
    date_str = res_df["기준일자"].iloc[0] if not res_df.empty else "N/A"

    melted = res_df.melt(
        id_vars=["종목명"],
        value_vars=["5일매수(백만)", "3일매수(백만)", "당일매수(백만)"],
        var_name="기간",
        value_name="순매수금액",
    )

    fig = px.bar(
        melted,
        x="종목명",
        y="순매수금액",
        color="기간",
        barmode="group",
        text="순매수금액",
        title=f"🔥 [{category_name}] 5일 누적 종목 통합 TOP 20 ({date_str} 기준)",
        color_discrete_map=color_map,
    )
    fig.update_layout(
        font=dict(color="#FFFFFF"),
        template="plotly_dark",
        plot_bgcolor="#121212",
        paper_bgcolor="#121212",
        xaxis_title="",
        yaxis_title="합산 순매수 금액 (백만원)",
        height=650,
    )
    fig.update_traces(textposition="outside", textangle=-90, textfont_size=10, texttemplate="%{text:,.1f}")
    st.plotly_chart(fig, use_container_width=True, key=f"bar_{category_name}")
    return res_df


# TIME / KoAct / TIGER 차트
t20_time = draw_merged_top20(
    merged_data["TIME"],
    "TIME",
    {"5일매수(백만)": "#FFBB78", "3일매수(백만)": "#FF7F0E", "당일매수(백만)": "#D62728"},
)
if not t20_time.empty:
    with st.expander("🦅 [히든 대시보드] TIME 통합 TOP 20 입체 분석"):
        stocks = t20_time["종목명"].tolist()
        tabs = st.tabs([f"📈 {s}" for s in stocks])
        for idx, tab in enumerate(tabs):
            with tab:
                render_stock_3d_chart(stocks[idx], etf_data, base_ledger_df, f"t_{idx}")

st.markdown("<br>", unsafe_allow_html=True)
t20_koact = draw_merged_top20(
    merged_data["KoAct"],
    "KoAct",
    {"5일매수(백만)": "#AEC7E8", "3일매수(백만)": "#1F77B4", "당일매수(백만)": "#17BECF"},
)
if not t20_koact.empty:
    with st.expander("🦅 [히든 대시보드] KoAct 통합 TOP 20 입체 분석"):
        stocks = t20_koact["종목명"].tolist()
        tabs = st.tabs([f"📈 {s}" for s in stocks])
        for idx, tab in enumerate(tabs):
            with tab:
                render_stock_3d_chart(stocks[idx], etf_data, base_ledger_df, f"k_{idx}")

st.markdown("<br>", unsafe_allow_html=True)
t20_tiger = draw_merged_top20(
    merged_data["TIGER"],
    "TIGER",
    {"5일매수(백만)": "#C5E1A5", "3일매수(백만)": "#8BC34A", "당일매수(백만)": "#33691E"},
)
if not t20_tiger.empty:
    with st.expander("🦅 [히든 대시보드] TIGER 통합 TOP 20 입체 분석"):
        stocks = t20_tiger["종목명"].tolist()
        tabs = st.tabs([f"📈 {s}" for s in stocks])
        for idx, tab in enumerate(tabs):
            with tab:
                render_stock_3d_chart(stocks[idx], etf_data, base_ledger_df, f"tg_{idx}")


# =====================================================================
# 섹션 2-1: 상세 거래 장부
# =====================================================================
st.markdown("---")
with st.expander("🔍 [히든 데이터베이스] TOP 20 종목들의 개별 ETF 거래 장부 (어느 ETF가 샀나?)"):
    top_frames = [df for df in [t20_time, t20_koact, t20_tiger] if not df.empty and "종목명" in df.columns]
    if top_frames:
        top20_all = pd.concat(top_frames, ignore_index=True)["종목명"].dropna().unique()
    else:
        top20_all = []

    history_rows = []
    for etf_name, df_raw in etf_data.items():
        date_col = df_raw.columns[0]
        df_proc = df_raw.tail(20)

        for stock_name in top20_all:
            change_col = f"{stock_name}_증감"
            if change_col not in df_proc.columns:
                continue

            for _, row in df_proc.iterrows():
                parsed = parse_change_cell(row[change_col])
                if parsed["qty_change"] == 0 or pd.isna(parsed["price"]):
                    continue

                sign_text = f"🔴▲{parsed['qty_change']:,}" if parsed["qty_change"] > 0 else f"🔵▼{abs(parsed['qty_change']):,}"
                history_rows.append(
                    {
                        "일자": row[date_col],
                        "운용사(ETF)": etf_name,
                        "종목명": stock_name,
                        "매수/매도": sign_text,
                        "금액(백만)": round((parsed["qty_change"] * float(parsed["price"])) / 1_000_000.0, 1),
                        "종가": f"₩{int(parsed['price']):,}",
                    }
                )

    if history_rows:
        history_df = pd.DataFrame(history_rows)
        history_df["일자"] = pd.to_datetime(history_df["일자"], errors="coerce")
        history_df = history_df.sort_values(["일자", "금액(백만)"], ascending=[False, False])
        st.dataframe(history_df, use_container_width=True, hide_index=True)
    else:
        st.info("표시할 개별 ETF 거래 장부가 없습니다.")


# =====================================================================
# 섹션 3: 관심/매입 종목 분석
# =====================================================================
st.markdown("---")
st.header("🦅 내 관심/매입 종목 정밀 입체 분석 대시보드")

with st.expander("🦅 [히든 대시보드] 내가 원하는 종목을 골라서 분석 차트 열어보기", expanded=True):
    default_stocks = []
    if not base_ledger_df.empty and "종목명" in base_ledger_df.columns:
        default_stocks = [
            stock
            for stock in base_ledger_df["종목명"].dropna().astype(str).unique().tolist()
            if stock in all_stocks_list
        ]

    col1, col2 = st.columns([2, 1])
    with col1:
        user_selected = st.multiselect("🔍 종목 선택:", options=all_stocks_list, default=default_stocks)
    with col2:
        uploaded = st.file_uploader("📁 '매입장부.xlsx' 업로드", type=["xlsx"])
        st.download_button("📥 양식 다운로드", data=build_template_file(), file_name="매입장부_양식.xlsx")

    current_ledger = pd.read_excel(uploaded) if uploaded else base_ledger_df
    final_stocks = list(dict.fromkeys(user_selected))

    if final_stocks:
        tabs = st.tabs([f"📈 {name}" for name in final_stocks])
        for idx, tab in enumerate(tabs):
            with tab:
                render_stock_3d_chart(final_stocks[idx], etf_data, current_ledger, f"custom_{idx}")
    else:
        st.info("분석할 종목을 하나 이상 선택해 주세요.")
