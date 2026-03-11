import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import os

# 1. 페이지 설정
st.set_page_config(page_title="ETF 전종목 비중 추적", layout="wide")
st.title("📈 ETF 종목별 비중 변화 (20개 종목 전체)")

# 2. 구글 시트 연결
# 기존 3줄을 지우고 아래 2줄로 바꿔주세요
credentials = st.secrets["google_credentials"]
gc = gspread.service_account_from_dict(credentials)

@st.cache_data(ttl=5)
def load_data_from_google():
    try:
        gc = gspread.service_account(filename=json_path)
        sh = gc.open_by_key(spreadsheet_id)
        worksheets = sh.worksheets()
        all_data = {ws.title: pd.DataFrame(ws.get_all_records()) for ws in worksheets if ws.get_all_records()}
        return all_data
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return None

etf_data = load_data_from_google()

if etf_data:
    selected_etf = st.sidebar.selectbox("ETF 선택", list(etf_data.keys()))
    df = etf_data[selected_etf].copy()

    # [핵심] 가로로 긴 데이터를 세로로 변환 (Melt 처리)
    if len(df.columns) > 3:
        date_col = df.columns[0] # 첫 번째 컬럼(Date)
        # 가로로 나열된 종목명들을 '종목명'이라는 하나의 컬럼으로 모읍니다.
        df = df.melt(id_vars=[date_col], var_name='종목명', value_name='비중')
    else:
        date_col, name_col, weight_col = df.columns[0], df.columns[1], df.columns[2]
        df.columns = ['일자', '종목명', '비중']
        date_col, name_col, weight_col = '일자', '종목명', '비중'

    # 데이터 타입 정제
    df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
    df[df.columns[2]] = pd.to_numeric(df[df.columns[2]], errors='coerce')
    df = df.dropna().sort_values(by=df.columns[0])

    # 3. 그래프 그리기
    st.subheader(f"📅 {selected_etf} 실시간 비중 추이")

    fig = px.line(
        df, 
        x=df.columns[0], 
        y=df.columns[2], 
        color=df.columns[1], 
        markers=True,
        hover_name=df.columns[1]
    )

    fig.update_layout(
        yaxis=dict(range=[0, df[df.columns[2]].max() * 1.1], title="비중 (%)"),
        xaxis_title="날짜",
        height=750,
        legend=dict(title="종목명", orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        hovermode="x unified"
    )

    st.plotly_chart(fig, use_container_width=True)

    # 4. 종목 리스트 및 데이터 확인
    st.info(f"✅ 총 {len(df[df.columns[1]].unique())}개 종목이 그래프에 표시되고 있습니다.")
    with st.expander("데이터 표 보기"):
        st.dataframe(df)

else:

    st.warning("데이터가 없습니다.")
