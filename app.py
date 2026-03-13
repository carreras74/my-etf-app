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

    # 3. 그래프 그리기
    st.subheader(f"📅 {selected_etf} 실시간 순위 변동 추이")

    fig = px.line(
        df, 
        x=date_col_name, 
        y='순위',                # 🛠️ [복구] 다시 '순위'를 기준으로 간격을 쫙 펴줍니다!
        color=name_col_name, 
        markers=True,
        hover_name=name_col_name,
        hover_data={
            weight_col_name: True,   # 마우스 올렸을 때 실제 '비중(%)' 나오게 하기
            '순위': True,            
            date_col_name: False,
            name_col_name: False
        }
    )

    fig.update_layout(
        yaxis=dict(
            autorange="reversed",    # 🛠️ [복구] 1등이 꼭대기로 가도록 뒤집기
            title="순위 (등)",
            tickmode='linear',
            tick0=1,
            dtick=1
        ),
        xaxis_title="날짜",
        height=800,
        
        # 🛠️ [수리 1] 범례(이름표)는 붕 뜨지 않게 그래프 정중앙(middle, 0.5)에 안착!
        legend=dict(title="종목명", orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        
        # 🛠️ [수리 2] 마우스 올리면 전체가 뜨는 게 아니라 딱 '그 종목'만 깔끔하게 톡!
        hovermode="closest"
    )

    st.plotly_chart(fig, use_container_width=True)

    # 4. 종목 리스트 및 데이터 확인
    st.info(f"✅ 총 {len(df[name_col_name].unique())}개 종목이 그래프에 표시되고 있습니다.")
    with st.expander("데이터 표 보기"):
        st.dataframe(df.sort_values(by=[date_col_name, '순위']))

else:
    st.warning("데이터가 없습니다.")


