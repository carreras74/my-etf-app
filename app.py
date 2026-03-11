import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import os

# 1. 페이지 설정
st.set_page_config(page_title="ETF 비중 분석", layout="wide")
st.title("📈 ETF 종목별 비중 변화 추적")

# 2. 구글 시트 ID (이게 함수 밖이나 안에 정확히 있어야 합니다)
SPREADSHEET_ID = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=5)
def load_data_from_google():
    try:
        # 클라우드 Secrets에서 열쇠 가져오기
        credentials = st.secrets["google_credentials"]
        gc = gspread.service_account_from_dict(credentials)
        
        # 구글 시트 열기
        sh = gc.open_by_key(SPREADSHEET_ID)
        worksheets = sh.worksheets()
        
        all_data = {}
        for ws in worksheets:
            data = ws.get_all_records()
            if data:
                all_data[ws.title] = pd.DataFrame(data)
        return all_data
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return None

etf_data = load_data_from_google()

if etf_data:
    selected_etf = st.sidebar.selectbox("분석할 ETF 선택", list(etf_data.keys()))
    df = etf_data[selected_etf].copy()

    # 데이터가 가로로 긴 형태일 경우 세로로 변환
    if len(df.columns) > 3:
        date_col = df.columns[0]
        df = df.melt(id_vars=[date_col], var_name='종목명', value_name='비중')
    else:
        df.columns = ['일자', '종목명', '비중']

    # 데이터 정제
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
        xaxis_title="날짜/시간",
        height=750,
        legend=dict(title="종목명", orientation="v", yanchor="top", y=1, xanchor="left", x=1.02),
        hovermode="x unified"
    )

    st.plotly_chart(fig, use_container_width=True)
    st.info(f"✅ 현재 {len(df[df.columns[1]].unique())}개 종목이 표시되고 있습니다.")

else:
    st.warning("데이터가 없습니다. 구글 시트를 확인해 주세요.")
    st.warning("데이터가 없습니다.")


