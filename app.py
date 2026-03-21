import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import json

# 1. 페이지 설정
st.set_page_config(page_title="ETF 전종목 비중 추적", layout="wide")
st.title("📈 ETF 종목별 순위 변동 추이 (범프 차트)")

# 2. 구글 시트 연결 (스트림릿 클라우드 비밀금고 사용)
spreadsheet_id = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=3600)
def load_data_from_google():
    try:
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
    
    # 💡 [핵심] raw_df가 바로 구글 시트 원본 그 자체입니다!
    raw_df = etf_data[selected_etf].copy()

    if len(raw_df.columns) > 3:
        date_col = raw_df.columns[0]
        stock_cols = [c for c in raw_df.columns if c != date_col and not str(c).endswith('_증감')]
        
        df_weight = raw_df[[date_col] + stock_cols].copy()
        df_weight = df_weight.melt(id_vars=[date_col], var_name='종목명', value_name='비중')
        
        change_cols = [f"{c}_증감" for c in stock_cols if f"{c}_증감" in raw_df.columns]
        df_change = raw_df[[date_col] + change_cols].copy()
        df_change.columns = [date_col] + [c.replace('_증감', '') for c in change_cols]
        df_change = df_change.melt(id_vars=[date_col], var_name='종목명', value_name='수량증감')
        
        df = pd.merge(df_weight, df_change, on=[date_col, '종목명'], how='left')
        
    else:
        df = raw_df.copy()
        date_col, name_col, weight_col = df.columns[0], df.columns[1], df.columns[2]
        df.columns = ['일자', '종목명', '비중']
        df['수량증감'] = "-" 
        date_col, name_col, weight_col = '일자', '종목명', '비중'

    df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
    df['비중'] = pd.to_numeric(df['비중'], errors='coerce')
    df = df.dropna(subset=['비중']).sort_values(by=df.columns[0])
    
    date_col_name = df.columns[0]
    name_col_name = '종목명'
    weight_col_name = '비중'
    
    df['순위'] = df.groupby(date_col_name)[weight_col_name].rank(method='min', ascending=False)

    latest_date_val = df[date_col_name].max()
    latest_order = df[df[date_col_name] == latest_date_val].sort_values(by=weight_col_name, ascending=False)[name_col_name].tolist()

    st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (상세 확대 모드)")

    fig = px.line(
        df, x=date_col_name, y=weight_col_name, color=name_col_name, markers=True,
        hover_name=name_col_name, category_orders={name_col_name: latest_order}, 
        hover_data={weight_col_name: True, '순위': True, '수량증감': True, date_col_name: False, name_col_name: False}
    )

    fig.update_layout(
        yaxis=dict(type="log", title="비중 (%)", tickvals=[1, 1.5, 2, 2.5, 3, 4, 5, 7, 10, 15, 20]),
        xaxis=dict(type="category", title="날짜"),
        height=800,
        legend=dict(title="종목명", orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        hovermode="closest",
        
        # =====================================================================
        # 💡 [가독성 극대화 패치] 마우스 올렸을 때 뜨는 라벨(Hover Label) 블랙&화이트 튜닝
        # =====================================================================
        hoverlabel=dict(
            bgcolor="white",       # 1. 라벨 배경색을 깨끗한 흰색(white)으로!
            font_size=13,          # 2. 글씨 크기는 보기 좋게 유지
            font_color="black",    # 3. [핵심] 글씨 색상을 가장 또렷한 검정색(black)으로!
            font_family="Malgun Gothic, sans-serif", # 4. 한글 폰트 지정 (깨짐 방지)
            bordercolor="#B0BEC5", # 5. 테두리는 은은하고 세련된 회색으로 장식
            align="left"           # 6. 글씨 왼쪽 정렬
        )
        # =====================================================================
    )
    st.plotly_chart(fig, use_container_width=True)
    st.info(f"✅ 총 {len(df[name_col_name].unique())}개 종목이 그래프에 표시되고 있습니다.")
    
    # =====================================================================
    # 💡 [핵심 패치] 차트 바로 밑에 '구글 시트 원본 뷰어'를 달아드렸습니다!
    # =====================================================================
    with st.expander("📊 구글 시트 원본 데이터 펴보기 (종목별 수량증감 상세 조회)"):
        st.markdown("**💡 구글 시트와 동일한 원본 데이터입니다. 표 안에서 스크롤하거나 우측 상단의 확대 버튼을 누르시면 더 크게 볼 수 있습니다.**")
        # 구글 시트 원본 형태(raw_df)를 그대로 예쁘게 그려줍니다.
        st.dataframe(raw_df, use_container_width=True, hide_index=True)

else:
    st.warning("데이터가 없습니다.")


# =====================================================================
# 📊 [자동화 엔진] 5영업일 누적 매집 찐 주도주 바 차트 (TIME / KoAct)
# =====================================================================
st.markdown("---")
st.header("🔥 최근 5영업일 누적 매집 찐 주도주 TOP 20")

time_records = []
koact_records = []

for etf_name, raw_df in etf_data.items():
    if "TIME" in etf_name or "타임" in etf_name:
        category = "TIME"
    elif "KoAct" in etf_name or "코액트" in etf_name:
        category = "KoAct"
    else:
        continue
        
    df = raw_df.copy()
    if len(df.columns) <= 3:
        continue 
        
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(by=date_col)
    
    if len(df) < 2: continue
        
    latest_date = df.iloc[-1][date_col].strftime('%Y-%m-%d')
    latest_row = df.iloc[-1]
    
    row_1d = df.iloc[-2] if len(df) >= 2 else df.iloc[0]
    row_3d = df.iloc[-4] if len(df) >= 4 else df.iloc[0]
    row_5d = df.iloc[-6] if len(df) >= 6 else df.iloc[0]
    
    etf_short = etf_name.replace('TIME ', '').replace('TIME', '').replace('KoAct ', '').replace('KoAct', '').strip()

    for col in df.columns[1:]: 
        if str(col).endswith('_증감'):
            continue

        l_val = pd.to_numeric(latest_row[col], errors='coerce'); l_val = l_val if pd.notna(l_val) else 0.0
        v_1d = pd.to_numeric(row_1d[col], errors='coerce'); v_1d = v_1d if pd.notna(v_1d) else 0.0
        v_3d = pd.to_numeric(row_3d[col], errors='coerce'); v_3d = v_3d if pd.notna(v_3d) else 0.0
        v_5d = pd.to_numeric(row_5d[col], errors='coerce'); v_5d = v_5d if pd.notna(v_5d) else 0.0
        
        diff_1d = l_val - v_1d
        diff_3d = l_val - v_3d
        diff_5d = l_val - v_5d
        
        if diff_5d > 0.001 or diff_1d > 0.001: 
            record = {
                '기준일자': latest_date, 
                '표시명': f"{col}<br>({etf_short})",
                '당일변화(%p)': round(diff_1d, 2),
                '3영업일변화(%p)': round(diff_3d, 2),
                '5영업일변화(%p)': round(diff_5d, 2)
            }
            if category == "TIME":
                time_records.append(record)
            else:
                koact_records.append(record)

def draw_top20_bar_chart(records, category_name, color_map):
    if not records: 
        st.info(f"{category_name} 데이터가 부족합니다.")
        return
    
    df_res = pd.DataFrame(records)
    df_res = df_res.sort_values(by='5영업일변화(%p)', ascending=False).head(20)
    date_str = df_res['기준일자'].iloc[0]
    
    df_melted = df_res.melt(
        id_vars=['표시명'], 
        value_vars=['5영업일변화(%p)', '3영업일변화(%p)', '당일변화(%p)'],
        var_name='기간', 
        value_name='비중증가(%p)'
    )
    
    title_emoji = "🔥" if category_name == "TIME" else "🌊"
    
    fig = px.bar(
        df_melted, x='표시명', y='비중증가(%p)', color='기간', barmode='group', text='비중증가(%p)',
        title=f"{title_emoji} [{category_name}] 5일 집중 매집 찐 주도주 TOP 20 ({date_str} 기준)",
        color_discrete_map=color_map
    )
    
    fig.update_layout(xaxis_title="", yaxis_title="비중 증가폭 (%p)", height=650, legend_title="매집 기간")
    fig.update_yaxes(zeroline=True, zerolinewidth=2, zerolinecolor='black')
    fig.update_traces(textposition='outside', textangle=-90, textfont_size=10)
    
    st.plotly_chart(fig, use_container_width=True)

color_time = {'5영업일변화(%p)': '#FFBB78', '3영업일변화(%p)': '#FF7F0E', '당일변화(%p)': '#D62728'}
draw_top20_bar_chart(time_records, "TIME", color_time)

st.markdown("<br><br>", unsafe_allow_html=True)

color_koact = {'5영업일변화(%p)': '#AEC7E8', '3영업일변화(%p)': '#1F77B4', '당일변화(%p)': '#17BECF'}
draw_top20_bar_chart(koact_records, "KoAct", color_koact)

# =====================================================================
# 📈 [퀀트 마스터 비서] 내 매입 종목 입체 분석 그래프 (완전 자동화)
# =====================================================================
import urllib.parse # 💡 한글 URL 번역기 마법사 출동!

st.markdown("---")
st.header("🦅 내 매입 종목 입체 분석 대시보드")
st.markdown("**💡 깃허브의 '매입장부.xlsx'를 실시간으로 읽어와 로봇이 그린 그래프를 띄워줍니다.**")

# 1. 깃허브 Raw 주소 기본 세팅
github_id = "carreras74" # 대표님 ID
repo_name = "ETF_Auto_Bot"
base_url = f"https://raw.githubusercontent.com/{github_id}/{repo_name}/main/"

# 2. [핵심] 한글 파일명을 인터넷이 읽을 수 있게 안전하게 번역!
safe_ledger_name = urllib.parse.quote("매입장부.xlsx")
ledger_url = f"{base_url}{safe_ledger_name}"

try:
    # 번역된 안전한 주소로 엑셀 읽어오기
    ledger_df = pd.read_excel(ledger_url)
    
    my_stocks = ledger_df['종목명'].dropna().unique().tolist()
    
    if my_stocks:
        stock_tabs = st.tabs([f"📈 {name}" for name in my_stocks])
        
        for i, tab in enumerate(stock_tabs):
            stock_name = my_stocks[i]
            
            # 사진 이름("삼성전자_분석.png")도 한글이므로 똑같이 안전하게 번역!
            safe_image_name = urllib.parse.quote(f"{stock_name}_분석.png")
            image_url = f"{base_url}{safe_image_name}"
            
            with tab:
                st.subheader(f"📊 {stock_name} - 주가 vs ETF 비중 추이")
                st.image(image_url, caption=f"🤖 {stock_name} 입체 분석 그래프 (매일 아침 7시 자동 업데이트)", use_container_width=True)
    else:
        st.info("💡 매입장부에 기록된 종목이 없습니다.")

except Exception as e:
    st.warning(f"⚠️ 깃허브에서 '매입장부.xlsx'를 아직 불러오지 못했습니다. 에러 상세 원인: {e}")

st.markdown("<br><br><br>", unsafe_allow_html=True)
