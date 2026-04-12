import streamlit as st
import pandas as pd
import plotly.express as px
import FinanceDataReader as fdr
from pykrx import stock
import datetime
import numpy as np
import time
import gspread
import os

# =====================================================================
# 1. 페이지 설정 및 다크모드 테마 적용
# =====================================================================
st.set_page_config(page_title="🔥 주도 섹터 로테이션 추적기", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    h1, h2, h3, h4, h5, h6, p, div, span { color: #E0E0E0 !important; }
    .streamlit-expanderHeader { background-color: #1E1E1E !important; color: #FFFFFF !important; }
    .streamlit-expanderContent { background-color: #121212 !important; }
    [data-testid="stDataFrame"] { background-color: #1E1E1E; }
</style>
""", unsafe_allow_html=True)

st.title("🧩 스마트머니 섹터 로테이션 & 주도주 해부 대시보드")
st.markdown("액티브 ETF 매니저들의 자금 흐름과 인포스탁 테마 데이터를 결합하여 **현재 시장의 진짜 주인공**을 찾아냅니다.")

# =====================================================================
# 2. 데이터 엔진: 섹터 사전 & 주가 수익률 계산
# =====================================================================

def clean_name(name):
    return str(name).replace(" ", "").upper().strip()

@st.cache_data(ttl=3600)
def load_sector_dict_from_gs():
    """구글 시트의 '섹터사전' 탭에서 종목별 섹터 정보를 가져옵니다."""
    try:
        current_folder = os.path.dirname(os.path.abspath(__file__))
        gc = gspread.service_account(filename=os.path.join(current_folder, 'google_key.json'))
        # 회원님의 시트 URL 적용
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA/edit'
        sh = gc.open_by_url(SHEET_URL)
        worksheet = sh.worksheet("섹터사전")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if not df.empty and '종목명' in df.columns:
            return dict(zip(df['종목명'].apply(clean_name), df['섹터']))
        return {}
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def load_krx_mapping():
    """전종목 이름-코드 매핑"""
    try:
        krx_df = fdr.StockListing('KRX')
        return dict(zip(krx_df['Name'].apply(clean_name), krx_df['Code']))
    except Exception:
        return {}

@st.cache_data(ttl=300)
def get_market_returns(lookback_days):
    """실시간 현재가와 과거 종가를 결합한 하이브리드 수익률 엔진 (IP 차단 방어 포함)"""
    today = datetime.datetime.now()
    yesterday = today - datetime.timedelta(days=1)
    
    # 1일(당일)은 초고속 우회 패스
    if lookback_days == 1:
        try:
            fdr_current = fdr.StockListing('KRX')
            ratio_col = next((c for c in ['ChagesRatio', 'ChangesRatio'] if c in fdr_current.columns), None)
            if ratio_col:
                returns = dict(zip(fdr_current['Code'], pd.to_numeric(fdr_current[ratio_col], errors='coerce').fillna(0.0)))
                return returns, "전일 종가", "오늘 현재가"
        except Exception: pass

    # 다일(Multi-day) 계산 로직
    try:
        df_samsung = stock.get_market_ohlcv((today - datetime.timedelta(days=40)).strftime("%Y%m%d"), yesterday.strftime("%Y%m%d"), "005930")
        b_days = df_samsung.index.tolist()
        start_date = b_days[-lookback_days].strftime("%Y%m%d")
        
        # 과거가 (시가총액 API 우회)
        time.sleep(0.5)
        df_kpi = stock.get_market_cap(start_date, market="KOSPI")
        df_kdq = stock.get_market_cap(start_date, market="KOSDAQ")
        past_prices = pd.concat([df_kpi, df_kdq])['종가'].to_dict()
        
        # 현재가
        fdr_current = fdr.StockListing('KRX')
        current_prices = dict(zip(fdr_current['Code'], fdr_current['Close']))
        
        returns = {code: ((current_prices.get(code, 0) - p_p) / p_p * 100) if p_p > 0 else 0 for code, p_p in past_prices.items()}
        return returns, start_date, "오늘 현재가"
    except Exception:
        return {}, "", ""

# =====================================================================
# 3. 사이드바 컨트롤 및 파일 처리
# =====================================================================
with st.sidebar:
    st.header("⚙️ 분석 설정")
    uploaded_file = st.file_uploader("📂 인포스탁 테마 파일 업로드", type=['xlsx', 'csv'])
    lookback_days = st.selectbox("⏱️ 모멘텀 기간", options=[1, 2, 3, 5, 10, 20], format_func=lambda x: f"{x}영업일", index=3)

# 데이터 로드
sector_dict = load_sector_dict_from_gs()
name_to_code = load_krx_mapping()
code_to_return, start_dt, end_dt = get_market_returns(lookback_days)

if not sector_dict:
    st.warning("⚠️ 구글 시트에 '섹터사전'이 없거나 불러오지 못했습니다. 모든 종목이 '기타'로 분류됩니다.")

if uploaded_file and code_to_return:
    df_theme = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
    
    # 테마 데이터를 종목별 데이터로 펼치기
    rows = []
    for _, row in df_theme.iterrows():
        t_name = row['테마명']
        for s_name in str(row['편입종목']).split(','):
            s_name = s_name.strip()
            c_name = clean_name(s_name)
            code = name_to_code.get(c_name)
            rows.append({
                '종목명': s_name,
                '섹터': sector_dict.get(c_name, "기타"),
                '수익률': code_to_return.get(code, 0.0) if code else 0.0
            })
    
    full_df = pd.DataFrame(rows).drop_duplicates('종목명')
    
    # 섹터별 평균 수익률 계산
    sector_perf = full_df.groupby('섹터')['수익률'].mean().sort_values(ascending=False)

    # =====================================================================
    # 4. 시각화: Top 30 범프 차트 (개선된 버전)
    # =====================================================================
    st.subheader(f"🔥 최근 {lookback_days}일 섹터 로테이션 Top 30")
    
    # 시각화용 데이터 정제 (기타 제외)
    plot_df = sector_perf.drop("기타", errors='ignore').head(30)
    top_30_names = plot_df.index.tolist()
    
    # 현재는 단일 시점이지만, 범프 차트 구성을 위해 Rank 데이터 생성
    # (실제 과거 추적 데이터가 있다면 해당 데이터프레임을 사용하세요)
    display_chart_df = pd.DataFrame({
        '섹터': top_30_names,
        '평균수익률': plot_df.values,
        '순위': range(1, len(top_30_names) + 1)
    })

    fig = px.bar(
        display_chart_df,
        x='평균수익률',
        y='섹터',
        orientation='h',
        color='평균수익률',
        color_continuous_scale='RdBu_r',
        text='평균수익률',
        # 💡 범례/축 순서를 1위~30위 순서로 강제 고정
        category_orders={"섹터": top_30_names}
    )

    fig.update_layout(
        template="plotly_dark",
        height=800,
        yaxis=dict(autorange="reversed"), # 1위가 맨 위로
        coloraxis_showscale=False,
        margin=dict(l=150)
    )
    fig.update_traces(texttemplate='%{text:.2f}%', textposition='outside')
    st.plotly_chart(fig, use_container_width=True)

    # =====================================================================
    # 5. 하드캐리 종목 해부 (The 'Why')
    # =====================================================================
    st.markdown("---")
    st.header("🔍 섹터별 하드캐리 종목 해부")
    
    # 1위 섹터 자동 선택
    target_sector = st.selectbox("분석할 섹터 선택:", options=sector_perf.index.tolist(), index=0)
    
    sector_stocks = full_df[full_df['섹터'] == target_sector].sort_values('수익률', ascending=False)
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.metric(f"{target_sector} 평균 수익률", f"{sector_perf[target_sector]:.2f}%")
        st.write(f"추적 종목 수: {len(sector_stocks)}개")
    
    with col2:
        st.dataframe(
            sector_stocks.style.background_gradient(cmap='RdYlBu_r', subset=['수익률']),
            use_container_width=True,
            hide_index=True
        )

else:
    st.info("👈 사이드바에서 인포스탁 테마 파일을 업로드하면 분석이 시작됩니다.")

