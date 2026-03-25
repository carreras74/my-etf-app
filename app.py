import streamlit as st
import gspread
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import urllib.parse
import re
import numpy as np

# =====================================================================
# 1. 페이지 설정 및 초기화
# =====================================================================
st.set_page_config(page_title="ETF 전종목 비중 추적", layout="wide")
st.title("📈 ETF 종목별 순위 변동 추이 (범프 차트)")

# 2. 구글 시트 연결 (스트림릿 클라우드 비밀금고 사용)
spreadsheet_id = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=7200) # 429 에러 방지를 위해 캐시 2시간 유지
def load_data_from_google():
    try:
        creds_json = json.loads(st.secrets["google_key"])
        gc = gspread.service_account_from_dict(creds_json)
        
        sh = gc.open_by_key(spreadsheet_id)
        worksheets = sh.worksheets()
        all_data = {ws.title: pd.DataFrame(ws.get_all_records()) for ws in worksheets if ws.get_all_records()}
        return all_data
    except Exception as e:
        if "429" in str(e):
            st.error("⚠️ 구글 시트 API 트래픽이 초과되었습니다(429 에러). 약 1~2분 뒤에 새로고침해 주세요.")
        else:
            st.error(f"데이터 로드 실패: {e}")
        return None

etf_data = load_data_from_google()

# 데이터 로드 실패 시 여기서 안전하게 정지 (하단 에러 방지)
if not etf_data:
    st.warning("데이터를 정상적으로 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()


# =====================================================================
# 🏁 [섹션 1: 범프 차트 - 종목별 순위 변동]
# =====================================================================
selected_etf = st.sidebar.selectbox("ETF 선택", list(etf_data.keys()))
st.sidebar.markdown("<br>" * 15, unsafe_allow_html=True)

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

df['순위'] = df.groupby(date_col_name)[weight_col_name].rank(method='first', ascending=False)

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

fig = px.line(
    df, x=date_col_name, y='순위', color=name_col_name, markers=True,
    hover_name=name_col_name, category_orders={name_col_name: latest_order}, 
    hover_data={
        '순위': False,            
        weight_col_name: True,    
        '수량증감': False,        
        '수량증감(주식수)': True,  
        '종가/등락률': True,      
        date_col_name: False,
        name_col_name: False
    }
)

fig.update_layout(
    yaxis=dict(title="종목 순위 (등수)", autorange="reversed", tickmode="linear", dtick=1, showgrid=False, zeroline=False, showticklabels=True),
    xaxis=dict(type="category", title="날짜", showgrid=False),
    height=800,
    legend=dict(title="종목명", orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
    hovermode="closest",
    hoverlabel=dict(bgcolor="white", font_size=13, font_color="black", font_family="Malgun Gothic, sans-serif", bordercolor="#B0BEC5", align="left")
)

st.plotly_chart(fig, use_container_width=True)
st.info(f"✅ 총 {len(df[name_col_name].unique())}개 종목이 그래프에 표시되고 있습니다.")

with st.expander("📊 구글 시트 원본 데이터 펴보기 (종목별 수량증감 상세 조회)"):
    st.markdown("**💡 구글 시트와 동일한 원본 데이터입니다. 표 안에서 스크롤하거나 우측 상단의 확대 버튼을 누르시면 더 크게 볼 수 있습니다.**")
    st.dataframe(raw_df, use_container_width=True, hide_index=True)


# =====================================================================
# 🔥 [섹션 2: 수급 격전지 찐 주도주 분석]
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
# 🦅 [섹션 3: 내 매입 종목 입체 분석 다이내믹 차트] 
# =====================================================================
st.markdown("---")
st.header("🦅 내 매입 종목 입체 분석 대시보드")
st.markdown("**💡 1층: 대장 ETF 비중 및 주가 / 2층: 16개 전체 ETF 합산 총 수량증감**")

github_id = "carreras74"
repo_name = "ETF_Auto_Bot"
base_url = f"https://raw.githubusercontent.com/{github_id}/{repo_name}/main/"
safe_ledger_name = urllib.parse.quote("매입장부.xlsx")
ledger_url = f"{base_url}{safe_ledger_name}"

try:
    ledger_df = pd.read_excel(ledger_url)
    my_stocks = ledger_df['종목명'].dropna().unique().tolist()
    
    has_buy_info = '매수일자' in ledger_df.columns and '매수단가' in ledger_df.columns
    
    if my_stocks and etf_data:
        stock_tabs = st.tabs([f"📈 {name}" for name in my_stocks])
        
        for i, tab in enumerate(stock_tabs):
            stock_name = my_stocks[i]
            
            with tab:
                buy_date, buy_price = None, None
                if has_buy_info:
                    row_data = ledger_df[ledger_df['종목명'] == stock_name]
                    if not row_data.empty:
                        b_date_val = row_data.iloc[0].get('매수일자')
                        b_price_val = row_data.iloc[0].get('매수단가')
                        
                        if pd.notna(b_date_val):
                            buy_date = pd.to_datetime(b_date_val).strftime('%Y-%m-%d')
                        if pd.notna(b_price_val):
                            if isinstance(b_price_val, str):
                                b_price_val = b_price_val.replace(',', '').replace('원', '').strip()
                            buy_price = float(b_price_val)

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
                    
                agg_data = {}
                
                for etf_name, df in etf_data.items():
                    if stock_name not in df.columns:
                        continue
                        
                    date_col = df.columns[0]
                    diff_col = f"{stock_name}_증감"
                    
                    for _, row in df.iterrows():
                        d = str(row[date_col]).strip()
                        if d not in agg_data:
                            agg_data[d] = {'Weight': 0.0, 'Price': np.nan, 'TotalQtyChange': 0}
                            
                        if etf_name == best_etf:
                            w = pd.to_numeric(row[stock_name], errors='coerce')
                            agg_data[d]['Weight'] = w if pd.notna(w) else 0.0
                            
                        diff_str = str(row[diff_col]) if diff_col in df.columns else ""
                        qty_change = 0
                        q_str = diff_str
                        
                        if " | " in diff_str:
                            parts = diff_str.split(" | ")
                            q_str = parts[0].strip()
                            p_str = parts[1].strip()
                            
                            match = re.search(r'₩([\d,]+)', p_str)
                            if match: agg_data[d]['Price'] = int(match.group(1).replace(',', ''))
                                
                        if '🔴▲' in q_str: qty_change = int(q_str.replace('🔴▲', '').replace(',', '').strip())
                        elif '🔵▼' in q_str: qty_change = -int(q_str.replace('🔵▼', '').replace(',', '').strip())
                                
                        agg_data[d]['TotalQtyChange'] += qty_change

                plot_data = [{'Date': k, 'Weight': v['Weight'], 'Price': v['Price'], 'QtyChange': v['TotalQtyChange']} for k, v in agg_data.items()]
                p_df = pd.DataFrame(plot_data)
                
                if p_df.empty:
                    st.info("차트를 그릴 데이터가 없습니다.")
                    continue
                
                p_df['DateObj'] = pd.to_datetime(p_df['Date'], errors='coerce')
                p_df = p_df.dropna(subset=['DateObj']).sort_values('DateObj')
                p_df['Date'] = p_df['DateObj'].dt.strftime('%Y-%m-%d')
                p_df = p_df.drop(columns=['DateObj'])
                
                p_df['Price'] = p_df['Price'].ffill().bfill()
                valid_p_df = p_df.dropna(subset=['Price'])
                
                st.subheader(f"📊 {stock_name} 입체 분석 (대장 비중: {best_etf} / 수량: 전체 합산)")
                
                fig = make_subplots(
                    rows=2, cols=1, 
                    shared_xaxes=True,
                    vertical_spacing=0.08,
                    row_heights=[0.7, 0.3],
                    specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
                )
                
                fig.update_xaxes(type='category')
                
                fig.add_trace(
                    go.Bar(x=p_df['Date'], y=p_df['Weight'], name=f'{best_etf} 비중(%)', opacity=0.5, marker_color='#AEC7E8', width=0.35),
                    row=1, col=1, secondary_y=False
                )
                
                fig.add_trace(
                    go.Scatter(x=valid_p_df['Date'], y=valid_p_df['Price'], name='주가(원)', mode='lines+markers', line=dict(color='#333333', width=3), marker=dict(size=6)),
                    row=1, col=1, secondary_y=True
                )
                
                colors = ['#FF4B4B' if q > 0 else '#1F77B4' if q < 0 else '#CCCCCC' for q in p_df['QtyChange']]
                fig.add_trace(
                    go.Bar(x=p_df['Date'], y=p_df['QtyChange'], name='전체 ETF 수량 합산', marker_color=colors, width=0.35),
                    row=2, col=1
                )
                
                if not p_df.empty:
                    if buy_price is not None:
                        fig.add_trace(
                            go.Scatter(
                                x=[p_df['Date'].iloc[0], p_df['Date'].iloc[-1]], 
                                y=[buy_price, buy_price], 
                                mode="lines+text", 
                                line=dict(color="#00C853", dash="dash", width=2),
                                name=f"내 평단가 ({buy_price:,.0f}원)",
                                text=[f"내 매수단가 ({buy_price:,.0f}원)", ""],
                                textposition="bottom right",
                                showlegend=False,
                                hoverinfo="skip"
                            ),
                            row=1, col=1, secondary_y=True
                        )
                    
                    if buy_date is not None and buy_date in p_df['Date'].values:
                        max_y = valid_p_df['Price'].max() if not valid_p_df.empty else 100000
                        min_y = valid_p_df['Price'].min() if not valid_p_df.empty else 0
                        margin = (max_y - min_y) * 0.1 if max_y != min_y else max_y * 0.1
                        
                        fig.add_trace(
                            go.Scatter(
                                x=[buy_date, buy_date], 
                                y=[min_y - margin, max_y + margin], 
                                mode="lines+text", 
                                line=dict(color="#00C853", dash="dash", width=2),
                                name="매수일자",
                                text=["매수타점", ""],
                                textposition="top right",
                                showlegend=False,
                                hoverinfo="skip"
                            ),
                            row=1, col=1, secondary_y=True
                        )

                fig.update_layout(
                    height=700,
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    plot_bgcolor='white', paper_bgcolor='white',
                    margin=dict(l=10, r=10, t=50, b=10)
                )
                
                fig.update_xaxes(showgrid=False)
                fig.update_yaxes(title_text="비중 (%)", secondary_y=False, row=1, col=1, showgrid=False, zeroline=False)
                fig.update_yaxes(title_text="주가 (원)", secondary_y=True, row=1, col=1, showgrid=True, gridcolor='#F0F0F0', zeroline=False)
                fig.update_yaxes(title_text="총 수량증감 (합산)", row=2, col=1, showgrid=True, gridcolor='#F0F0F0', zeroline=True, zerolinecolor='#E0E0E0')
                
                st.plotly_chart(fig, use_container_width=True)

except Exception as e:
    st.warning(f"⚠️ 매입장부 데이터를 불러오거나 처리하는 중 에러가 발생했습니다: {e}")

st.markdown("<br><br><br>", unsafe_allow_html=True)
