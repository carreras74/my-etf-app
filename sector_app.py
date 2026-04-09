import os
import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import json
import re

# =====================================================================
# 1. 페이지 설정 및 다크모드
# =====================================================================
st.set_page_config(page_title="섹터 로테이션 & 주도주 분석", layout="wide")
st.markdown("""
<style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    h1, h2, h3 { color: #E0E0E0 !important; }
</style>
""", unsafe_allow_html=True)

st.title("🧩 스마트머니 섹터 로테이션 & 주도주 해부 대시보드")
st.caption("TIME, KoAct 등 액티브 ETF 매니저들의 자금이 어느 섹터로, 어떤 종목을 통해 들어오는지 추적합니다.")

# =====================================================================
# 2. 섹터 딕셔너리 (사용자가 직접 커스텀 가능)
# =====================================================================
# ETF에 자주 등장하는 종목들을 섹터별로 묶어줍니다. 여기에 없는 종목은 '기타'로 분류됩니다.
SECTOR_MAP = {
    # 🧬 바이오/헬스케어
    "알테오젠": "바이오", "삼천당제약": "바이오", "리가켐바이오": "바이오", "유한양행": "바이오", "휴젤": "바이오", "파마리서치": "바이오", "에스티팜": "바이오",
    # 💻 반도체/AI
    "삼성전자": "반도체", "SK하이닉스": "반도체", "한미반도체": "반도체", "리노공업": "반도체", "이수페타시스": "반도체", "HPSP": "반도체",
    # 🔋 2차전지/에너지
    "에코프로비엠": "2차전지", "에코프로": "2차전지", "LG에너지솔루션": "2차전지", "포스코홀딩스": "2차전지", "엔켐": "2차전지",
    # 🏦 금융/밸류업
    "KB금융": "금융/밸류업", "신한지주": "금융/밸류업", "하나금융지주": "금융/밸류업", "메리츠금융지주": "금융/밸류업", "삼성생명": "금융/밸류업",
    # 🚗 자동차/기계
    "현대차": "자동차/조선", "기아": "자동차/조선", "현대모비스": "자동차/조선", "HD한국조선해양": "자동차/조선",
    # 💄 화장품/소비재
    "실리콘투": "소비재/미용", "클리오": "소비재/미용", "삼양식품": "소비재/미용", "브이티": "소비재/미용"
}

# =====================================================================
# 3. 구글 시트 데이터 로드 (기존 로직 동일)
# =====================================================================
spreadsheet_id = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=3600)
def load_data():
    creds_json = json.loads(st.secrets["google_key"])
    gc = gspread.service_account_from_dict(creds_json)
    sh = gc.open_by_key(spreadsheet_id)
    return {ws.title: pd.DataFrame(ws.get_all_records()) for ws in sh.worksheets() if ws.get_all_records()}

with st.spinner("구글 시트에서 최신 수급 데이터를 불러오는 중..."):
    try:
        raw_etf_data = load_data()
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        st.stop()

# =====================================================================
# 4. 데이터 파싱 및 섹터/종목별 순매수 합산 엔진
# =====================================================================
all_records = []
for etf_name, df in raw_etf_data.items():
    if "수량백업" in etf_name or "TIGER" in etf_name or "타이거" in etf_name: 
        continue
    if len(df.columns) <= 3: continue
    
    date_col = df.columns[0]
    change_cols = [c for c in df.columns if str(c).endswith('_증감')]
    
    for _, row in df.iterrows():
        d_val = row[date_col]
        for col in change_cols:
            stock_name = col.replace('_증감', '')
            v = row[col]
            if isinstance(v, str) and " | " in v:
                q_str, p_str = v.split(" | ")[0].strip(), v.split(" | ")[1].strip()
                qty, price = 0, 0
                
                # 수량 추출
                if '🔴▲' in q_str: qty = int(q_str.replace('🔴▲', '').replace(',', '').strip())
                elif '🔵▼' in q_str: qty = -int(q_str.replace('🔵▼', '').replace(',', '').strip())
                
                # 가격 추출
                match = re.search(r'₩([\d,]+)', p_str)
                if match: price = int(match.group(1).replace(',', ''))
                
                if qty != 0:
                    amt = (qty * price) / 1000000.0 # 백만원 단위
                    sector = SECTOR_MAP.get(stock_name, "기타")
                    all_records.append({'Date': d_val, 'Sector': sector, 'Stock': stock_name, 'NetBuy_Amt': amt})

if not all_records:
    st.warning("분석할 수급 데이터가 부족합니다.")
    st.stop()

df_records = pd.DataFrame(all_records)
df_records['Date'] = pd.to_datetime(df_records['Date'])

# =====================================================================
# 5. [메인 차트] 섹터별 5일 누적 순매수 로테이션
# =====================================================================
st.header("🔥 최근 15영업일 섹터 로테이션 (5일 누적 수급 기준)")

# 일자별, 섹터별 합산 -> 5일 이동합산 -> 랭킹
daily_sector = df_records.groupby(['Date', 'Sector'])['NetBuy_Amt'].sum().reset_index()
pivot_sector = daily_sector.pivot(index='Date', columns='Sector', values='NetBuy_Amt').fillna(0)
rolling_5d_sector = pivot_sector.rolling(window=5, min_periods=1).sum().tail(15) # 최근 15일만

# 랭킹 데이터프레임으로 변환
sector_ranks = rolling_5d_sector.rank(axis=1, method='first', ascending=False)
sector_ranks_melted = sector_ranks.reset_index().melt(id_vars='Date', var_name='Sector', value_name='Rank')
sector_ranks_melted['Date_str'] = sector_ranks_melted['Date'].dt.strftime('%m-%d')

fig_sector = px.line(
    sector_ranks_melted[sector_ranks_melted['Sector'] != '기타'], # 기타 제외하고 보기 좋게
    x='Date_str', y='Rank', color='Sector', markers=True,
    title="📈 스마트머니 섹터 선호도 순위 변동 (1위로 갈수록 자금 유입 강함)"
)
fig_sector.update_yaxes(autorange="reversed", title="섹터 순위")
fig_sector.update_xaxes(title="날짜")
fig_sector.update_layout(template="plotly_dark", height=500)
st.plotly_chart(fig_sector, use_container_width=True)

st.markdown("---")

# =====================================================================
# 6. [디테일 분석] 선택한 섹터의 멱살을 잡은 종목은?
# =====================================================================
st.header("🔍 섹터별 하드캐리 종목 해부 (The 'Why')")
st.markdown("선택한 섹터에 최근 5일 동안 **어떤 종목을 통해 자금이 들어왔는지** 확인합니다.")

# 셀렉트 박스로 섹터 선택 (최신일자 기준 1위 섹터를 기본값으로)
latest_date = rolling_5d_sector.index[-1]
latest_top_sector = rolling_5d_sector.loc[latest_date].drop("기타", errors='ignore').idxmax()
unique_sectors = [s for s in SECTOR_MAP.values() if s != "기타"]

selected_sector = st.selectbox("🎯 분석할 섹터를 선택하세요:", list(set(unique_sectors)), index=list(set(unique_sectors)).index(latest_top_sector))

# 선택한 섹터의 최근 5일 종목별 수급 데이터 필터링
last_5_dates = df_records['Date'].sort_values().unique()[-5:]
sector_df = df_records[(df_records['Sector'] == selected_sector) & (df_records['Date'].isin(last_5_dates))]

if not sector_df.empty:
    stock_sum = sector_df.groupby('Stock')['NetBuy_Amt'].sum().reset_index()
    stock_sum = stock_sum.sort_values(by='NetBuy_Amt', ascending=False).head(10) # Top 10만 표시
    
    fig_stock = px.bar(
        stock_sum, x='Stock', y='NetBuy_Amt', 
        text='NetBuy_Amt',
        title=f"🏆 [{selected_sector}] 섹터 내 최근 5일 순매수 주도주 TOP 10",
        color='NetBuy_Amt', color_continuous_scale='Blues'
    )
    fig_stock.update_traces(texttemplate='%{text:,.1f}M', textposition='outside')
    fig_stock.update_layout(template="plotly_dark", yaxis_title="5일 누적 순매수 (백만원)", xaxis_title="")
    st.plotly_chart(fig_stock, use_container_width=True)
else:
    st.info(f"최근 5일간 '{selected_sector}' 섹터에 유의미한 매수 수급이 포착되지 않았습니다.")

# (옵션) 기타로 분류된 녀석들 중에 놓친 대어가 있는지 확인
with st.expander("👀 (참고) '기타'로 분류된 종목 중 수급이 강한 녀석들은? (사전 업데이트 필요)"):
    etc_df = df_records[(df_records['Sector'] == '기타') & (df_records['Date'].isin(last_5_dates))]
    if not etc_df.empty:
        etc_sum = etc_df.groupby('Stock')['NetBuy_Amt'].sum().sort_values(ascending=False).head(15).reset_index()
        st.dataframe(etc_sum.style.format({"NetBuy_Amt": "{:,.1f} M"}), use_container_width=True)
        st.caption("위 리스트에 큰 금액이 찍히는 종목이 있다면, 코드 상단의 `SECTOR_MAP` 딕셔너리에 추가하여 섹터를 지정해주세요!")