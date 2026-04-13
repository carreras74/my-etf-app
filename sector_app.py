import streamlit as st
import pandas as pd
import plotly.express as px
import FinanceDataReader as fdr
from pykrx import stock
import datetime
import time
import gspread
import os
import json

# =====================================================================
# 1. 페이지 설정
# =====================================================================
st.set_page_config(page_title="🔥 주도 섹터 로테이션 대시보드", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    h1, h2, h3, h4, h5, h6, p, div, span { color: #E0E0E0 !important; }
    [data-testid="stDataFrame"] { background-color: #1E1E1E; }
</style>
""", unsafe_allow_html=True)

st.title("🧩 스마트머니 섹터 로테이션 (범프 차트 부활)")

# =====================================================================
# 2. 구글 시트 로더
# =====================================================================
def clean_name(name):
    return str(name).replace(" ", "").upper().strip()

@st.cache_data(ttl=3600)
def load_all_data_from_gs():
    try:
        if "google_credentials" in st.secrets:
            creds_dict = json.loads(st.secrets["google_credentials"])
            gc = gspread.service_account_from_dict(creds_dict)
        else:
            current_folder = os.path.dirname(os.path.abspath(__file__))
            gc = gspread.service_account(filename=os.path.join(current_folder, 'google_key.json'))
        
        sh = gc.open_by_url('https://docs.google.com/spreadsheets/d/1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA/edit')
        
        ws_dict = sh.worksheet("섹터사전")
        df_dict = pd.DataFrame(ws_dict.get_all_records())
        target_col = '섹터명' if '섹터명' in df_dict.columns else '섹터'
        mapping = dict(zip(df_dict['종목명'].apply(clean_name), df_dict[target_col]))
        
        ws_theme = sh.worksheet("인포스탁")
        df_theme = pd.DataFrame(ws_theme.get_all_records())
        
        if '편입종목' in df_theme.columns:
            df_theme = df_theme[df_theme['편입종목'].notna()]
            df_theme['편입종목'] = df_theme['편입종목'].astype(str)
            
        if '날짜' in df_theme.columns:
            df_theme['날짜'] = df_theme['날짜'].astype(str).str.strip()
            
        return mapping, df_theme
    except Exception as e:
        return {}, pd.DataFrame()

# =====================================================================
# 3. 💡 [핵심] 시계열 데이터 최적화 수집 엔진 (호출 횟수 1/2 단축)
# =====================================================================
@st.cache_data(ttl=600)
def get_historical_market_data(lookback_days):
    today = datetime.datetime.now()
    past_limit = today - datetime.timedelta(days=40)
    try:
        df_samsung = stock.get_market_ohlcv(past_limit.strftime("%Y%m%d"), today.strftime("%Y%m%d"), "005930")
        if df_samsung.empty: raise Exception("거래소 데이터 없음")
        b_days = df_samsung.index.tolist()[-lookback_days:]
        
        hist_prices = {}
        progress_text = st.empty()
        
        # 💡 [최적화] 코스피/코스닥 따로 부르지 않고 market="ALL"로 단 한 번에 호출
        for dt in b_days:
            dt_str = dt.strftime("%Y%m%d")
            progress_text.text(f"🔄 과거 주가 수집 중... ({dt_str})")
            time.sleep(1.0) # 매너 타임
            df_all = stock.get_market_ohlcv(dt_str, market="ALL")
            hist_prices[dt] = df_all['종가'].to_dict()
            
        # 오늘 실시간 데이터는 FDR로 초고속 우회 패스
        progress_text.text("🔄 오늘 실시간 주가 수집 중...")
        time.sleep(1.0)
        df_fdr = fdr.StockListing('KRX')
        hist_prices[today] = dict(zip(df_fdr['Code'], df_fdr['Close']))
        b_days.append(today)
        
        progress_text.empty()
        return hist_prices, b_days
    except Exception as e:
        return None, []

# =====================================================================
# 4. 메인 로직
# =====================================================================
sector_dict, df_theme_full = load_all_data_from_gs()

with st.sidebar:
    st.header("⚙️ 분석 설정")
    target_df_theme = df_theme_full
    if not df_theme_full.empty and '날짜' in df_theme_full.columns:
        valid_dates = [d for d in df_theme_full['날짜'].unique() if d and d != 'nan']
        available_dates = sorted(valid_dates, reverse=True)
        if available_dates:
            selected_date = st.selectbox("📅 기준 테마 일자", options=available_dates)
            target_df_theme = df_theme_full[df_theme_full['날짜'] == selected_date]

    lookback_days = st.selectbox("⏱️ 로테이션 추적 기간", options=[3, 5, 10], index=1, format_func=lambda x: f"{x}영업일")
    if st.button("🔄 실시간 데이터 강제 새로고침"):
        st.cache_data.clear()
        st.rerun()

@st.cache_data
def get_krx_mapping():
    df = fdr.StockListing('KRX')
    return dict(zip(df['Name'].apply(clean_name), df['Code']))

krx_mapping = get_krx_mapping()

if not target_df_theme.empty and sector_dict:
    hist_prices, b_days = get_historical_market_data(lookback_days)
    if not hist_prices:
        st.error("🚨 주가 데이터를 가져오지 못했습니다. 잠시 후 새로고침 해주세요.")
        st.stop()

    # 종목 매핑
    theme_stocks = []
    for _, row in target_df_theme.iterrows():
        raw_stocks = str(row.get('편입종목', ''))
        if not raw_stocks or raw_stocks == 'nan': continue
        for s_name in raw_stocks.split(','):
            s_name = s_name.strip()
            c_name = clean_name(s_name)
            code = krx_mapping.get(c_name)
            if code:
                theme_stocks.append({'종목명': s_name, '코드': code, '섹터': sector_dict.get(c_name, "기타")})
    
    base_df = pd.DataFrame(theme_stocks).drop_duplicates('종목명')
    
    # 일자별 누적 수익률 계산 (Base Date 기준)
    daily_returns = []
    base_date = b_days[0]
    
    for dt in b_days[1:]:
        temp_list = []
        for _, row in base_df.iterrows():
            p0 = hist_prices[base_date].get(row['코드'])
            p1 = hist_prices[dt].get(row['코드'])
            if p0 and p1 and p0 > 0:
                temp_list.append({'섹터': row['섹터'], '수익률': ((p1 - p0) / p0) * 100})
        
        if temp_list:
            day_avg = pd.DataFrame(temp_list).groupby('섹터')['수익률'].mean()
            day_avg.name = dt
            daily_returns.append(day_avg)

    rolling_df = pd.concat(daily_returns, axis=1).T
    rolling_df.index = [d.strftime("%m-%d") for d in rolling_df.index]
    
    clean_df = rolling_df.drop(columns=["기타"], errors='ignore')
    top_30 = clean_df.iloc[-1].sort_values(ascending=False).head(30).index.tolist()

    # (1) 당일 기준 누적 강도 (막대)
    st.subheader(f"📊 {lookback_days}영업일 누적 섹터 강도 (TOP 30)")
    today_data = clean_df.loc[clean_df.index[-1], top_30].reset_index()
    today_data.columns = ['섹터', '수익률']
    fig_bar = px.bar(
        today_data, x='수익률', y='섹터', orientation='h', color='수익률',
        color_continuous_scale='RdBu_r', text_auto='.2f', category_orders={"섹터": top_30}
    )
    fig_bar.update_layout(template="plotly_dark", height=600, yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")

    # (2) 매일의 순위 변화 (범프 차트)
    st.subheader(f"📈 최근 {lookback_days}영업일 섹터 로테이션 추세 (범프 차트)")
    rank_df = clean_df[top_30].rank(axis=1, ascending=False, method='min')
    bump_data = rank_df.reset_index().melt(id_vars='index', var_name='섹터', value_name='순위')
    fig_bump = px.line(
        bump_data, x='index', y='순위', color='섹터', markers=True, category_orders={"섹터": top_30}
    )
    fig_bump.update_layout(template="plotly_dark", height=700, yaxis=dict(autorange="reversed", dtick=1))
    for trace in fig_bump.data:
        trace.line.width = 4 if trace.name in top_30[:5] else 1.2
    st.plotly_chart(fig_bump, use_container_width=True)

    st.markdown("---")
    
    # (3) 섹터 내 개별 종목 (세로 막대)
    st.subheader("🔍 선택 섹터 내 개별 종목 상세 (누적 수익률)")
    target_sector = st.selectbox("분석할 섹터를 선택하세요:", options=top_30)
    
    sector_stocks = base_df[base_df['섹터'] == target_sector].copy()
    latest_dt = b_days[-1]
    returns_list = []
    for _, row in sector_stocks.iterrows():
        p0 = hist_prices[base_date].get(row['코드'])
        p1 = hist_prices[latest_dt].get(row['코드'])
        returns_list.append(((p1 - p0) / p0) * 100 if p0 and p1 and p0 > 0 else 0.0)
            
    sector_stocks['수익률(%)'] = returns_list
    sector_stocks = sector_stocks.sort_values('수익률(%)', ascending=False)
    
    fig_stock = px.bar(
        sector_stocks, x='종목명', y='수익률(%)', color='수익률(%)',
        color_continuous_scale='RdBu_r', text_auto='.2f'
    )
    fig_stock.update_layout(template="plotly_dark", height=500, coloraxis_showscale=False, xaxis_tickangle=-45)
    st.plotly_chart(fig_stock, use_container_width=True)
    
    with st.expander("데이터 표로 보기"):
        st.dataframe(
            sector_stocks[['종목명', '코드', '수익률(%)']].style.background_gradient(cmap='RdYlBu_r', subset=['수익률(%)']), 
            use_container_width=True, hide_index=True
        )
