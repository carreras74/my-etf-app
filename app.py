import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import os

# 1. 페이지 설정
st.set_page_config(page_title="ETF 비중 분석", layout="wide")
st.title("📈 ETF 종목별 비중 변화 추적")

# 2. 구글 시트 ID
SPREADSHEET_ID = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=5)
def load_data_from_google():
    try:
        credentials = st.secrets["google_credentials"]
        gc = gspread.service_account_from_dict(credentials)
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

    # 데이터 형식 변환 (가로 -> 세로)
    if len(df.columns) > 3:
        date_col = df.columns[0]
        df = df.melt(id_vars=[date_col], var_name='종목명', value_name='비중')
    else:
        df.columns = ['일자', '종목명', '비중']

    # 데이터 타입 정제
    df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
    df[df.columns[2]] = pd.to_numeric(df[df.columns[2]], errors='coerce')
    df = df.dropna().sort_values(by=df.columns[0])

    # 비중이 높은 순서대로 종목 정렬
    latest_date = df[df.columns[0]].max()
    sorted_stocks = df[df[df.columns[0]] == latest_date].sort_values(by=df.columns[2], ascending=False)[df.columns[1]].tolist()

    # 3. 그래프 그리기
    st.subheader(f"📅 {selected_etf} 실시간 비중 추이")
    
    fig = px.line(
        df, 
        x=df.columns[0], 
        y=df.columns[2], 
        color=df.columns[1], 
        markers=True,
        hover_name=df.columns[1],
        category_orders={df.columns[1]: sorted_stocks}
    )

    # [핵심 수정] 정보창(Hover)이 화면을 벗어나지 않도록 하고, 가독성 높이기
    fig.update_layout(
        yaxis=dict(
            range=[0, df[df.columns[2]].max() * 1.1], 
            title="비중 (%)",
            fixedrange=True
        ),
        xaxis=dict(
            title="날짜/시간",
            fixedrange=True
        ),
        height=800, # 핸드폰에서 더 길게 보이도록 높이 약간 추가
        legend=dict(
            title="종목명(비중순)", 
            orientation="v", 
            yanchor="top", 
            y=1, 
            xanchor="left", 
            x=1.02,
            itemclick="toggle", # 클릭 시 해당 종목만 켜고 끄기 가능
            itemdoubleclick="toggleothers" # 더블클릭 시 해당 종목만 보기
        ),
        # 정보창 설정 변경
        hovermode="closest", # 'x unified' 대신 'closest'를 사용하여 손가락이 닿은 종목 정보만 깔끔하게 표시
        dragmode=False
    )

    # 툴바 숨기기 및 레이아웃 최적화
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    
    st.info(f"💡 팁: 오른쪽 종목명을 '한 번' 누르면 숨기기, '두 번' 누르면 그 종목만 볼 수 있습니다.")

else:
    st.warning("데이터가 없습니다.")


