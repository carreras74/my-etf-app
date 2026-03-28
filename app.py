import os
if not os.path.exists('.streamlit'):
    os.makedirs('.streamlit')
with open('.streamlit/config.toml', 'w') as f:
    f.write('[theme]\nbase="dark"\nprimaryColor="#82B1FF"\nbackgroundColor="#121212"\nsecondaryBackgroundColor="#1E1E1E"\ntextColor="#FFFFFF"\n')

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
import datetime
import pytz
import io

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

# 2. 구글 시트 연결
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
        if "429" in str(e): st.error("⚠️ 구글 시트 API 트래픽 초과. 잠시 후 새로고침해 주세요.")
        else: st.error(f"데이터 로드 실패: {e}")
        return None

etf_data = load_data_from_google()
if not etf_data:
    st.warning("데이터를 정상적으로 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
    st.stop()

kst = pytz.timezone('Asia/Seoul')
today_kst = datetime.datetime.now(kst).date()
latest_dates_in_db = []
all_stocks_set = set()

for etf_name, df in etf_data.items():
    if len(df.columns) > 0:
        for col in df.columns[1:]:
            if not str(col).endswith('_증감'):
                all_stocks_set.add(str(col))
                
        date_col = df.columns[0]
        df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
        df = df.dropna(subset=[date_col]).sort_values(by=date_col)
        
        if not df.empty:
            latest_dates_in_db.append(df[date_col].max().date())
            
        df = df.tail(20)
        df[date_col] = df[date_col].dt.strftime('%Y-%m-%d')
        etf_data[etf_name] = df

all_stocks_list = sorted(list(all_stocks_set))

if latest_dates_in_db:
    overall_latest_date = max(latest_dates_in_db)
    if overall_latest_date < today_kst and today_kst.weekday() < 5:
        st.warning(f"⚠️ 오늘({today_kst.strftime('%m월 %d일')}) 데이터가 아직 구글 시트에 반영되지 않았습니다. {overall_latest_date.strftime('%m월 %d일')}까지의 데이터를 표시합니다.")
    elif overall_latest_date == today_kst:
        st.success(f"✅ 오늘({today_kst.strftime('%m월 %d일')}) 최신 데이터가 성공적으로 반영되었습니다!")

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

base_ledger_df = load_ledger_data()

# =====================================================================
# 💡 2단 입체 분석 차트
# =====================================================================
def render_stock_3d_chart(stock_name, etf_data, ledger_df, unique_key):
    buy_date, buy_price = None, None
    has_buy_info = not ledger_df.empty and '매수일자' in ledger_df.columns and '매수단가' in ledger_df.columns
    
    if has_buy_info:
        row_data = ledger_df[ledger_df['종목명'] == stock_name]
        if not row_data.empty:
            b_date_val, b_price_val = row_data.iloc[0].get('매수일자'), row_data.iloc[0].get('매수단가')
            if pd.notna(b_date_val): buy_date = pd.to_datetime(b_date_val).strftime('%m-%d')
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
    p_df['Date'] = p_df['DateObj'].dt.strftime('%m-%d')
    p_df = p_df.drop(columns=['DateObj'])
    p_df['Price'] = p_df['Price'].ffill().bfill()
    p_df['AmtChange'] = p_df['AmtChange'].round(0)
    valid_p_df = p_df.dropna(subset=['Price'])
    
    st.subheader(f"📊 {stock_name} 정밀 분석 (1층: 주가&비중 / 2층: 매수금액&수량)")
    
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.6, 0.4], specs=[[{"secondary_y": True}], [{"secondary_y": True}]]
    )
    
    fig.update_xaxes(type='category')
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['Weight'], name=f'{best_etf} 비중(%)', opacity=0.3, marker_color='#82B1FF', width=0.35, hovertemplate='%{x}<br>비중: %{y:.2f}%<extra></extra>'), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=valid_p_df['Date'], y=valid_p_df['Price'], name='주가(원)', mode='lines+markers', line=dict(color='#FFCA28', width=3), marker=dict(size=6, color='#FFCA28'), hovertemplate='%{x}<br>주가: %{y:,.0f}원<extra></extra>'), row=1, col=1, secondary_y=True)
    
    colors = ['#FF5252' if q > 0 else '#448AFF' if q < 0 else '#555555' for q in p_df['QtyChange']]
    text_amt = p_df['AmtChange'].apply(lambda x: f"{x:,.0f}M" if x != 0 else "")
    
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['AmtChange'], name='순매수 금액(백만)', marker_color=colors, width=0.35, offsetgroup=1, customdata=p_df['QtyChange'], text=text_amt, textposition='outside', textfont=dict(color='white', size=10), hovertemplate='%{x}<br>순매수: %{y:,.0f} 백만원<br>수량: %{customdata:,.0f} 주<extra></extra>'), row=2, col=1, secondary_y=False)
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['QtyChange'], name='수량 증감(주)', marker_color=colors, width=0.35, offsetgroup=2, opacity=0.7, hoverinfo='skip'), row=2, col=1, secondary_y=True)
    
    if not p_df.empty:
        if buy_price is not None:
            fig.add_trace(go.Scatter(x=[p_df['Date'].iloc[0], p_df['Date'].iloc[-1]], y=[buy_price, buy_price], mode="lines+text", line=dict(color="#00E676", dash="dash", width=2), name=f"내 평단가 ({buy_price:,.0f}원)", text=[f"매수단가 ({buy_price:,.0f}원)", ""], textposition="bottom right", showlegend=False, hoverinfo="skip"), row=1, col=1, secondary_y=True)
        if buy_date is not None and buy_date in p_df['Date'].values:
            max_y, min_y = (valid_p_df['Price'].max(), valid_p_df['Price'].min()) if not valid_p_df.empty else (100000, 0)
            margin = (max_y - min_y) * 0.1 if max_y != min_y else max_y * 0.1
            fig.add_trace(go.Scatter(x=[buy_date, buy_date], y=[min_y - margin, max_y + margin], mode="lines+text", line=dict(color="#00E676", dash="dash", width=2), name="매수일자", text=["매수타점", ""], textposition="top right", showlegend=False, hoverinfo="skip"), row=1, col=1, secondary_y=True)

    fig.update_layout(
        font=dict(color="#FFFFFF"), height=750, template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212',
        hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color="#FFFFFF")), margin=dict(l=10, r=10, t=50, b=10), barmode='group'
    )
    
    fig.update_xaxes(showgrid=False, color="#FFFFFF")
    fig.update_yaxes(title_text="비중 (%)", secondary_y=False, row=1, col=1, showgrid=False, zeroline=False, color="#FFFFFF")
    fig.update_yaxes(title_text="주가 (원)", secondary_y=True, row=1, col=1, showgrid=True, gridcolor='#333333', zeroline=False, color="#FFFFFF")
    fig.update_yaxes(title_text="매수금액(백만)", secondary_y=False, row=2, col=1, showgrid=True, gridcolor='#333333', zeroline=True, zerolinecolor='#555555', color="#FFFFFF")
    fig.update_yaxes(title_text="수량증감(주)", secondary_y=True, row=2, col=1, showgrid=False, zeroline=True, zerolinecolor='#555555', color="#FFFFFF")
    
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
df[date_col_name] = df[date_col_name].dt.strftime('%m-%d')
df['순위'] = df.groupby(date_col_name)[weight_col_name].rank(method='first', ascending=False)

def split_qty(val): return str(val).split(' | ')[0] if ' | ' in str(val) else str(val)
def format_price(val):
    if ' | ' not in str(val): return "-"
    price_str = str(val).split(' | ')[1]
    return f"<span style='color:#FF5252'><b>{price_str}</b></span>" if '(+' in price_str else f"<span style='color:#448AFF'><b>{price_str}</b></span>" if '(-' in price_str else price_str

df['수량증감(주식수)'] = df['수량증감'].apply(split_qty)
df['종가/등락률'] = df['수량증감'].apply(format_price)

last_weights = df.groupby(name_col_name)[weight_col_name].last()
df['종목표시명'] = df.apply(lambda r: f"{r[name_col_name]}({last_weights[r[name_col_name]]})", axis=1)

latest_date_val = df[date_col_name].max()
latest_order = df[df[date_col_name] == latest_date_val].sort_values(by=weight_col_name, ascending=False)['종목표시명'].tolist()

st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (최근 20영업일)")

fig = px.line(df, x=date_col_name, y='순위', color='종목표시명', markers=True, hover_name='종목표시명', category_orders={'종목표시명': latest_order}, hover_data={'순위': False, weight_col_name: True, '수량증감': False, '수량증감(주식수)': True, '종가/등락률': True, date_col_name: False, '종목표시명': False})
fig.update_layout(font=dict(color="#FFFFFF"), template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212', yaxis=dict(title="종목 순위 (등수)", autorange="reversed", tickmode="linear", dtick=1, showgrid=False, zeroline=False, color="#FFFFFF"), xaxis=dict(type="category", title="날짜 (월-일)", showgrid=False, color="#FFFFFF"), height=800, legend=dict(title=dict(text="종목명(%)", font=dict(color="#FFFFFF")), font=dict(color="#FFFFFF", size=13), orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02), hovermode="closest", hoverlabel=dict(bgcolor="#2A2A2A", font_size=13, font_color="white", bordercolor="#444444", align="left"))
st.plotly_chart(fig, use_container_width=True, key="main_bump_chart")


# =====================================================================
# 🔥 [섹션 2: 수급 격전지 찐 주도주 분석]
# =====================================================================
st.markdown("---")
st.header("🔥 최근 5영업일 누적 순매수 찐 주도주 TOP 20 (단위: 백만원)")

# 💡 [핵심 패치 1] 운용사별로 데이터를 담을 임시 저장소
merged_data = {"TIME": [], "KoAct": [], "TIGER": []}

for etf_name, raw_df in etf_data.items():
    if "TIME" in etf_name or "타임" in etf_name: cat = "TIME"
    elif "KoAct" in etf_name or "코액트" in etf_name: cat = "KoAct"
    elif "TIGER" in etf_name or "타이거" in etf_name: cat = "TIGER"
    else: continue
        
    df = raw_df.copy()
    if len(df.columns) <= 3: continue 
        
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(by=date_col)
    
    recent_df = df.tail(5)
    last_1_date = df.iloc[-1][date_col] if len(df) >= 1 else None
    last_3_dates = df[date_col].tail(3).tolist()
    last_5_dates = df[date_col].tail(5).tolist()
    latest_date_str = last_1_date.strftime('%Y-%m-%d') if last_1_date else "N/A"
    
    change_cols = [c for c in df.columns if str(c).endswith('_증감')]

    for col in change_cols:
        stock_name = col.replace('_증감', '')
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
        
        if amt_5d != 0 or amt_1d != 0: 
            merged_data[cat].append({
                '기준일자': latest_date_str, '종목명': stock_name,
                '당일매수(백만)': amt_1d, '3일매수(백만)': amt_3d, '5일매수(백만)': amt_5d
            })

def draw_merged_top20(category_records, category_name, color_map):
    if not category_records: return pd.DataFrame()
    
    # 💡 [핵심 패치 2] 같은 운용사 내의 동일 종목명을 하나로 합칩니다(Groupby)
    full_df = pd.DataFrame(category_records)
    grouped = full_df.groupby('종목명').agg({
        '기준일자': 'first',
        '당일매수(백만)': 'sum',
        '3일매수(백만)': 'sum',
        '5일매수(백만)': 'sum'
    }).reset_index()
    
    # 5일 누적 순매수 기준 정렬 및 TOP 20 추출
    res_df = grouped.sort_values(by='5일매수(백만)', ascending=False).head(20)
    date_str = res_df['기준일자'].iloc[0]
    
    melted = res_df.melt(id_vars=['종목명'], value_vars=['5일매수(백만)', '3일매수(백만)', '당일매수(백만)'], var_name='기간', value_name='순매수금액')
    fig = px.bar(melted, x='종목명', y='순매수금액', color='기간', barmode='group', text='순매수금액', title=f"🔥 [{category_name}] 5일 누적 종목 통합 TOP 20 ({date_str} 기준)", color_discrete_map=color_map)
    fig.update_layout(font=dict(color="#FFFFFF"), template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212', xaxis_title="", yaxis_title="합산 순매수 금액 (백만원)", height=650)
    fig.update_traces(textposition='outside', textangle=-90, textfont_size=10, texttemplate='%{text:,.1f}')
    st.plotly_chart(fig, use_container_width=True, key=f"bar_{category_name}")
    return res_df

# TIME (주황) / KoAct (파랑) / TIGER (초록) 차트 출력
t20_time = draw_merged_top20(merged_data["TIME"], "TIME", {'5일매수(백만)': '#FFBB78', '3일매수(백만)': '#FF7F0E', '당일매수(백만)': '#D62728'})
if not t20_time.empty:
    with st.expander("🦅 [히든 대시보드] TIME 통합 TOP 20 입체 분석"):
        stocks = t20_time['종목명'].tolist()
        tabs = st.tabs([f"📈 {s}" for s in stocks])
        for i, tab in enumerate(tabs):
            with tab: render_stock_3d_chart(stocks[i], etf_data, base_ledger_df, f"t_{i}")

st.markdown("<br>", unsafe_allow_html=True)
t20_koact = draw_merged_top20(merged_data["KoAct"], "KoAct", {'5일매수(백만)': '#AEC7E8', '3일매수(백만)': '#1F77B4', '당일매수(백만)': '#17BECF'})
if not t20_koact.empty:
    with st.expander("🦅 [히든 대시보드] KoAct 통합 TOP 20 입체 분석"):
        stocks = t20_koact['종목명'].tolist()
        tabs = st.tabs([f"📈 {s}" for s in stocks])
        for i, tab in enumerate(tabs):
            with tab: render_stock_3d_chart(stocks[i], etf_data, base_ledger_df, f"k_{i}")

st.markdown("<br>", unsafe_allow_html=True)
t20_tiger = draw_merged_top20(merged_data["TIGER"], "TIGER", {'5일매수(백만)': '#C5E1A5', '3일매수(백만)': '#8BC34A', '당일매수(백만)': '#33691E'})
if not t20_tiger.empty:
    with st.expander("🦅 [히든 대시보드] TIGER 통합 TOP 20 입체 분석"):
        stocks = t20_tiger['종목명'].tolist()
        tabs = st.tabs([f"📈 {s}" for s in stocks])
        for i, tab in enumerate(tabs):
            with tab: render_stock_3d_chart(stocks[i], etf_data, base_ledger_df, f"tg_{i}")

# =====================================================================
# 🕵️‍♂️ [섹션 2-1: 상세 거래 장부]
# =====================================================================
st.markdown("---")
with st.expander("🔍 [히든 데이터베이스] TOP 20 종목들의 개별 ETF 거래 장부 (어느 ETF가 샀나?)"):
    top20_all = pd.concat([t20_time, t20_koact, t20_tiger])['종목명'].unique()
    h_list = []
    for etf_name, df_raw in etf_data.items():
        d_col = df_raw.columns[0]
        df_proc = df_raw.tail(20)
        for s_name in top20_all:
            c_col = f"{s_name}_증감"
            if c_col in df_proc.columns:
                for _, r in df_proc.iterrows():
                    v = r[c_col]
                    if isinstance(v, str) and " | " in v:
                        q_s, p_s = v.split(" | ")[0], v.split(" | ")[1]
                        qty = 0
                        if '🔴▲' in q_s: qty = int(q_s.replace('🔴▲', '').replace(',', ''))
                        elif '🔵▼' in q_s: qty = -int(q_s.replace('🔵▼', '').replace(',', ''))
                        match = re.search(r'₩([\d,]+)', p_s)
                        price = int(match.group(1).replace(',', '')) if match else 0
                        if qty != 0:
                            h_list.append({
                                '일자': r[d_col], '운용사(ETF)': etf_name, '종목명': s_name, 
                                '매수/매도': q_s, '금액(백만)': round((qty*price)/1000000.0, 1), '종가': p_s
                            })
    if h_list:
        st.dataframe(pd.DataFrame(h_list).sort_values(['일자', '금액(백만)'], ascending=[False, False]), use_container_width=True, hide_index=True)

# =====================================================================
# 🦅 [섹션 3: 내 관심/매입 종목 입체 분석]
# =====================================================================
st.markdown("---")
st.header("🦅 내 관심/매입 종목 정밀 입체 분석 대시보드")
with st.expander("🦅 [히든 대시보드] 내가 원하는 종목을 골라서 분석 차트 열어보기", expanded=True):
    default_stocks = [s for s in (base_ledger_df['종목명'].dropna().unique().tolist() if not base_ledger_df.empty else []) if s in all_stocks_list]
    c1, c2 = st.columns([2, 1])
    with c1: user_selected = st.multiselect("🔍 종목 선택:", options=all_stocks_list, default=default_stocks)
    with c2: 
        uploaded = st.file_uploader("📁 '매입장부.xlsx' 업로드", type=["xlsx"])
        output = io.BytesIO()
        pd.DataFrame([['삼성전자', '2024-03-26', '75000']], columns=['종목명', '매수일자', '매수단가']).to_excel(output, index=False)
        st.download_button("📥 양식 다운로드", data=output.getvalue(), file_name="매입장부_양식.xlsx")
    
    curr_ledger = pd.read_excel(uploaded) if uploaded else base_ledger_df
    final_stocks = list(dict.fromkeys(user_selected))
    if final_stocks:
        tabs = st.tabs([f"📈 {n}" for n in final_stocks])
        for i, tab in enumerate(tabs):
            with tab: render_stock_3d_chart(final_stocks[i], etf_data, curr_ledger, f"custom_{i}")
