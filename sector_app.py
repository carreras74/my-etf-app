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
import json

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
    """구글 시트에서 섹터 정보를 가져옵니다. ('섹터명' 자동 인식)"""
    try:
        if "google_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["google_credentials"])
            gc = gspread.service_account_from_dict(creds_dict)
        else:
            current_folder = os.path.dirname(os.path.abspath(__file__))
            gc = gspread.service_account(filename=os.path.join(current_folder, 'google_key.json'))
            
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA/edit'
        sh = gc.open_by_url(SHEET_URL)
        worksheet = sh.worksheet("섹터사전")
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)

        if df.empty:
            st.error("❌ 구글 시트에 데이터가 없습니다.")
            return {}
            
        # 💡 [핵심 수정] '섹터' 또는 '섹터명' 컬럼을 유연하게 자동 탐색
        cols = df.columns.tolist()
        target_col = '섹터명' if '섹터명' in cols else ('섹터' if '섹터' in cols else None)
        
        if '종목명' in cols and target_col:
            return dict(zip(df['종목명'].apply(clean_name), df[target_col]))
        else:
            st.error(f"❌ 구글 시트 컬럼 확인 필요. 현재 컬럼: {cols}")
            return {}
            
    except Exception as e:
        st.error(f"⚠️ 구글 시트 연결 실패: {e}")
        return {}

@st.cache_data(ttl=3600)
def load_krx_mapping():
    try:
        krx_df = fdr.StockListing('KRX')
        return dict(zip(krx_df['Name'].apply(clean_name), krx_df['Code']))
    except Exception:
        return {}

@st.cache_data(ttl=300)
def get_market_returns(lookback_days):
    today = datetime.datetime.now()
    yesterday = today - datetime.timedelta(days=1)
    
    # 1일(당일) 초고속 우회 패스 (IP 차단 시 1순위 권장)
    if lookback_days == 1:
        try:
            fdr_current = fdr.StockListing('KRX')
            ratio_col = next((c for c in ['ChagesRatio', 'ChangesRatio'] if c in fdr_current.columns), None)
            if ratio_col:
                returns = dict(zip(fdr_current['Code'], pd.to_numeric(fdr_current[ratio_col], errors='coerce').fillna(0.0)))
                return returns, "전일 종가", "오늘 현재가"
        except Exception: pass

    # 다일(Multi-day) 계산 (IP 차단 방어)
    try:
        df_samsung = stock.get_market_ohlcv((today - datetime.timedelta(days=40)).strftime("%Y%m%d"), yesterday.strftime("%Y%m%d"), "005930")
        b_days = df_samsung.index.tolist()
        start_date = b_days[-lookback_days].strftime("%Y%m%d")
        
        time.sleep(0.5)
        df_kpi = stock.get_market_cap(start_date, market="KOSPI")
        time.sleep(0.5)
        df_kdq = stock.get_market_cap(start_date, market="KOSDAQ")
        past_prices = pd.concat([df_kpi, df_kdq])['종가'].to_dict()
        
        fdr_current = fdr.StockListing('KRX')
        current_prices = dict(zip(fdr_current['Code'], fdr_current['Close']))
        
        returns = {code: ((current_prices.get(code, 0) - p_p) / p_p * 100) if p_p > 0 else 0 for code, p_p in past_prices.items()}
        return returns, start_date, "오늘 현재가"
    except Exception:
        return None, "", ""

# =====================================================================
# 3. 사이드바 및 실행
# =====================================================================
with st.sidebar:
    st.header("⚙️ 분석 설정")
    uploaded_file = st.file_uploader("📂 인포스탁 테마 파일 업로드", type=['xlsx', 'csv'])
    lookback_days = st.selectbox("⏱️ 모멘텀 기간 (🚨IP차단 시 1일 선택)", options=[1, 2, 3, 5, 10, 20], index=3)

sector_dict = load_sector_dict_from_gs()
name_to_code = load_krx_mapping()
code_to_return, start_dt, end_dt = get_market_returns(lookback_days)

if code_to_return is None:
    st.error("🚨 한국거래소(KRX) 접속이 일시 차단되었습니다. 왼쪽 메뉴에서 기간을 '1일'로 변경하시면 즉시 우회하여 차트를 볼 수 있습니다.")
    st.stop()

if uploaded_file and sector_dict:
    df_theme = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
    
    rows = []
    for _, row in df_theme.iterrows():
        stocks = str(row['편입종목']).split(',')
        for s_name in stocks:
            s_name = s_name.strip()
            c_name = clean_name(s_name)
            code = name_to_code.get(c_name)
            rows.append({
                '종목명': s_name,
                '섹터': sector_dict.get(c_name, "기타"),
                '수익률': code_to_return.get(code, 0.0) if code else 0.0
            })
    
    full_df = pd.DataFrame(rows).drop_duplicates('종목명')
    sector_perf = full_df.groupby('섹터')['수익률'].mean().sort_values(ascending=False)

    # =====================================================================
    # 4. 시각화: Top 30 주도 섹터 랭킹
    # =====================================================================
    st.subheader(f"🏆 주도 섹터 TOP 30 ({lookback_days}영업일 기준)")
    plot_df = sector_perf.drop("기타", errors='ignore').head(30)
    top_30_names = plot_df.index.tolist()
    
    chart_data = pd.DataFrame({
        '섹터': top_30_names,
        '평균수익률': plot_df.values
    })

    fig = px.bar(
        chart_data, x='평균수익률', y='섹터', orientation='h', 
        color='평균수익률', color_continuous_scale='RdBu_r', text='평균수익률',
        category_orders={"섹터": top_30_names}
    )
    
    fig.update_layout(template="plotly_dark", height=800, yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
    fig.update_traces(texttemplate='%{text:.2f}%', textposition='outside')
    st.plotly_chart(fig, use_container_width=True)
    
    # =====================================================================
    # 5. 하드캐리 종목 해부
    # =====================================================================
    st.markdown("---")
    st.header("🔍 섹터별 하드캐리 종목 해부")
    
    valid_sectors = [s for s in sector_perf.index if s != "기타"]
    if not valid_sectors: valid_sectors = ["기타"]
    
    target_sector = st.selectbox("섹터 상세 분석:", options=valid_sectors, index=0)
    sector_stocks = full_df[full_df['섹터'] == target_sector].sort_values('수익률', ascending=False)
    
    c1, c2 = st.columns([1, 2])
    c1.metric(f"{target_sector} 수익률", f"{sector_perf[target_sector]:.2f}%")
    c1.write(f"추적 종목: {len(sector_stocks)}개")
    
    with c2:
        st.dataframe(sector_stocks.style.background_gradient(cmap='RdYlBu_r', subset=['수익률']), use_container_width=True, hide_index=True)

else:
    st.info("👈 왼쪽 메뉴에서 '인포스탁 엑셀 파일'을 업로드해주세요.")
