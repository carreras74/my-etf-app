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
# 1. 페이지 설정 및 다크모드 테마
# =====================================================================
st.set_page_config(page_title="🔥 자동화 주도 섹터 대시보드", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    h1, h2, h3, h4, h5, h6, p, div, span { color: #E0E0E0 !important; }
    [data-testid="stDataFrame"] { background-color: #1E1E1E; }
</style>
""", unsafe_allow_html=True)

st.title("🧩 스마트머니 섹터 로테이션 & 주도주 해부")
st.info("✅ 구글 시트의 '인포스탁' 및 '섹터사전' 탭 데이터를 기반으로 자동 분석합니다.")

# =====================================================================
# 2. 데이터 엔진
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
        
        SHEET_URL = 'https://docs.google.com/spreadsheets/d/1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA/edit'
        sh = gc.open_by_url(SHEET_URL)
        
        ws_dict = sh.worksheet("섹터사전")
        df_dict = pd.DataFrame(ws_dict.get_all_records())
        cols_dict = df_dict.columns.tolist()
        target_col = '섹터명' if '섹터명' in cols_dict else ('섹터' if '섹터' in cols_dict else None)
        mapping = dict(zip(df_dict['종목명'].apply(clean_name), df_dict[target_col])) if target_col else {}
        
        ws_theme = sh.worksheet("인포스탁")
        df_theme = pd.DataFrame(ws_theme.get_all_records())
        
        # 💡 [방어 코드 추가] 편입종목이 없는 빈 줄이나 이상한 데이터 삭제
        if '편입종목' in df_theme.columns:
            df_theme = df_theme[df_theme['편입종목'].notna()] # 빈 칸 제거
            df_theme['편입종목'] = df_theme['편입종목'].astype(str) # 무조건 문자열로 변환
        
        return mapping, df_theme
    except Exception as e:
        st.error(f"⚠️ 구글 시트 연결 실패: {e}")
        return {}, pd.DataFrame()

@st.cache_data(ttl=600)
def get_combined_market_data(lookback_days):
    today = datetime.datetime.now()
    
    if lookback_days == 1:
        try:
            df_fdr = fdr.StockListing('KRX')
            ratio_col = next((c for c in ['ChagesRatio', 'ChangesRatio'] if c in df_fdr.columns), None)
            if ratio_col:
                yesterday = today - datetime.timedelta(days=1)
                hist_prices = {yesterday: {}, today: {}}
                
                for _, row in df_fdr.iterrows():
                    code = row['Code']
                    ratio = pd.to_numeric(row[ratio_col], errors='coerce')
                    if pd.isna(ratio): ratio = 0.0
                    
                    hist_prices[yesterday][code] = 100
                    hist_prices[today][code] = 100 * (1 + (ratio / 100))
                    
                return hist_prices, [yesterday, today]
        except Exception as e:
             st.error(f"1일 우회 데이터 로드 실패: {e}")
             pass

    past_limit = today - datetime.timedelta(days=40)
    try:
        df_samsung = stock.get_market_ohlcv(past_limit.strftime("%Y%m%d"), today.strftime("%Y%m%d"), "005930")
        if df_samsung.empty:
            raise Exception("거래소 데이터 비어있음")
            
        b_days = df_samsung.index.tolist()[-lookback_days:]
        
        hist_prices = {}
        progress_text = st.empty()
        
        for i, dt in enumerate(b_days):
            dt_str = dt.strftime("%Y%m%d")
            progress_text.text(f"🔄 거래소 데이터 수집 중... ({dt_str})")
            time.sleep(1.0)
            df_cap = pd.concat([
                stock.get_market_cap(dt_str, market="KOSPI"), 
                stock.get_market_cap(dt_str, market="KOSDAQ")
            ])
            hist_prices[dt] = df_cap['종가'].to_dict()
        
        time.sleep(1.0)
        fdr_curr = fdr.StockListing('KRX')
        hist_prices[today] = dict(zip(fdr_curr['Code'], fdr_curr['Close']))
        b_days.append(today)
        
        progress_text.empty()
        return hist_prices, b_days
    except Exception as e:
        return None, []

# =====================================================================
# 3. 메인 로직
# =====================================================================
with st.sidebar:
    st.header("⚙️ 분석 설정")
    lookback_days = st.selectbox("⏱️ 추적 기간 (차단 시 1일 권장)", options=[1, 3, 5, 10], index=0, format_func=lambda x: f"{x}영업일")
    if st.button("🔄 데이터 강제 새로고침"):
        st.cache_data.clear()
        st.rerun()

sector_dict, df_theme = load_all_data_from_gs()

@st.cache_data
def get_krx_mapping():
    df = fdr.StockListing('KRX')
    return dict(zip(df['Name'].apply(clean_name), df['Code']))

krx_mapping = get_krx_mapping()

if not df_theme.empty and sector_dict:
    # 💡 [방어 코드 추가] '편입종목' 컬럼 확인
    if '편입종목' not in df_theme.columns:
        st.error("🚨 구글 시트 '인포스탁' 탭에 '편입종목' 컬럼이 없습니다. 데이터를 확인해주세요.")
        st.stop()

    hist_prices, b_days = get_combined_market_data(lookback_days)
    
    if hist_prices is None or len(b_days) < 2:
        st.error("🚨 거래소 데이터 호출 제한(IP 차단). 15분 후 시도하거나 '1일'을 선택하세요.")
        st.stop()

    theme_stocks = []
    for _, row in df_theme.iterrows():
        # 💡 [안전하게 텍스트만 처리]
        raw_stocks = str(row.get('편입종목', ''))
        if not raw_stocks or raw_stocks == 'nan':
            continue
            
        for s_name in raw_stocks.split(','):
            s_name = s_name.strip()
            c_name = clean_name(s_name)
            code = krx_mapping.get(c_name)
            if code:
                theme_stocks.append({
                    '종목명': s_name, 
                    '코드': code, 
                    '섹터': sector_dict.get(c_name, "기타")
                })
    
    if not theme_stocks:
        st.warning("⚠️ 유효한 종목을 찾지 못했습니다. 구글 시트의 데이터를 다시 확인해주세요.")
        st.stop()

    base_df = pd.DataFrame(theme_stocks).drop_duplicates('종목명')
    
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

    if not daily_returns:
        st.error("수익률 계산 실패")
        st.stop()

    rolling_df = pd.concat(daily_returns, axis=1).T
    rolling_df.index = [d.strftime("%m-%d") for d in rolling_df.index]
    
    clean_df = rolling_df.drop(columns=["기타"], errors='ignore')
    top_30 = clean_df.iloc[-1].sort_values(ascending=False).head(30).index.tolist()

    st.subheader(f"📊 당일 섹터별 수익률 강도 (TOP 30)")
    today_data = clean_df.loc[clean_df.index[-1], top_30].reset_index()
    today_data.columns = ['섹터', '수익률']
    fig_bar = px.bar(
        today_data, x='수익률', y='섹터', orientation='h', color='수익률',
        color_continuous_scale='RdBu_r', text_auto='.2f', category_orders={"섹터": top_30}
    )
    fig_bar.update_layout(template="plotly_dark", height=600, yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")

    st.subheader(f"📈 최근 {lookback_days}영업일 섹터 순위 변화 (범프 차트)")
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
    target_sector = st.selectbox("🔍 섹터 상세 종목 분석:", options=top_30)
    st.dataframe(base_df[base_df['섹터'] == target_sector], use_container_width=True)

else:
    st.warning("⚠️ 구글 시트 설정을 확인해주세요. '섹터사전'과 '인포스탁' 탭이 필요합니다.")
