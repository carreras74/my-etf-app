import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import json # json 모듈 추가

# 1. 페이지 설정
st.set_page_config(page_title="ETF 전종목 비중 추적", layout="wide")
st.title("📈 ETF 종목별 순위 변동 추이 (범프 차트)")

# 2. 구글 시트 연결 (스트림릿 클라우드 비밀금고 사용)
spreadsheet_id = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=3600)
def load_data_from_google():
    try:
        # 💡 [핵심] 바탕화면 파일 대신, 스트림릿 비밀금고에서 열쇠를 가져옵니다.
        creds_json = json.loads(st.secrets["google_key"])
        gc = gspread.service_account_from_dict(creds_json)
        
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

    # 가로로 긴 데이터를 세로로 변환 (Melt 처리)
    if len(df.columns) > 3:
        date_col = df.columns[0]
        df = df.melt(id_vars=[date_col], var_name='종목명', value_name='비중')
    else:
        date_col, name_col, weight_col = df.columns[0], df.columns[1], df.columns[2]
        df.columns = ['일자', '종목명', '비중']
        date_col, name_col, weight_col = '일자', '종목명', '비중'

    # 데이터 타입 정제
    df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
    df[df.columns[2]] = pd.to_numeric(df[df.columns[2]], errors='coerce')
    df = df.dropna().sort_values(by=df.columns[0])
    
    # 날짜별로 비중에 따른 '순위' 계산
    date_col_name = df.columns[0]
    name_col_name = df.columns[1]
    weight_col_name = df.columns[2]
    
    df['순위'] = df.groupby(date_col_name)[weight_col_name].rank(method='min', ascending=False)

    # -------------------------------------------------------------
    # 🛠️ [수리 포인트 1] 가장 최근 날짜를 기준으로 비중 1등부터 줄 세우는 부품!
    latest_date = df[date_col_name].max()
    latest_order = df[df[date_col_name] == latest_date].sort_values(by=weight_col_name, ascending=False)[name_col_name].tolist()
    # -------------------------------------------------------------

    # 3. 그래프 그리기
    st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (상세 확대 모드)")

    fig = px.line(
        df, 
        x=date_col_name, 
        y=weight_col_name,       # 🛠️ [수리 포인트 1] Y축을 '순위'에서 다시 '비중'으로 원상복구하여 고저차를 살립니다!
        color=name_col_name, 
        markers=True,
        hover_name=name_col_name,
        category_orders={name_col_name: latest_order}, 
        hover_data={
            weight_col_name: True,   
            '순위': True,            # 마우스를 올리면 계산해둔 '순위'는 여전히 예쁘게 뜹니다!
            date_col_name: False,
            name_col_name: False
        }
    )

    fig.update_layout(
        yaxis=dict(
            type="log",              
            title="비중 (%)",
            tickvals=[1, 1.5, 2, 2.5, 3, 4, 5, 7, 10, 15, 20], 
            fixedrange=True          
        ),
        xaxis=dict(
            type="category",         # 🛠️ [핵심 수리 포인트] X축을 '시간의 흐름'이 아닌 '칸칸이 박스(카테고리)'로 강제 변환!
            title="날짜",
            fixedrange=True          
        ),
        height=800,
        legend=dict(
            title="종목명", 
            orientation="v", 
            yanchor="middle", 
            y=0.5, 
            xanchor="left", 
            x=1.02
        ),
        hovermode="closest"
    )
    st.plotly_chart(fig, use_container_width=True)
    # 4. 종목 리스트 및 데이터 확인
    st.info(f"✅ 총 {len(df[name_col_name].unique())}개 종목이 그래프에 표시되고 있습니다.")
    with st.expander("데이터 표 보기"):
        st.dataframe(df.sort_values(by=[date_col_name, '순위']))

else:
    st.warning("데이터가 없습니다.")


