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
# 2. 구글 시트 연결 및 데이터 로드 (섹터사전 포함)
# =====================================================================
spreadsheet_id = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=3600)
def load_data():
    creds_json = json.loads(st.secrets["google_key"])
    gc = gspread.service_account_from_dict(creds_json)
    sh = gc.open_by_key(spreadsheet_id)
    return {ws.title: pd.DataFrame(ws.get_all_records()) for ws in sh.worksheets() if ws.get_all_records()}

with st.spinner("구글 시트에서 최신 수급 데이터와 섹터 사전을 불러오는 중..."):
    try:
        raw_etf_data = load_data()
        
        # 💡 [핵심] 구글 시트에서 '섹터사전' 탭을 읽어와서 파이썬 딕셔너리로 자동 변환
        if "섹터사전" in raw_etf_data:
            sector_df = raw_etf_data["섹터사전"]
            # A열(종목명)과 B열(섹터명)이 있다고 가정하고 딕셔너리 생성
            if '종목명' in sector_df.columns and '섹터명' in sector_df.columns:
                SECTOR_MAP = dict(zip(sector_df['종목명'], sector_df['섹터명']))
            else:
                st.warning("⚠️ '섹터사전' 탭에 '종목명', '섹터명' 열(Column)이 정확히 있는지 확인해주세요.")
                SECTOR_MAP = {}
        else:
            st.warning("⚠️ 구글 시트에 '섹터사전' 탭이 아직 없습니다. 종목들이 모두 '기타'로 분류됩니다.")
            SECTOR_MAP = {}
            
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        st.stop()

# =====================================================================
# 3. 데이터 파싱 및 섹터/종목별 순매수 합산 엔진
# =====================================================================
all_records = []
for etf_name, df in raw_etf_data.items():
    # 수량백업 시트, TIGER ETF, 그리고 방금 불러온 '섹터사전' 시트는 수급 계산에서 제외
    if "수량백업" in etf_name or "TIGER" in etf_name or "타이거" in etf_name or "섹터사전" in etf_name: 
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
                    # 💡 구글 시트에서 가져온 SECTOR_MAP을 이용해 섹터 매핑 (없으면 '기타')
                    sector = SECTOR_MAP.get(stock_name, "기타")
                    all_records.append({'Date': d_val, 'Sector': sector, 'Stock': stock_name, 'NetBuy_Amt': amt})

if not all_records:
    st.warning("분석할 수급 데이터가 부족합니다. 구글 시트를 확인해주세요.")
    st.stop()

df_records = pd.DataFrame(all_records)
df_records['Date'] = pd.to_datetime(df_records['Date'])

# =====================================================================
# 4. [메인 차트] 섹터별 5일 누적 순매수 로테이션
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
    sector_ranks_melted[sector_ranks_melted['Sector'] != '기타'], # 기타 제외하고 랭킹 표시
    x='Date_str', y='Rank', color='Sector', markers=True,
    title="📈 스마트머니 섹터 선호도 순위 변동 (1위로 갈수록 자금 유입 강함)"
)
fig_sector.update_yaxes(autorange="reversed", title="섹터 순위")
fig_sector.update_xaxes(title="날짜")
fig_sector.update_layout(template="plotly_dark", height=500)
st.plotly_chart(fig_sector, use_container_width=True)

st.markdown("---")

# =====================================================================
# 5. [디테일 분석] 선택한 섹터의 멱살을 잡은 종목은?
# =====================================================================
st.header("🔍 섹터별 하드캐리 종목 해부 (The 'Why')")
st.markdown("선택한 섹터에 최근 5일 동안 **어떤 종목을 통해 자금이 들어왔는지** 확인합니다.")

# 셀렉트 박스로 섹터 선택 (최신일자 기준 1위 섹터를 기본값으로 설정)
latest_date = rolling_5d_sector.index[-1]
latest_top_sector = rolling_5d_sector.loc[latest_date].drop("기타", errors='ignore').idxmax()
unique_sectors = [s for s in SECTOR_MAP.values() if s != "기타"]

# 만약 구글 시트 섹터사전이 비어있어서 unique_sectors가 없다면 에러 방지
if unique_sectors:
    default_index = list(set(unique_sectors)).index(latest_top_sector) if latest_top_sector in set(unique_sectors) else 0
    selected_sector = st.selectbox("🎯 분석할 섹터를 선택하세요:", list(set(unique_sectors)), index=default_index)
else:
    selected_sector = "기타"
    st.info("구글 시트 '섹터사전'에 등록된 섹터가 없어 임시로 '기타'만 표시합니다.")

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

# =====================================================================
# 6. 미분류 종목 확인 (사전 업데이트용)
# =====================================================================
with st.expander("👀 (참고) '기타'로 분류된 종목 중 수급이 강한 녀석들은? (사전 업데이트 필요)", expanded=True):
    etc_df = df_records[(df_records['Sector'] == '기타') & (df_records['Date'].isin(last_5_dates))]
    if not etc_df.empty:
        etc_sum = etc_df.groupby('Stock')['NetBuy_Amt'].sum().sort_values(ascending=False).head(20).reset_index()
        st.dataframe(etc_sum.style.format({"NetBuy_Amt": "{:,.1f} M"}), use_container_width=True)
        st.caption("💡 위 리스트에서 금액이 큰 종목을 발견하셨나요? 구글 시트 **[섹터사전]** 탭에 가셔서 해당 종목과 섹터명을 추가하시면 앱에 즉시 반영됩니다!")
    else:
        st.success("🎉 완벽합니다! 현재 수급이 들어오는 모든 종목이 섹터 사전에 매핑되어 있습니다.")
