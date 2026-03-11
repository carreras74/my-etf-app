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

    # [수정] 레이아웃 최적화: 범례 중앙 정렬 및 고정형 설정
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
        height=700, 
        legend=dict(
            title="종목명(비중순)", 
            orientation="v", 
            yanchor="middle", # 범례를 세로 기준 중앙에 배치
            y=0.5,            # 중앙 좌표값
            xanchor="left", 
            x=1.02,
            itemclick="toggle",
            itemdoubleclick="toggleothers"
        ),
        hovermode="closest",
        dragmode=False
    )

    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    
    # 4. [복구] 하단 상세 데이터 테이블
    st.subheader("📋 일자별 종목 구성 상세")
    
    # 테이블용 데이터 정리 (최신순 정렬)
    display_df = df.sort_values(by=[df.columns[0], df.columns[2]], ascending=[False, False])
    # 날짜 형식을 보기 좋게 변환
    display_df[df.columns[0]] = display_df[df.columns[0]].dt.strftime('%Y-%m-%d %H:%M')
    
    st.dataframe(display_df, use_container_width=True, height=400)

else:
    st.warning("데이터가 없습니다.")



