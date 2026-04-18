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

# =====================================================================
# 💡 핵심 수정 파트: 시트 데이터 분리 및 15일 자르기 로직 예외 처리
# =====================================================================
qty_backup_df = etf_data.get("수량백업(봇전용)", pd.DataFrame()).copy()
pullback_df_raw = etf_data.get("관심종목", pd.DataFrame()).copy()

kst = pytz.timezone('Asia/Seoul')
today_kst = datetime.datetime.now(kst).date()
latest_dates_in_db = []
all_stocks_set = set()

filtered_etf_data = {}
for etf_name, df in etf_data.items():
    if "수량백업" in etf_name or "TIGER" in etf_name or "타이거" in etf_name or "관심종목" in etf_name: 
        continue
    filtered_etf_data[etf_name] = df

etf_data = filtered_etf_data

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
            
        df = df.tail(15)
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
# 💡 2단 입체 분석 차트 함수
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
        if "수량백업" in etf_name: continue
        if stock_name in df.columns:
            m_weight = pd.to_numeric(df[stock_name], errors='coerce').max()
            if m_weight > max_weight: max_weight, best_etf = m_weight, etf_name
                
    if not best_etf:
        st.warning(f"'{stock_name}' 종목은 현재 추적 중인 ETF에 존재하지 않습니다.")
        return
        
    agg_data = {}
    for etf_name, df in etf_data.items():
        if "수량백업" in etf_name: continue
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
    p_df['AmtChange'] = p_df['AmtChange'].round(1)
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
    text_amt = p_df['AmtChange'].apply(lambda x: f"{x:,.1f}M" if x != 0 else "")
    
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['AmtChange'], name='순매수 금액(백만)', marker_color=colors, width=0.35, offsetgroup=1, customdata=p_df['QtyChange'], text=text_amt, textposition='outside', textfont=dict(color='white', size=10), hovertemplate='%{x}<br>순매수: %{y:,.1f} 백만원<br>수량: %{customdata:,.0f} 주<extra></extra>'), row=2, col=1, secondary_y=False)
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
valid_etfs = list(etf_data.keys())
if not valid_etfs:
    st.warning("분석할 ETF 데이터가 없습니다. 구글 시트를 확인해 주세요.")
    st.stop()
    
selected_etf = st.sidebar.selectbox("ETF 선택", valid_etfs)
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

ordered_dates = df[date_col_name].unique().tolist()

num_stocks_main = len(latest_order)
dynamic_height_main = max(800, num_stocks_main * 25 + 100) 

st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (최근 15영업일)")

fig = px.line(df, x=date_col_name, y='순위', color='종목표시명', markers=True, hover_name='종목표시명', 
              category_orders={'종목표시명': latest_order, date_col_name: ordered_dates}, 
              hover_data={'순위': False, weight_col_name: True, '수량증감': False, '수량증감(주식수)': True, '종가/등락률': True, date_col_name: False, '종목표시명': False})
fig.update_layout(
    font=dict(color="#FFFFFF"), template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212', 
    height=dynamic_height_main,
    yaxis=dict(title="종목 순위 (등수)", autorange="reversed", tickmode="linear", dtick=1, showgrid=False, zeroline=False, color="#FFFFFF"), 
    xaxis=dict(type="category", title="날짜 (월-일)", showgrid=False, color="#FFFFFF"), 
    legend=dict(title=dict(text="종목명(%)", font=dict(color="#FFFFFF")), font=dict(color="#FFFFFF", size=13), orientation="v", yanchor="top", y=1, xanchor="left", x=1.02), 
    hovermode="closest", hoverlabel=dict(bgcolor="#2A2A2A", font_size=13, font_color="white", bordercolor="#444444", align="left")
)
st.plotly_chart(fig, use_container_width=True, key="main_bump_chart")

# =====================================================================
# 💡 선택한 ETF 구글 시트 원본 데이터 테이블
# =====================================================================
st.markdown("<br>", unsafe_allow_html=True)
with st.expander(f"📋 [{selected_etf}] 구글 시트 원본 장부 확인하기", expanded=True):
    display_df = raw_df.copy()
    st.dataframe(display_df.sort_values(by=display_df.columns[0], ascending=False), use_container_width=True, hide_index=True)


# =====================================================================
# 🔥 [추가 기능] 15일 누적 수급 로테이션 범프 차트 그리기 엔진
# =====================================================================
def draw_momentum_bump_chart(target_cat, etf_dict, backup_df):
    
    latest_prices = {}
    for etf_name, df_raw in etf_dict.items():
        if target_cat == "TIME" and not ("TIME" in etf_name or "타임" in etf_name): continue
        if target_cat == "KoAct" and not ("KoAct" in etf_name or "코액트" in etf_name): continue
        if len(df_raw) == 0: continue
        
        last_row = df_raw.iloc[-1]
        change_cols = [c for c in df_raw.columns if str(c).endswith('_증감')]
        for col in change_cols:
            stock_name = col.replace('_증감', '')
            v = last_row.get(col, "")
            if isinstance(v, str) and " | " in v:
                p_s = v.split(" | ")[1].strip()
                match = re.search(r'₩([\d,]+)', p_s)
                if match:
                    latest_prices[stock_name] = int(match.group(1).replace(',', ''))

    brand_current_qty = {}
    if not backup_df.empty and 'ETF' in backup_df.columns and '종목명' in backup_df.columns and '수량' in backup_df.columns:
        for _, row in backup_df.iterrows():
            etf_val = str(row['ETF'])
            stock_val = str(row['종목명'])
            qty_val = row['수량']
            try: qty_val = int(float(str(qty_val).replace(',', '')))
            except: qty_val = 0
            
            if target_cat == "TIME" and ("TIME" in etf_val or "타임" in etf_val):
                brand_current_qty[stock_val] = brand_current_qty.get(stock_val, 0) + qty_val
            elif target_cat == "KoAct" and ("KoAct" in etf_val or "코액트" in etf_val):
                brand_current_qty[stock_val] = brand_current_qty.get(stock_val, 0) + qty_val

    all_records = []
    for etf_name, df_raw in etf_dict.items():
        if target_cat == "TIME" and ("TIME" in etf_name or "타임" in etf_name): pass
        elif target_cat == "KoAct" and ("KoAct" in etf_name or "코액트" in etf_name): pass
        else: continue
            
        if len(df_raw.columns) <= 3: continue
        date_col = df_raw.columns[0]
        change_cols = [c for c in df_raw.columns if str(c).endswith('_증감')]
        
        for _, r in df_raw.iterrows():
            d_val = r[date_col]
            for col in change_cols:
                stock_name = col.replace('_증감', '')
                v = r[col]
                if isinstance(v, str) and " | " in v:
                    qty, price = 0, 0
                    parts = v.split(" | ")
                    q_s, p_s = parts[0].strip(), parts[1].strip()
                    
                    if '🔴▲' in q_s: qty = int(q_s.replace('🔴▲', '').replace(',', '').strip())
                    elif '🔵▼' in q_s: qty = -int(q_s.replace('🔵▼', '').replace(',', '').strip())
                    
                    match = re.search(r'₩([\d,]+)', p_s)
                    if match: price = int(match.group(1).replace(',', ''))
                        
                    if qty != 0 or price != 0:
                        amt = (qty * price) / 1000000.0
                        all_records.append({'Date': d_val, 'Stock': stock_name, 'Amt': amt, 'Qty': qty, 'Price': price})
                        
    if not all_records: return
    
    df_records = pd.DataFrame(all_records)
    df_records['Date'] = pd.to_datetime(df_records['Date'])
    
    daily_sum = df_records.groupby(['Date', 'Stock']).agg({'Amt': 'sum', 'Qty': 'sum', 'Price': 'max'}).reset_index()
    
    df_prices = daily_sum[daily_sum['Price'] > 0][['Date', 'Stock', 'Price']]
    price_matrix = df_prices.pivot(index='Date', columns='Stock', values='Price')
    qty_change_matrix = daily_sum.pivot(index='Date', columns='Stock', values='Qty').fillna(0)
    
    all_dates_asc = sorted(list(set(price_matrix.index) | set(qty_change_matrix.index)))
    price_matrix = price_matrix.reindex(all_dates_asc)
    qty_change_matrix = qty_change_matrix.reindex(all_dates_asc).fillna(0)
    
    for s in brand_current_qty.keys():
        if s not in qty_change_matrix.columns: qty_change_matrix[s] = 0
        if s not in price_matrix.columns: price_matrix[s] = np.nan
        
    price_matrix = price_matrix.ffill().bfill()
    for s in price_matrix.columns:
        price_matrix[s] = price_matrix[s].fillna(latest_prices.get(s, 0))

    qty_matrix = pd.DataFrame(index=all_dates_asc, columns=qty_change_matrix.columns)
    temp_qty = {s: brand_current_qty.get(s, 0) for s in qty_change_matrix.columns}
    
    for d in reversed(all_dates_asc):
        for s in qty_change_matrix.columns:
            qty_matrix.loc[d, s] = temp_qty[s]
        for s in qty_change_matrix.columns:
            temp_qty[s] -= qty_change_matrix.loc[d, s]
            
    common_cols = list(set(price_matrix.columns) & set(qty_matrix.columns))
    total_val_matrix = (qty_matrix[common_cols] * price_matrix[common_cols]) / 1000000.0
    total_val_matrix.index.name = 'Date' 
    
    pivot_amt = daily_sum.pivot(index='Date', columns='Stock', values='Amt').fillna(0).sort_index()
    rolling_5d_amt = pivot_amt.rolling(window=5, min_periods=1).sum()
    
    target_universe = set()
    for date in rolling_5d_amt.index:
        daily_top10 = rolling_5d_amt.loc[date].nlargest(10).index.tolist()
        target_universe.update(daily_top10)
        
    if not target_universe: return
    
    safe_universe = [s for s in target_universe if s in total_val_matrix.columns]
    universe_val = total_val_matrix[safe_universe].reset_index().melt(id_vars='Date', var_name='Stock', value_name='Total_Value')
    long_df = universe_val.copy()
    long_df['Total_Value'] = long_df['Total_Value'].astype(float)
    
    long_df['Rank'] = long_df.groupby('Date')['Total_Value'].rank(method='first', ascending=False)
    long_df['Date_str'] = long_df['Date'].dt.strftime('%m-%d')
    long_df = long_df.sort_values(['Date', 'Rank'])
    
    long_df = pd.merge(long_df, daily_sum[['Date', 'Stock', 'Amt', 'Qty']], on=['Date', 'Stock'], how='left').fillna({'Amt':0, 'Qty':0})
    
    def format_qty_str(qty):
        if pd.isna(qty) or qty == 0: return "0"
        if qty > 0: return f"🔴▲ {int(qty):,}"
        else: return f"🔵▼ {abs(int(qty)):,}"
        
    long_df['당일 수량(주)'] = long_df['Qty'].apply(format_qty_str)
    long_df['당일 순매수(백만)'] = long_df['Amt']
    
    long_df['현재 보유량(주)'] = long_df.apply(lambda r: f"{int(qty_matrix.loc[r['Date'], r['Stock']]):,}", axis=1)
    long_df['보유총액(백만)'] = long_df['Total_Value']
    
    latest_date_val = long_df['Date'].max()
    latest_order = long_df[long_df['Date'] == latest_date_val].sort_values(by='Rank')['Stock'].tolist()
    
    ordered_dates_mom = long_df['Date_str'].unique().tolist()
    
    num_stocks_mom = len(latest_order)
    dynamic_height_mom = max(650, num_stocks_mom * 25 + 100)
    
    fig = px.line(
        long_df, 
        x='Date_str', 
        y='Rank', 
        color='Stock', 
        markers=True,
        category_orders={'Stock': latest_order, 'Date_str': ordered_dates_mom}, 
        hover_data={
            'Rank': True,
            '보유총액(백만)': ':,.1f',
            '현재 보유량(주)': True,
            '당일 순매수(백만)': ':,.1f',
            '당일 수량(주)': True, 
            'Date_str': False
        },
        title=f"🏆 [{target_cat}] 찐 주도주 15일 수급 로테이션 (<b>5일 누적 순매수 Top 10</b> 종목의 <b>보유총액</b> 순위)"
    )
    
    fig.update_yaxes(autorange="reversed", title="순위 (보유총액 기준)")
    fig.update_xaxes(title="날짜 (월-일)", type='category')
    fig.update_traces(line=dict(width=3), marker=dict(size=8))
    
    fig.update_layout(
        font=dict(color="#FFFFFF"), template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212',
        height=dynamic_height_mom,
        hovermode="closest", 
        legend=dict(title_text='주도주 라인업', yanchor="top", y=1, xanchor="left", x=1.02)
    )
    
    st.plotly_chart(fig, use_container_width=True, key=f"momentum_bump_{target_cat}")


# =====================================================================
# 🔥 [섹션 2: 수급 격전지 찐 주도주 분석]
# =====================================================================
st.markdown("---")
st.header("🔥 수급 격전지: 누적 및 당일 찐 주도주 & 역(逆) 주도주 (단위: 백만원)")

merged_data = {"TIME": [], "KoAct": []}

for etf_name, raw_df_loop in etf_data.items():
    if "TIME" in etf_name or "타임" in etf_name: cat = "TIME"
    elif "KoAct" in etf_name or "코액트" in etf_name: cat = "KoAct"
    else: continue
        
    df_loop = raw_df_loop.copy()
    if len(df_loop.columns) <= 3: continue 
        
    date_col = df_loop.columns[0]
    df_loop[date_col] = pd.to_datetime(df_loop[date_col])
    df_loop = df_loop.sort_values(by=date_col)
    
    recent_df = df_loop.tail(5)
    last_1_date = df_loop.iloc[-1][date_col] if len(df_loop) >= 1 else None
    last_3_dates = df_loop[date_col].tail(3).tolist()
    last_5_dates = df_loop[date_col].tail(5).tolist()
    latest_date_str = last_1_date.strftime('%Y-%m-%d') if last_1_date else "N/A"
    
    change_cols = [c for c in df_loop.columns if str(c).endswith('_증감')]

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

# 💡 1. 상위(5일 누적 순매수) 막대그래프 그리기 엔진
def draw_merged_top20(category_records, category_name, color_map):
    if not category_records:
        st.info(f"💡 [{category_name}] 분석할 누적 순매수 데이터가 없습니다.")
        return pd.DataFrame()
        
    full_df = pd.DataFrame(category_records)
    grouped = full_df.groupby('종목명').agg({
        '기준일자': 'first',
        '당일매수(백만)': 'sum',
        '3일매수(백만)': 'sum',
        '5일매수(백만)': 'sum'
    }).reset_index()
    grouped['5일매수(백만)'] = grouped['5일매수(백만)'].round(1)
    grouped['3일매수(백만)'] = grouped['3일매수(백만)'].round(1)
    grouped['당일매수(백만)'] = grouped['당일매수(백만)'].round(1)
    
    date_str = grouped['기준일자'].iloc[0]
    res_df = grouped.sort_values(by='5일매수(백만)', ascending=False).head(20)
    
    if res_df.empty or res_df['5일매수(백만)'].max() <= 0:
        st.info(f"💡 [{category_name}] {date_str} 기준 5일 누적 순매수(양수)가 발생한 종목이 없습니다.")
        return res_df
        
    melted = res_df.melt(id_vars=['종목명'], value_vars=['5일매수(백만)', '3일매수(백만)', '당일매수(백만)'], var_name='기간', value_name='순매수금액')
    fig = px.bar(melted, x='종목명', y='순매수금액', color='기간', barmode='group', text='순매수금액', title=f"🔥 [{category_name}] 5일 누적 순매수 TOP 20 ({date_str} 기준)", color_discrete_map=color_map)
    fig.update_layout(font=dict(color="#FFFFFF"), template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212', xaxis_title="", yaxis_title="합산 순매수 금액 (백만원)", height=600)
    fig.update_traces(textposition='outside', textangle=-90, textfont_size=10, texttemplate='%{text:,.1f}')
    st.plotly_chart(fig, use_container_width=True, key=f"bar_top_{category_name}")
    return res_df

# 💡 2. 하위(5일 누적 순매도) 막대그래프 그리기 엔진
def draw_merged_bottom20(category_records, category_name, color_map):
    if not category_records:
        return pd.DataFrame()
        
    full_df = pd.DataFrame(category_records)
    grouped = full_df.groupby('종목명').agg({
        '기준일자': 'first',
        '당일매수(백만)': 'sum',
        '3일매수(백만)': 'sum',
        '5일매수(백만)': 'sum'
    }).reset_index()
    grouped['5일매수(백만)'] = grouped['5일매수(백만)'].round(1)
    grouped['3일매수(백만)'] = grouped['3일매수(백만)'].round(1)
    grouped['당일매수(백만)'] = grouped['당일매수(백만)'].round(1)
    
    date_str = grouped['기준일자'].iloc[0]
    res_df = grouped.sort_values(by='5일매수(백만)', ascending=True).head(20)
    res_df = res_df[res_df['5일매수(백만)'] < 0] 
    
    if res_df.empty:
        st.info(f"💡 [{category_name}] {date_str} 기준 5일 누적 순매도가 발생한 종목이 없습니다.")
        return res_df
        
    melted = res_df.melt(id_vars=['종목명'], value_vars=['5일매수(백만)', '3일매수(백만)', '당일매수(백만)'], var_name='기간', value_name='순매수금액')
    fig = px.bar(melted, x='종목명', y='순매수금액', color='기간', barmode='group', text='순매수금액', title=f"❄️ [{category_name}] 5일 누적 순매도 TOP 20 ({date_str} 기준)", color_discrete_map=color_map)
    fig.update_layout(font=dict(color="#FFFFFF"), template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212', xaxis_title="", yaxis_title="합산 순매도 금액 (백만원)", height=600)
    fig.update_traces(textposition='outside', textangle=-90, textfont_size=10, texttemplate='%{text:,.1f}')
    st.plotly_chart(fig, use_container_width=True, key=f"bar_bottom_{category_name}")
    return res_df

# 💡 3. [개선 완료] 당일 순매수 TOP 15 안내 메시지 표시 로직
def draw_daily_top15(category_records, category_name, color):
    if not category_records:
        return pd.DataFrame()
        
    full_df = pd.DataFrame(category_records)
    grouped = full_df.groupby('종목명').agg({
        '기준일자': 'first',
        '당일매수(백만)': 'sum'
    }).reset_index()
    grouped['당일매수(백만)'] = grouped['당일매수(백만)'].round(1)
    
    date_str = grouped['기준일자'].iloc[0]
    res_df = grouped[grouped['당일매수(백만)'] > 0].sort_values(by='당일매수(백만)', ascending=False).head(15)
    
    # 🔥 차트를 그릴 종목이 없으면, 사용자에게 사유를 정확하게 알려줍니다.
    if res_df.empty: 
        st.info(f"💡 [{category_name}] {date_str} 기준 당일 합산 순매수(금액 > 0)가 발생한 종목이 없습니다 (전량 매도 또는 관망).")
        return res_df
    
    fig = px.bar(res_df, x='종목명', y='당일매수(백만)', text='당일매수(백만)', title=f"🚀 [{category_name}] 당일 합산 순매수 TOP 15 ({date_str} 기준)")
    fig.update_layout(font=dict(color="#FFFFFF"), template="plotly_dark", plot_bgcolor='#121212', paper_bgcolor='#121212', xaxis_title="", yaxis_title="당일 순매수 금액 (백만원)", height=500)
    fig.update_traces(marker_color=color, textposition='outside', textangle=-90, textfont_size=11, texttemplate='%{text:,.1f}')
    st.plotly_chart(fig, use_container_width=True, key=f"bar_daily_{category_name}")
    return res_df


# =====================================================================
# 💡 TIME (주황/보라/빨강) 렌더링
# =====================================================================
st.markdown("### 🕒 TIME ETF 그룹 분석")
t20_time = draw_merged_top20(merged_data["TIME"], "TIME", {'5일매수(백만)': '#FFBB78', '3일매수(백만)': '#FF7F0E', '당일매수(백만)': '#D62728'})
b20_time = draw_merged_bottom20(merged_data["TIME"], "TIME", {'5일매수(백만)': '#D1C4E9', '3일매수(백만)': '#9575CD', '당일매수(백만)': '#512DA8'})
d15_time = draw_daily_top15(merged_data["TIME"], "TIME", '#D62728') 

time_stocks = []
if not t20_time.empty: time_stocks.extend(t20_time['종목명'].tolist())
if not b20_time.empty: time_stocks.extend(b20_time['종목명'].tolist())
if not d15_time.empty: time_stocks.extend(d15_time['종목명'].tolist())
time_stocks = list(dict.fromkeys(time_stocks)) 

if time_stocks:
    with st.expander("🦅 [히든 대시보드] TIME 주도주(누적+당일) 정밀 입체 분석"):
        tabs = st.tabs([f"📈 {s}" for s in time_stocks])
        for i, tab in enumerate(tabs):
            with tab: render_stock_3d_chart(time_stocks[i], etf_data, base_ledger_df, f"t_{i}")
    draw_momentum_bump_chart("TIME", etf_data, qty_backup_df)

st.markdown("<br><hr><br>", unsafe_allow_html=True)


# =====================================================================
# 💡 KoAct (파랑/보라/하늘) 렌더링
# =====================================================================
st.markdown("### 🌀 KoAct ETF 그룹 분석")
t20_koact = draw_merged_top20(merged_data["KoAct"], "KoAct", {'5일매수(백만)': '#AEC7E8', '3일매수(백만)': '#1F77B4', '당일매수(백만)': '#17BECF'})
b20_koact = draw_merged_bottom20(merged_data["KoAct"], "KoAct", {'5일매수(백만)': '#D1C4E9', '3일매수(백만)': '#9575CD', '당일매수(백만)': '#512DA8'})
d15_koact = draw_daily_top15(merged_data["KoAct"], "KoAct", '#17BECF') 

koact_stocks = []
if not t20_koact.empty: koact_stocks.extend(t20_koact['종목명'].tolist())
if not b20_koact.empty: koact_stocks.extend(b20_koact['종목명'].tolist())
if not d15_koact.empty: koact_stocks.extend(d15_koact['종목명'].tolist())
koact_stocks = list(dict.fromkeys(koact_stocks)) 

if koact_stocks:
    with st.expander("🦅 [히든 대시보드] KoAct 주도주(누적+당일) 정밀 입체 분석"):
        tabs = st.tabs([f"📈 {s}" for s in koact_stocks])
        for i, tab in enumerate(tabs):
            with tab: render_stock_3d_chart(koact_stocks[i], etf_data, base_ledger_df, f"k_{i}")
    draw_momentum_bump_chart("KoAct", etf_data, qty_backup_df)


# =====================================================================
# 🕵️‍♂️ [섹션 2-1: 상세 거래 장부]
# =====================================================================
st.markdown("---")
with st.expander("🔍 [히든 데이터베이스] 순매수/순매도 TOP 20 & 당일 TOP 15 종목들의 개별 ETF 거래 장부"):
    all_df_list = [df for df in [t20_time, b20_time, d15_time, t20_koact, b20_koact, d15_koact] if not df.empty]
    if all_df_list:
        top_all = pd.concat(all_df_list)['종목명'].unique()
        h_list = []
        for etf_name, df_raw in etf_data.items():
            if "수량백업" in etf_name: continue
            d_col = df_raw.columns[0]
            df_proc = df_raw 
            for s_name in top_all:
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

# =====================================================================
# 🎯 [섹션 4: 퀀트 알고리즘 - MA200 눌림목 타점 포착]
# =====================================================================
st.markdown("---")
st.header("🎯 MA200 기반 눌림목 포착 종목 (알고리즘 추천)")

pullback_df = pullback_df_raw.copy()

if not pullback_df.empty:
    st.success(f"✅ 눌림목 알고리즘이 포착한 총 {len(pullback_df)}개의 종목이 업데이트되어 있습니다.")
    st.dataframe(pullback_df, use_container_width=True, hide_index=True)
    
    if '종목명' in pullback_df.columns:
        pb_stocks = [s for s in pullback_df['종목명'].tolist() if s in all_stocks_list]
        
        if pb_stocks:
            with st.expander(f"🦅 [히든 대시보드] 포착된 눌림목 종목 즉시 입체 분석 열기 (ETF에 포함된 {len(pb_stocks)}개)", expanded=False):
                tabs = st.tabs([f"📈 {s}" for s in pb_stocks])
                for i, tab in enumerate(tabs):
                    with tab:
                        render_stock_3d_chart(pb_stocks[i], etf_data, base_ledger_df, f"pullback_{i}")
        else:
            st.info("💡 포착된 종목 중 현재 추적 중인 주도주 ETF(TIME, KoAct 등)에 포함된 종목은 없습니다.")
else:
    st.info("현재 구글 시트('관심종목' 탭)에 포착된 눌림목 데이터가 없습니다. 백그라운드에서 스캐너 스크립트를 실행해주세요.")




