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
# 1. 페이지 설정 및 다크모드 강제 적용 CSS
# =====================================================================
st.set_page_config(page_title="ETF 전종목 비중 추적", layout="wide")

st.markdown("""
<style>
    .stApp { background-color: #121212; color: #E0E0E0; }
    h1, h2, h3, h4, h5, h6, p, div, span { color: #E0E0E0 !important; }
    .streamlit-expanderHeader { background-color: #1E1E1E !important; color: #FFFFFF !important; }
    .streamlit-expanderContent { background-color: #121212 !important; }
</style>
""", unsafe_allow_html=True)

st.title("📈 ETF 종목별 순위 변동 추이 (범프 차트)")

# 2. 구글 시트 연결 (스트림릿 클라우드 비밀금고 사용)
spreadsheet_id = "1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA"

@st.cache_data(ttl=7200)
def load_data_from_google():
    try:
        creds_json = json.loads(st.secrets["google_key"])
        gc = gspread.service_account_from_dict(creds_json)
        
        sh = gc.open_by_key(spreadsheet_id)
        worksheets = sh.worksheets()
        all_data = {ws.title: pd.DataFrame(ws.get_all_records()) for ws in worksheets if ws.get_all_records()}
        return all_data
    except Exception as e:
        if "429" in str(e): st.error("⚠️ 구글 시트 API 트래픽 초과(429 에러). 약 1~2분 뒤 새로고침해 주세요.")
        else: st.error(f"데이터 로드 실패: {e}")
        return None

etf_data = load_data_from_google()
if not etf_data:
    st.warning("데이터를 정상적으로 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()

# =====================================================================
# 💡 전역 데이터 다이어트 (최근 20영업일 데이터만 유지!)
# =====================================================================
for etf_name, df in etf_data.items():
    if len(df.columns) > 0:
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col]).sort_values(by=date_col)
        df = df.tail(20)
        df[date_col] = df[date_col].dt.strftime('%Y-%m-%d')
        etf_data[etf_name] = df


# 3. 매입장부 데이터 로드
@st.cache_data(ttl=600)
def load_ledger_data():
    try:
        github_id = "carreras74"
        repo_name = "ETF_Auto_Bot"
        base_url = f"https://raw.githubusercontent.com/{github_id}/{repo_name}/main/"
        safe_ledger_name = urllib.parse.quote("매입장부.xlsx")
        ledger_url = f"{base_url}{safe_ledger_name}"
        return pd.read_excel(ledger_url)
    except:
        return pd.DataFrame()

ledger_df = load_ledger_data()

# =====================================================================
# 💡 3단 입체 분석 차트 만능 함수 
# =====================================================================
def render_stock_3d_chart(stock_name, etf_data, ledger_df, unique_key):
    buy_date, buy_price = None, None
    has_buy_info = not ledger_df.empty and '매수일자' in ledger_df.columns and '매수단가' in ledger_df.columns
    
    if has_buy_info:
        row_data = ledger_df[ledger_df['종목명'] == stock_name]
        if not row_data.empty:
            b_date_val, b_price_val = row_data.iloc[0].get('매수일자'), row_data.iloc[0].get('매수단가')
            if pd.notna(b_date_val): buy_date = pd.to_datetime(b_date_val).strftime('%Y-%m-%d')
            if pd.notna(b_price_val):
                if isinstance(b_price_val, str): b_price_val = b_price_val.replace(',', '').replace('원', '').strip()
                buy_price = float(b_price_val)

    best_etf, max_weight = None, -1
    for etf_name, df in etf_data.items():
        if stock_name in df.columns:
            m_weight = pd.to_numeric(df[stock_name], errors='coerce').max()
            if m_weight > max_weight: max_weight, best_etf = m_weight, etf_name
                
    if not best_etf:
        st.warning(f"'{stock_name}' 종목은 현재 추적 중인 ETF에 존재하지 않습니다.")
        return
        
    agg_data = {}
    for etf_name, df in etf_data.items():
        if stock_name not in df.columns: continue
            
        date_col, diff_col = df.columns[0], f"{stock_name}_증감"
        
        for _, row in df.iterrows():
            d = str(row[date_col]).strip()
            if d not in agg_data:
                agg_data[d] = {'Weight': 0.0, 'Price': np.nan, 'TotalQtyChange': 0, 'TotalAmtChange': 0.0}
                
            if etf_name == best_etf:
                w = pd.to_numeric(row[stock_name], errors='coerce')
                agg_data[d]['Weight'] = w if pd.notna(w) else 0.0
                
            diff_str = str(row[diff_col]) if diff_col in df.columns else ""
            qty_change, price = 0, 0
            
            if " | " in diff_str:
                parts = diff_str.split(" | ")
                q_str, p_str = parts[0].strip(), parts[1].strip()
                match = re.search(r'₩([\d,]+)', p_str)
                if match: 
                    price = int(match.group(1).replace(',', ''))
                    agg_data[d]['Price'] = price 
                    
                if '🔴▲' in q_str: qty_change = int(q_str.replace('🔴▲', '').replace(',', '').strip())
                elif '🔵▼' in q_str: qty_change = -int(q_str.replace('🔵▼', '').replace(',', '').strip())
                    
            agg_data[d]['TotalQtyChange'] += qty_change
            agg_data[d]['TotalAmtChange'] += (qty_change * price) / 1000000.0

    p_df = pd.DataFrame([{'Date': k, 'Weight': v['Weight'], 'Price': v['Price'], 'QtyChange': v['TotalQtyChange'], 'AmtChange': v['TotalAmtChange']} for k, v in agg_data.items()])
    if p_df.empty: return
    
    p_df['DateObj'] = pd.to_datetime(p_df['Date'], errors='coerce')
    p_df = p_df.dropna(subset=['DateObj']).sort_values('DateObj')
    p_df['Date'] = p_df['DateObj'].dt.strftime('%Y-%m-%d')
    p_df = p_df.drop(columns=['DateObj'])
    p_df['Price'] = p_df['Price'].ffill().bfill()
    valid_p_df = p_df.dropna(subset=['Price'])
    
    st.subheader(f"📊 {stock_name} 정밀 분석 (1층: 주가 / 2층: 수량증감 / 3층: 금액증감)")
    
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.5, 0.25, 0.25], specs=[[{"secondary_y": True}], [{"secondary_y": False}], [{"secondary_y": False}]]
    )
    
    fig.update_xaxes(type='category')
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['Weight'], name=f'{best_etf} 비중(%)', opacity=0.3, marker_color='#82B1FF', width=0.35), row=1, col=1, secondary_y=False)
    
    fig.add_trace(go.Scatter(x=valid_p_df['Date'], y=valid_p_df['Price'], name='주가(원)', mode='lines+markers', line=dict(color='#FFCA28', width=3), marker=dict(size=6, color='#FFCA28')), row=1, col=1, secondary_y=True)
    
    colors = ['#FF5252' if q > 0 else '#448AFF' if q < 0 else '#555555' for q in p_df['QtyChange']]
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['QtyChange'], name='수량 증감(주)', marker_color=colors, width=0.4), row=2, col=1)
    
    text_amt = p_df['AmtChange'].apply(lambda x: f"{x:,.0f}M" if x != 0 else "")
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['AmtChange'], name='순매수 금액(백만)', marker_color=colors, width=0.4, text=text_amt, textposition='outside', textfont=dict(color='white', size=10)), row=3, col=1)
    
    if not p_df.empty:
        if buy_price is not None:
            fig.add_trace(go.Scatter(x=[p_df['Date'].iloc[0], p_df['Date'].iloc[-1]], y=[buy_price, buy_price], mode="lines+text", line=dict(color="#00E676", dash="dash", width=2), name=f"내 평단가 ({buy_price:,.0f}원)", text=[f"내 매수단가 ({buy_price:,.0f}원)", ""], textposition="bottom right", showlegend=False, hoverinfo="skip"), row=1, col=1, secondary_y=True)
        if buy_date is not None and buy_date in p_df['Date'].values:
            max_y, min_y = (valid_p_df['Price'].max(), valid_p_df['Price'].min()) if not valid_p_df.empty else (100000, 0)
            margin = (max_y - min_y) * 0.1 if max_y != min_y else max_y * 0.1
            fig.add_trace(go.Scatter(x=[buy_date, buy_date], y=[min_y - margin, max_y + margin], mode="lines+text", line=dict(color="#00E676", dash="dash", width=2), name="매수일자", text=["매수타점", ""], textposition="top right", showlegend=False, hoverinfo="skip"), row=1, col=1, secondary_y=True)

    fig.update_layout(
        height=850, template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212',
        hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1), margin=dict(l=10, r=10, t=50, b=10)
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(title_text="비중 (%)", secondary_y=False, row=1, col=1, showgrid=False, zeroline=False)
    fig.update_yaxes(title_text="주가 (원)", secondary_y=True, row=1, col=1, showgrid=True, gridcolor='#333333', zeroline=False)
    fig.update_yaxes(title_text="수량증감(주)", row=2, col=1, showgrid=True, gridcolor='#333333', zeroline=True, zerolinecolor='#555555')
    fig.update_yaxes(title_text="매수금액(백만)", row=3, col=1, showgrid=True, gridcolor='#333333', zeroline=True, zerolinecolor='#555555')
    
    st.plotly_chart(fig, use_container_width=True, key=f"3d_chart_{unique_key}_{stock_name}")


# =====================================================================
# 🏁 [섹션 1: 범프 차트 - 종목별 순위 변동]
# =====================================================================
selected_etf = st.sidebar.selectbox("ETF 선택", list(etf_data.keys()))
st.sidebar.markdown("<br>" * 15, unsafe_allow_html=True)

raw_df = etf_data[selected_etf].copy()

if len(raw_df.columns) > 3:
    date_col = raw_df.columns[0]
    stock_cols = [c for c in raw_df.columns if c != date_col and not str(c).endswith('_증감')]
    df_weight = raw_df[[date_col] + stock_cols].copy().melt(id_vars=[date_col], var_name='종목명', value_name='비중')
    change_cols = [f"{c}_증감" for c in stock_cols if f"{c}_증감" in raw_df.columns]
    df_change = raw_df[[date_col] + change_cols].copy()
    df_change.columns = [date_col] + [c.replace('_증감', '') for c in change_cols]
    df_change = df_change.melt(id_vars=[date_col], var_name='종목명', value_name='수량증감')
    df = pd.merge(df_weight, df_change, on=[date_col, '종목명'], how='left')
else:
    df = raw_df.copy()
    df.columns = ['일자', '종목명', '비중']
    df['수량증감'] = "-" 

df[df.columns[0]] = pd.to_datetime(df[df.columns[0]])
df['비중'] = pd.to_numeric(df['비중'], errors='coerce')
df = df.dropna(subset=['비중']).sort_values(by=df.columns[0])

date_col_name, name_col_name, weight_col_name = df.columns[0], '종목명', '비중'

# 💡 [패치 1] X축 날짜를 '월-일' 형식으로 변경 (예: 03-26)
df[date_col_name] = df[date_col_name].dt.strftime('%m-%d')

df['순위'] = df.groupby(date_col_name)[weight_col_name].rank(method='first', ascending=False)

def split_qty(val): return str(val).split(' | ')[0] if ' | ' in str(val) else str(val)
def format_price(val):
    if ' | ' not in str(val): return "-"
    price_str = str(val).split(' | ')[1]
    if '(+' in price_str: return f"<span style='color:#FF5252'><b>{price_str}</b></span>"
    elif '(-' in price_str: return f"<span style='color:#448AFF'><b>{price_str}</b></span>"
    else: return price_str

df['수량증감(주식수)'] = df['수량증감'].apply(split_qty)
df['종가/등락률'] = df['수량증감'].apply(format_price)

# 💡 [패치 2] 오른쪽 범례를 '종목명(비중)' 형태로 변경 (% 기호 제거)
last_weights = df.groupby(name_col_name)[weight_col_name].last()
df['종목표시명'] = df.apply(lambda r: f"{r[name_col_name]}({last_weights[r[name_col_name]]})", axis=1)

latest_date_val = df[date_col_name].max()
latest_order = df[df[date_col_name] == latest_date_val].sort_values(by=weight_col_name, ascending=False)['종목표시명'].tolist()

st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (최근 20영업일)")

fig = px.line(
    df, x=date_col_name, y='순위', color='종목표시명', markers=True,
    hover_name='종목표시명', category_orders={'종목표시명': latest_order}, 
    hover_data={'순위': False, weight_col_name: True, '수량증감': False, '수량증감(주식수)': True, '종가/등락률': True, date_col_name: False, '종목표시명': False}
)

fig.update_layout(
    template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212',
    yaxis=dict(title="종목 순위 (등수)", autorange="reversed", tickmode="linear", dtick=1, showgrid=False, zeroline=False),
    xaxis=dict(type="category", title="날짜 (월-일)", showgrid=False), height=800,
    # 💡 [패치 3] 맨 위 범례 타이틀을 '종목명(%)'로 변경
    legend=dict(title="종목명(%)", orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02), hovermode="closest",
    hoverlabel=dict(bgcolor="#2A2A2A", font_size=13, font_color="white", bordercolor="#444444", align="left")
)

st.plotly_chart(fig, use_container_width=True, key="main_bump_chart")
st.info(f"✅ 총 {len(df[name_col_name].unique())}개 종목이 최근 20일간의 그래프에 표시되고 있습니다.")

with st.expander("📊 구글 시트 원본 데이터 펴보기 (종목별 수량증감 상세 조회)"):
    st.markdown("**💡 구글 시트와 동일한 원본 데이터입니다. 표 안에서 스크롤하거나 우측 상단의 확대 버튼을 누르시면 더 크게 볼 수 있습니다.**")
    st.dataframe(raw_df, use_container_width=True, hide_index=True)


# =====================================================================
# 🔥 [섹션 2: 수급 격전지 찐 주도주 분석]
# =====================================================================
st.markdown("---")
st.header("🔥 최근 5영업일 누적 순매수 찐 주도주 TOP 20 (단위: 백만원)")

time_records, koact_records = [], []

for etf_name, raw_df in etf_data.items():
    if "TIME" in etf_name or "타임" in etf_name: category = "TIME"
    elif "KoAct" in etf_name or "코액트" in etf_name: category = "KoAct"
    else: continue
        
    df = raw_df.copy()
    if len(df.columns) <= 3: continue 
        
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(by=date_col)
    
    if len(df) == 0: continue
        
    recent_df = df.tail(5)
    last_1_date = df.iloc[-1][date_col] if len(df) >= 1 else None
    last_3_dates = df[date_col].tail(3).tolist() if len(df) >= 3 else df[date_col].tolist()
    last_5_dates = df[date_col].tail(5).tolist() if len(df) >= 5 else df[date_col].tolist()
    latest_date_str = last_1_date.strftime('%Y-%m-%d') if last_1_date else "N/A"
    
    etf_short = etf_name.replace('TIME ', '').replace('TIME', '').replace('KoAct ', '').replace('KoAct', '').strip()
    change_cols = [c for c in df.columns if str(c).endswith('_증감')]

    for col in change_cols:
        stock_name = col.replace('_증감', '')
        key = f"{stock_name}<br>({etf_short})"
        amt_1d, amt_3d, amt_5d = 0.0, 0.0, 0.0

        for _, row in recent_df.iterrows():
            r_date, val_str = row[date_col], row[col]
            qty, price = 0, 0
            
            if isinstance(val_str, str) and " | " in val_str:
                parts = val_str.split(" | ")
                q_str, p_str = parts[0].strip(), parts[1].strip()
                if '🔴▲' in q_str: qty = int(q_str.replace('🔴▲', '').replace(',', '').strip())
                elif '🔵▼' in q_str: qty = -int(q_str.replace('🔵▼', '').replace(',', '').strip())
                match = re.search(r'₩([\d,]+)', p_str)
                if match: price = int(match.group(1).replace(',', ''))

            daily_amt = (qty * price) / 1000000.0
            if r_date in last_5_dates: amt_5d += daily_amt
            if r_date in last_3_dates: amt_3d += daily_amt
            if r_date == last_1_date: amt_1d += daily_amt
        
        if amt_5d > 0 or amt_1d > 0: 
            record = {
                '기준일자': latest_date_str, '표시명': key, '종목명': stock_name, 'ETF명': etf_name,
                '당일매수(백만)': round(amt_1d, 1), '3일매수(백만)': round(amt_3d, 1), '5일매수(백만)': round(amt_5d, 1)
            }
            if category == "TIME": time_records.append(record)
            else: koact_records.append(record)

def draw_top20_bar_chart(records, category_name, color_map):
    if not records: return pd.DataFrame()
    
    df_res = pd.DataFrame(records).sort_values(by='5일매수(백만)', ascending=False).head(20)
    date_str = df_res['기준일자'].iloc[0]
    df_melted = df_res.melt(id_vars=['표시명'], value_vars=['5일매수(백만)', '3일매수(백만)', '당일매수(백만)'], var_name='기간', value_name='순매수금액')
    
    fig = px.bar(
        df_melted, x='표시명', y='순매수금액', color='기간', barmode='group', text='순매수금액',
        title=f"🔥 [{category_name}] 5일 누적 순매수 찐 주도주 TOP 20 ({date_str} 기준)", color_discrete_map=color_map
    )
    
    fig.update_layout(
        template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212',
        xaxis_title="", yaxis_title="순매수 금액 (백만원)", height=650, legend_title="매집 기간"
    )
    fig.update_yaxes(zeroline=True, zerolinewidth=2, zerolinecolor='#666666', gridcolor='#333333')
    fig.update_traces(textposition='outside', textangle=-90, textfont_size=10, texttemplate='%{text:,.0f}')
    
    st.plotly_chart(fig, use_container_width=True, key=f"bar_chart_{category_name}")
    return df_res

# --- TIME 분석 ---
color_time = {'5일매수(백만)': '#FFBB78', '3일매수(백만)': '#FF7F0E', '당일매수(백만)': '#D62728'}
top20_time_df = draw_top20_bar_chart(time_records, "TIME", color_time)

if not top20_time_df.empty:
    with st.expander("🦅 [히든 대시보드] TIME TOP 20 찐 주도주 입체 분석 차트 열어보기"):
        time_top20_stocks = top20_time_df['종목명'].unique().tolist()
        if time_top20_stocks:
            tabs = st.tabs([f"📈 {s}" for s in time_top20_stocks])
            for i, tab in enumerate(tabs):
                with tab: render_stock_3d_chart(time_top20_stocks[i], etf_data, ledger_df, "time")

st.markdown("<br><br>", unsafe_allow_html=True)

# --- KoAct 분석 ---
color_koact = {'5일매수(백만)': '#AEC7E8', '3일매수(백만)': '#1F77B4', '당일매수(백만)': '#17BECF'}
top20_koact_df = draw_top20_bar_chart(koact_records, "KoAct", color_koact)

if not top20_koact_df.empty:
    with st.expander("🦅 [히든 대시보드] KoAct TOP 20 찐 주도주 입체 분석 차트 열어보기"):
        koact_top20_stocks = top20_koact_df['종목명'].unique().tolist()
        if koact_top20_stocks:
            tabs = st.tabs([f"📈 {s}" for s in koact_top20_stocks])
            for i, tab in enumerate(tabs):
                with tab: render_stock_3d_chart(koact_top20_stocks[i], etf_data, ledger_df, "koact")


# =====================================================================
# 🕵️‍♂️ [섹션 2-1: TOP 20 한 달 상세 거래 장부]
# =====================================================================
top20_combined = pd.concat([top20_time_df, top20_koact_df])

if not top20_combined.empty:
    with st.expander("🔍 [히든 데이터베이스] 위 TOP 20 찐 주도주들의 한 달(최근 20일) 상세 거래 장부 열어보기"):
        history_list = []
        for _, row in top20_combined.iterrows():
            s_name, e_name = row['종목명'], row['ETF명']
            if e_name in etf_data:
                df_raw = etf_data[e_name].copy()
                date_col = df_raw.columns[0]
                df_raw[date_col] = pd.to_datetime(df_raw[date_col])
                df_raw = df_raw.sort_values(by=date_col).tail(20) 
                
                col_name = f"{s_name}_증감"
                if col_name in df_raw.columns:
                    for _, r in df_raw.iterrows():
                        date_str, val_str = r[date_col].strftime('%Y-%m-%d'), r[col_name]
                        qty, price, q_str_disp, p_str_disp = 0, 0, "-", "-"
                        
                        if isinstance(val_str, str) and " | " in val_str:
                            parts = val_str.split(" | ")
                            q_str_disp, p_str_disp = parts[0].strip(), parts[1].strip()
                            if '🔴▲' in q_str_disp: qty = int(q_str_disp.replace('🔴▲', '').replace(',', '').strip())
                            elif '🔵▼' in q_str_disp: qty = -int(q_str_disp.replace('🔵▼', '').replace(',', '').strip())
                            match = re.search(r'₩([\d,]+)', p_str_disp)
                            if match: price = int(match.group(1).replace(',', ''))
                                
                        daily_amt = (qty * price) / 1000000.0 if price > 0 else 0.0
                        if qty != 0:
                            history_list.append({
                                '일자': date_str, '운용사(ETF)': e_name.replace('TIME ', 'TIME').replace('KoAct ', 'KoAct'),
                                '종목명': s_name, '매수/매도 수량': q_str_disp, '당일 종가': p_str_disp, '순매수액(백만원)': round(daily_amt, 1)
                            })
                            
        if history_list:
            hist_df = pd.DataFrame(history_list).sort_values(by=['일자', '순매수액(백만원)'], ascending=[False, False])
            st.dataframe(hist_df, use_container_width=True, hide_index=True)


# =====================================================================
# 🦅 [섹션 3: 내 매입 종목 입체 분석 대시보드] 
# =====================================================================
st.markdown("---")
st.header("🦅 내 매입 종목 입체 분석 대시보드")

with st.expander("🦅 [히든 대시보드] 내 매입 종목 정밀 입체 분석 차트 열어보기"):
    try:
        if not ledger_df.empty:
            my_stocks = ledger_df['종목명'].dropna().unique().tolist()
            if my_stocks and etf_data:
                stock_tabs = st.tabs([f"📈 {name}" for name in my_stocks])
                for i, tab in enumerate(stock_tabs):
                    with tab: render_stock_3d_chart(my_stocks[i], etf_data, ledger_df, "mystocks")
            else:
                st.info("매입장부에 추적할 종목이 없거나 ETF 데이터를 불러오지 못했습니다.")
        else:
            st.warning("⚠️ 매입장부(매입장부.xlsx)를 찾을 수 없거나 데이터가 비어 있습니다.")
    except Exception as e:
        st.warning(f"⚠️ 매입장부 데이터를 처리하는 중 에러가 발생했습니다: {e}")

st.markdown("<br><br><br>", unsafe_allow_html=True)
