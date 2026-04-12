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
# 1. 페이지 설정 및 다크모드
# =====================================================================
st.set_page_config(page_title="🔥 주도 섹터 멀티 대시보드", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    h1, h2, h3, h4, h5, h6, p, div, span { color: #E0E0E0 !important; }
    [data-testid="stDataFrame"] { background-color: #1E1E1E; }
</style>
""", unsafe_allow_html=True)

st.title("🧩 스마트머니 섹터 로테이션 & 주도주 해부")

# =====================================================================
# 2. 데이터 엔진: 섹터 사전 & 시계열 수익률 계산
# =====================================================================

def clean_name(name):
    return str(name).replace(" ", "").upper().strip()

@st.cache_data(ttl=3600)
def load_sector_dict_from_gs():
    try:
        if "google_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["google_credentials"])
            gc = gspread.service_account_from_dict(creds_dict)
        else:
            current_folder = os.path.dirname(os.path.abspath(__file__))
            gc = gspread.service_account(filename=os.path.join(current_folder, 'google_key.json'))
        
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA/edit')
        worksheet = sh.worksheet("섹터사전")
        df = pd.DataFrame(worksheet.get_all_records())
        cols = df.columns.tolist()
        target_col = '섹터명' if '섹터명' in cols else ('섹터' if '섹터' in cols else None)
        return dict(zip(df['종목명'].apply(clean_name), df[target_col])) if target_col else {}
    except: return {}

@st.cache_data(ttl=300)
def get_historical_data(lookback_days):
    today = datetime.datetime.now()
    past_date = today - datetime.timedelta(days=40)
    try:
        # 영업일 리스트 확보
        df_samsung = stock.get_market_ohlcv(past_date.strftime("%Y%m%d"), today.strftime("%Y%m%d"), "005930")
        b_days = df_samsung.index.tolist()[-lookback_days:]
        
        hist_prices = {}
        for dt in b_days:
            dt_str = dt.strftime("%Y%m%d")
            time.sleep(0.5) # IP 차단 방어
            df_cap = pd.concat([stock.get_market_cap(dt_str, market="KOSPI"), stock.get_market_cap(dt_str, market="KOSDAQ")])
            hist_prices[dt] = df_cap['종가'].to_dict()
        
        # 오늘 현재가 추가
        time.sleep(0.5)
        fdr_curr = fdr.StockListing('KRX')
        hist_prices[today] = dict(zip(fdr_curr['Code'], fdr_curr['Close']))
        b_days.append(today)
        return hist_prices, b_days
    except: return None, []

# =====================================================================
# 3. 사이드바 및 데이터 로드
# =====================================================================
with st.sidebar:
    st.header("⚙️ 분석 설정")
    uploaded_file = st.file_uploader("📂 인포스탁 테마 파일 업로드", type=['xlsx', 'csv'])
    lookback_days = st.selectbox("⏱️ 추적 기간", options=[3, 5, 10], index=1)

sector_dict = load_sector_dict_from_gs()
krx_mapping = dict(zip(fdr.StockListing('KRX')['Name'].apply(clean_name), fdr.StockListing('KRX')['Code']))

if uploaded_file and sector_dict:
    hist_prices, b_days = get_historical_data(lookback_days)
    if not hist_prices: st.error("거래소 데이터 호출 제한. 15분 후 시도하세요."); st.stop()

    df_theme = pd.read_excel(uploaded_file) if uploaded_file.name.endswith('.xlsx') else pd.read_csv(uploaded_file)
    theme_stocks = []
    for _, row in df_theme.iterrows():
        for s_name in str(row['편입종목']).split(','):
            s_name = s_name.strip(); c_name = clean_name(s_name)
            code = krx_mapping.get(c_name)
            if code: theme_stocks.append({'종목명': s_name, '코드': code, '섹터': sector_dict.get(c_name, "기타")})
    
    base_df = pd.DataFrame(theme_stocks).drop_duplicates('종목명')
    
    # 시계열 수익률 계산
    daily_returns = []
    base_date = b_days[0]
    for dt in b_days[1:]:
        temp_list = []
        for _, row in base_df.iterrows():
            p0 = hist_prices[base_date].get(row['코드'])
            p1 = hist_prices[dt].get(row['코드'])
            if p0 and p1 and p0 > 0: temp_list.append({'섹터': row['섹터'], '수익률': (p1-p0)/p0*100})
        
        day_avg = pd.DataFrame(temp_list).groupby('섹터')['수익률'].mean()
        day_avg.name = dt; daily_returns.append(day_avg)

    rolling_df = pd.concat(daily_returns, axis=1).T
    rolling_df.index = [d.strftime("%m-%d") for d in rolling_df.index]
    clean_df = rolling_df.drop(columns=["기타"], errors='ignore')
    top_30 = clean_df.iloc[-1].sort_values(ascending=False).head(30).index.tolist()

    # =====================================================================
    # 4. 시각화: [상단] 당일 강도(막대) + [하단] 며칠간 추세(범프)
    # =====================================================================
    
    # (1) 막대 차트: 현재의 힘
    st.subheader(f"📊 당일 섹터별 수익률 강도 (TOP 30)")
    today_data = clean_df.loc[clean_df.index[-1], top_30].reset_index()
    today_data.columns = ['섹터', '수익률']
    
    fig_bar = px.bar(today_data, x='수익률', y='섹터', orientation='h', color='수익률',
                     color_continuous_scale='RdBu_r', text_auto='.2f', category_orders={"섹터": top_30})
    fig_bar.update_layout(template="plotly_dark", height=600, yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")

    # (2) 범프 차트: 며칠간의 순위 변화
    st.subheader(f"📈 최근 {lookback_days}일 섹터 순위 변화 (범프 차트)")
    rank_df = clean_df[top_30].rank(axis=1, ascending=False, method='min')
    bump_data = rank_df.reset_index().melt(id_vars='index', var_name='섹터', value_name='순위')
    
    fig_bump = px.line(bump_data, x='index', y='순위', color='섹터', markers=True, category_orders={"섹터": top_30})
    fig_bump.update_layout(template="plotly_dark", height=700, yaxis=dict(autorange="reversed", dtick=1),
                           xaxis_title="", legend=dict(title="순위(현재 기준)"))
    # 상위 5개 강조
    for trace in fig_bump.data:
        trace.line.width = 4 if trace.name in top_30[:5] else 1.5
        
    st.plotly_chart(fig_bump, use_container_width=True)

else:
    st.info("👈 인포스탁 파일을 업로드해주세요.")
