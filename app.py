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
    
    # =====================================================================
    # 💡 [UI/UX 디테일 패치] 사이드바 드롭다운 무조건 '아래로' 열리게 강제하기
    # 투명한 엔터키(<br>)를 15번 쳐서 아래 공간을 넉넉하게 확보해 줍니다!
    # =====================================================================
    st.sidebar.markdown("<br>" * 15, unsafe_allow_html=True)
    
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
    
    # 순위 계산 (그래프 내부 계산용으로만 남겨둡니다)
    # =====================================================================
    # 💡 [핵심 패치 1] 등수 세분화 및 겹침 방지 트릭
    # 동점일 때 'min'(공동등수) 대신 'first'(먼저 나온 놈이 위)를 써서
    # 모든 종목에 0.000...1 단위로라도 겹치지 않는 고유 순위를 부여합니다!
    # =====================================================================
    df['순위'] = df.groupby(date_col_name)[weight_col_name].rank(method='first', ascending=False)

    # 툴팁에 보여줄 데이터 준비 (아까 세팅 유지)
    def split_qty(val):
        return str(val).split(' | ')[0] if ' | ' in str(val) else str(val)

    def format_price(val):
        if ' | ' not in str(val): return "-"
        price_str = str(val).split(' | ')[1]
        if '(+' in price_str:
            return f"<span style='color:red'><b>{price_str}</b></span>"
        elif '(-' in price_str:
            return f"<span style='color:blue'><b>{price_str}</b></span>"
        else:
            return price_str

    df['수량증감(주식수)'] = df['수량증감'].apply(split_qty)
    df['종가/등락률'] = df['수량증감'].apply(format_price)

    latest_date_val = df[date_col_name].max()
    latest_order = df[df[date_col_name] == latest_date_val].sort_values(by=weight_col_name, ascending=False)[name_col_name].tolist()

    st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (상세 확대 모드)")

    # (차트 그리는 부분은 동일 유지)
    fig = px.line(
        df, x=date_col_name, y='순위', color=name_col_name, markers=True,
        hover_name=name_col_name, category_orders={name_col_name: latest_order}, 
        hover_data={
            '순위': False,            
            weight_col_name: True,    
            '수량증감': False,        
            '수량증감(주식수)': True,  # 💡 [여기!] 아까 잘못 들어갔던 '탭' 글자를 뺐습니다!
            '종가/등락률': True,      
            date_col_name: False,
            name_col_name: False
        }
    )

    fig.update_layout(
        # 💡 핵심 2: Y축 디자인 완벽 개조 (그리드 선 제거!)
        yaxis=dict(
            title="종목 순위 (등수)", 
            autorange="reversed", # 1등이 맨 위로
            tickmode="linear",    # 소수점 없애기 (1, 2, 3...)
            dtick=1,               # 1 단위로 간격 설정
            
            # 💡 [가독성 패치] 흐릿한 베이스 선(그리드)을 싹 지워버립니다!
            showgrid=False,       # Y축 수평선 숨기기
            zeroline=False,       # 제로 라인 숨기기
            showticklabels=True   # ❌ Y축 숫자(등수)는 유지!
        ),
        xaxis=dict(
            type="category", 
            title="날짜",
            # (보너스: X축 세로선도 지우면 더 깔끔합니다!)
            showgrid=False        # X축 수직선 숨기기
        ),
        height=800,
        legend=dict(title="종목명", orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        hovermode="closest",
        
        # (깔끔한 화이트 라벨 유지)
        hoverlabel=dict(
            bgcolor="white",       
            font_size=13,
            font_color="black",    
            font_family="Malgun Gothic, sans-serif",
            bordercolor="#B0BEC5", 
            align="left"
        )
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
# 📈 [퀀트 마스터 비서] 내 매입 종목 입체 분석 다이내믹 차트 (HTS 모드)
# =====================================================================
import urllib.parse
import re
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.markdown("---")
st.header("🦅 내 매입 종목 입체 분석 대시보드")
st.markdown("**💡 앱이 구글 시트를 읽어와 주가, 비중, 수량증감을 HTS급 2층 차트로 그립니다.**")

github_id = "carreras74" # 대표님 ID
repo_name = "ETF_Auto_Bot"
base_url = f"https://raw.githubusercontent.com/{github_id}/{repo_name}/main/"
safe_ledger_name = urllib.parse.quote("매입장부.xlsx")
ledger_url = f"{base_url}{safe_ledger_name}"

try:
    ledger_df = pd.read_excel(ledger_url)
    my_stocks = ledger_df['종목명'].dropna().unique().tolist()
    
    # 장부에 매수일자, 매수단가 열이 있는지 확인
    has_buy_info = '매수일자' in ledger_df.columns and '매수단가' in ledger_df.columns
    
    if my_stocks and etf_data:
        stock_tabs = st.tabs([f"📈 {name}" for name in my_stocks])
        
        for i, tab in enumerate(stock_tabs):
            stock_name = my_stocks[i]
            
            with tab:
                # 1. 내 매수 타점 정보 가져오기
                buy_date, buy_price = None, None
                if has_buy_info:
                    row_data = ledger_df[ledger_df['종목명'] == stock_name]
                    if not row_data.empty:
                        b_date_val = row_data.iloc[0].get('매수일자')
                        b_price_val = row_data.iloc[0].get('매수단가')
                        if pd.notna(b_date_val):
                            buy_date = pd.to_datetime(b_date_val).strftime('%Y-%m-%d')
                        if pd.notna(b_price_val):
                            buy_price = float(b_price_val)

                # 2. 대장 ETF 찾기
                best_etf = None
                max_weight = -1
                for etf_name, df in etf_data.items():
                    if stock_name in df.columns:
                        m_weight = pd.to_numeric(df[stock_name], errors='coerce').max()
                        if m_weight > max_weight:
                            max_weight = m_weight; best_etf = etf_name
                            
                if not best_etf:
                    st.warning(f"'{stock_name}' 종목은 현재 추적 중인 ETF에 존재하지 않습니다.")
                    continue
                    
                # 3. 데이터 정제
                target_df = etf_data[best_etf].copy()
                date_col = target_df.columns[0]
                diff_col = f"{stock_name}_증감"
                
                plot_data = []
                for _, row in target_df.iterrows():
                    d = row[date_col]
                    w = pd.to_numeric(row[stock_name], errors='coerce')
                    w = w if pd.notna(w) else 0.0
                    
                    diff_str = str(row[diff_col]) if diff_col in target_df.columns else ""
                    
                    price = None
                    qty_change = 0
                    if " | " in diff_str:
                        parts = diff_str.split(" | ")
                        q_str = parts[0].strip()
                        p_str = parts[1].strip()
                        
                        match = re.search(r'₩([\d,]+)', p_str)
                        if match: price = int(match.group(1).replace(',', ''))
                            
                        if '🔴▲' in q_str: qty_change = int(q_str.replace('🔴▲', '').replace(',', '').strip())
                        elif '🔵▼' in q_str: qty_change = -int(q_str.replace('🔵▼', '').replace(',', '').strip())
                            
                    plot_data.append({'Date': d, 'Weight': w, 'Price': price, 'QtyChange': qty_change})
                    
                p_df = pd.DataFrame(plot_data)
                p_df['Date'] = pd.to_datetime(p_df['Date']).dt.strftime('%Y-%m-%d')
                
                st.subheader(f"📊 {stock_name} 입체 분석 (추적: {best_etf})")
                
                # 4. HTS급 2층 차트 렌더링
                fig = make_subplots(
                    rows=2, cols=1, 
                    shared_xaxes=True,           # 1층, 2층 X축(날짜) 동기화!
                    vertical_spacing=0.08,       # 1층과 2층 사이 간격
                    row_heights=[0.7, 0.3],      # 1층(주가/비중) 70%, 2층(수량) 30%
                    specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
                )
                
                # [1층] ETF 비중 막대 (얇게)
                fig.add_trace(
                    go.Bar(x=p_df['Date'], y=p_df['Weight'], name='ETF 내 비중(%)', opacity=0.5, marker_color='#AEC7E8', width=0.35),
                    row=1, col=1, secondary_y=False
                )
                
                # [1층] 주가 꺾은선
                fig.add_trace(
                    go.Scatter(x=p_df['Date'], y=p_df['Price'], name='주가(원)', mode='lines+markers', line=dict(color='#333333', width=3), marker=dict(size=6), connectgaps=True),
                    row=1, col=1, secondary_y=True
                )
                
                # [2층] 수량증감 막대 (상승=빨강, 하락=파랑)
                colors = ['#FF4B4B' if q > 0 else '#1F77B4' if q < 0 else '#CCCCCC' for q in p_df['QtyChange']]
                fig.add_trace(
                    go.Bar(x=p_df['Date'], y=p_df['QtyChange'], name='ETF 수량증감', marker_color=colors, width=0.35),
                    row=2, col=1
                )
                
                # [십자선 마법] 내 매수단가 및 일자 표시 (초록색 점선)
                if buy_price is not None:
                    fig.add_hline(y=buy_price, line_dash="dash", line_color="#00C853", line_width=2, 
                                  annotation_text=f"내 매수단가 ({buy_price:,.0f}원)", annotation_position="top left", 
                                  row=1, col=1, secondary_y=True)
                if buy_date is not None and buy_date in p_df['Date'].values:
                    fig.add_vline(x=buy_date, line_dash="dash", line_color="#00C853", line_width=2, 
                                  annotation_text="매수타점", annotation_position="top right", 
                                  row=1, col=1)

                fig.update_layout(
                    height=700,
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    plot_bgcolor='white', paper_bgcolor='white',
                    margin=dict(l=10, r=10, t=50, b=10)
                )
                
                # 축 설정 (주말 빈칸 삭제 및 그리드 디자인)
                fig.update_xaxes(type='category', showgrid=False)
                fig.update_yaxes(title_text="비중 (%)", secondary_y=False, row=1, col=1, showgrid=False, zeroline=False)
                fig.update_yaxes(title_text="주가 (원)", secondary_y=True, row=1, col=1, showgrid=True, gridcolor='#F0F0F0', zeroline=False)
                fig.update_yaxes(title_text="수량증감", row=2, col=1, showgrid=True, gridcolor='#F0F0F0', zeroline=True, zerolinecolor='#E0E0E0')
                
                st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.warning(f"⚠️ 매입장부 데이터를 불러오는 중 에러가 발생했습니다: {e}")

st.markdown("<br><br><br>", unsafe_allow_html=True)
