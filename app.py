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

# 1. 페이지 설정
st.set_page_config(page_title="ETF 전종목 비중 추적", layout="wide")

# =====================================================================
# 🪄 [마법의 함수] HTS 다크모드 입체 분석 차트 자동 생성기
# =====================================================================
def draw_hts_chart(stock_name, etf_data_dict, buy_price=None, buy_date=None, unique_key=None):
    best_etf = None
    max_weight = -1
    for etf_name, df in etf_data_dict.items():
        if stock_name in df.columns:
            m_weight = pd.to_numeric(df[stock_name], errors='coerce').max()
            if m_weight > max_weight:
                max_weight = m_weight; best_etf = etf_name
                
    if not best_etf:
        st.warning(f"'{stock_name}' 종목은 현재 추적 중인 ETF에 존재하지 않습니다.")
        return
        
    agg_data = {}
    for etf_name, df in etf_data_dict.items():
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
    
    p_df['DateObj'] = pd.to_datetime(p_df['Date'], errors='coerce')
    p_df = p_df.dropna(subset=['DateObj']).sort_values('DateObj')
    p_df['Date'] = p_df['DateObj'].dt.strftime('%Y-%m-%d')
    p_df = p_df.drop(columns=['DateObj'])
    
    valid_p_df = p_df.dropna(subset=['Price'])
    
    st.subheader(f"📊 {stock_name} 입체 분석 (비중: {best_etf} / 수급: 전체 합산)")
    
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.7, 0.3], specs=[[{"secondary_y": True}], [{"secondary_y": False}]]
    )
    fig.update_xaxes(type='category')
    
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['Weight'], name=f'{best_etf} 비중(%)', opacity=0.5, marker_color='#AEC7E8', width=0.35), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=valid_p_df['Date'], y=valid_p_df['Price'], name='주가(원)', mode='lines+markers', line=dict(color='#FFD700', width=3), marker=dict(size=6)), row=1, col=1, secondary_y=True)
    
    colors = ['#FF4B4B' if q > 0 else '#1F77B4' if q < 0 else '#CCCCCC' for q in p_df['QtyChange']]
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['QtyChange'], name='전체 수량 합산', marker_color=colors, width=0.35), row=2, col=1)
    
    if not p_df.empty:
        if buy_price is not None:
            fig.add_trace(go.Scatter(x=[p_df['Date'].iloc[0], p_df['Date'].iloc[-1]], y=[buy_price, buy_price], mode="lines+text", line=dict(color="#00C853", dash="dash", width=2), name=f"매수단가 ({buy_price:,.0f}원)", text=[f"내 매수단가 ({buy_price:,.0f}원)", ""], textposition="bottom right", textfont=dict(color='white'), showlegend=False, hoverinfo="skip"), row=1, col=1, secondary_y=True)
        if buy_date is not None and buy_date in p_df['Date'].values:
            max_y = valid_p_df['Price'].max() if not valid_p_df.empty else 100000
            min_y = valid_p_df['Price'].min() if not valid_p_df.empty else 0
            margin = (max_y - min_y) * 0.1 if max_y != min_y else max_y * 0.1
            fig.add_trace(go.Scatter(x=[buy_date, buy_date], y=[min_y - margin, max_y + margin], mode="lines+text", line=dict(color="#00C853", dash="dash", width=2), name="매수타점", text=["매수타점", ""], textposition="top right", textfont=dict(color='white'), showlegend=False, hoverinfo="skip"), row=1, col=1, secondary_y=True)

    fig.update_layout(
        height=700, hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color='white')),
        plot_bgcolor='#131722', paper_bgcolor='#131722', font=dict(color='white'), margin=dict(l=10, r=10, t=50, b=10)
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(title_text="비중 (%)", secondary_y=False, row=1, col=1, showgrid=False, zeroline=False)
    fig.update_yaxes(title_text="주가 (원)", secondary_y=True, row=1, col=1, showgrid=True, gridcolor='#2B3040', zeroline=False)
    fig.update_yaxes(title_text="총 수량증감", row=2, col=1, showgrid=True, gridcolor='#2B3040', zeroline=True, zerolinecolor='#404658')
    
    if unique_key is None: unique_key = f"chart_{stock_name}"
    st.plotly_chart(fig, use_container_width=True, key=unique_key)


# =====================================================================
# 2. 구글 시트 연결 및 범프 차트 대시보드
# =====================================================================
st.title("📈 ETF 종목별 순위 변동 추이 (범프 차트)")

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

    def split_qty(val): return str(val).split(' | ')[0] if ' | ' in str(val) else str(val)
    def format_price(val):
        if ' | ' not in str(val): return "-"
        price_str = str(val).split(' | ')[1]
        if '(+' in price_str: return f"<span style='color:red'><b>{price_str}</b></span>"
        elif '(-' in price_str: return f"<span style='color:blue'><b>{price_str}</b></span>"
        else: return price_str

    df['수량증감(주식수)'] = df['수량증감'].apply(split_qty)
    df['종가/등락률'] = df['수량증감'].apply(format_price)

    latest_date_val = df[date_col_name].max()
    latest_order = df[df[date_col_name] == latest_date_val].sort_values(by=weight_col_name, ascending=False)[name_col_name].tolist()

    st.subheader(f"📅 {selected_etf} 실시간 비중 변동 추이 (상세 확대 모드)")
    fig = px.line(
        df, x=date_col_name, y='순위', color=name_col_name, markers=True,
        hover_name=name_col_name, category_orders={name_col_name: latest_order}, 
        hover_data={'순위': False, weight_col_name: True, '수량증감': False, '수량증감(주식수)': True, '종가/등락률': True, date_col_name: False, name_col_name: False}
    )
    fig.update_layout(
        yaxis=dict(title="종목 순위 (등수)", autorange="reversed", tickmode="linear", dtick=1, showgrid=False, zeroline=False, showticklabels=True),
        xaxis=dict(type="category", title="날짜", showgrid=False),
        height=800, legend=dict(title="종목명", orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        hovermode="closest", hoverlabel=dict(bgcolor="white", font_size=13, font_color="black", font_family="Malgun Gothic, sans-serif", bordercolor="#B0BEC5", align="left")
    )
    st.plotly_chart(fig, use_container_width=True)
    
    with st.expander("📊 구글 시트 원본 데이터 펴보기 (종목별 수량증감 상세 조회)"):
        st.markdown("**💡 구글 시트와 동일한 원본 데이터입니다. 표 안에서 스크롤하거나 우측 상단의 확대 버튼을 누르시면 더 크게 볼 수 있습니다.**")
        st.dataframe(raw_df, use_container_width=True, hide_index=True)


# =====================================================================
# 3. 📊 [진짜 엔진] 5영업일 누적 "순매수 대금(수량×단가)" 찐 주도주 
# =====================================================================
st.markdown("---")
st.header("🔥 최근 5영업일 누적 순매수대금(수량×단가) 찐 주도주 TOP 20")
st.markdown("**💡 비중 착시를 완벽히 제거! 5일간 기관이 '실제 현금'을 가장 많이 쏟아부은 진짜 주도주를 찾습니다.**")

time_agg = {}
koact_agg = {}
all_dates = []

for etf_name, raw_df in etf_data.items():
    if "TIME" in etf_name or "타임" in etf_name:
        cat_agg = time_agg
    elif "KoAct" in etf_name or "코액트" in etf_name:
        cat_agg = koact_agg
    else: continue
        
    df = raw_df.copy()
    if len(df.columns) <= 3: continue 
        
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(by=date_col)
    
    if len(df) == 0: continue
    all_dates.extend(df[date_col].dt.strftime('%Y-%m-%d').tolist())
    
    last_5_df = df.tail(5)
    last_3_df = df.tail(3)
    last_1_df = df.tail(1)
    
    stock_cols = [c for c in df.columns if c != date_col and not str(c).endswith('_증감')]

    for stock in stock_cols:
        diff_col = f"{stock}_증감"
        if diff_col not in df.columns: continue
        
        # 💡 [핵심 패치 1] 어느 ETF에서 매수 대금이 가장 많이 들어왔는지 추적하기 위한 방(etf_5d)을 만듭니다!
        if stock not in cat_agg:
            cat_agg[stock] = {'1d': 0.0, '3d': 0.0, '5d': 0.0, 'etf_5d': {}}
            
        def calc_net_buy(sub_df):
            net_buy = 0.0
            for val in sub_df[diff_col]:
                val_str = str(val)
                if " | " in val_str:
                    parts = val_str.split(" | ")
                    q_str = parts[0].strip()
                    p_str = parts[1].strip()
                    
                    qty = 0
                    if '🔴▲' in q_str: qty = int(q_str.replace('🔴▲', '').replace(',', '').strip())
                    elif '🔵▼' in q_str: qty = -int(q_str.replace('🔵▼', '').replace(',', '').strip())
                    
                    price = 0
                    match = re.search(r'₩([\d,]+)', p_str)
                    if match: price = int(match.group(1).replace(',', ''))
                    
                    net_buy += (qty * price)
            return net_buy
            
        val_1d = calc_net_buy(last_1_df)
        val_3d = calc_net_buy(last_3_df)
        val_5d = calc_net_buy(last_5_df)
        
        cat_agg[stock]['1d'] += val_1d
        cat_agg[stock]['3d'] += val_3d
        cat_agg[stock]['5d'] += val_5d
        
        # 💡 [핵심 패치 2] 해당 ETF의 5일 누적 순매수 대금을 꼬리표로 저장해 둡니다.
        if etf_name not in cat_agg[stock]['etf_5d']:
            cat_agg[stock]['etf_5d'][etf_name] = 0.0
        cat_agg[stock]['etf_5d'][etf_name] += val_5d

global_latest_date = max(all_dates) if all_dates else "알수없음"

time_records = []
for stock, flows in time_agg.items():
    # 💡 [필터 해제] if flows['5d'] > 0: 조건을 과감하게 삭제했습니다! 
    # 이제 마이너스 수급이라도 상대적으로 덜 팔린 상위 종목들을 20개까지 꽉 채웁니다.
    if flows['etf_5d']: # 데이터가 비어있지 않은 경우만
        best_etf = max(flows['etf_5d'], key=flows['etf_5d'].get)
        etf_short = best_etf.replace('TIME ', '').replace('TIME', '').replace('KoAct ', '').replace('KoAct', '').strip()
        
        time_records.append({
            '기준일자': global_latest_date, 
            '종목명': stock, 
            '표시명': f"{stock}<br>({etf_short})", 
            '당일순매수(백만)': round(flows['1d'] / 1000000, 1),
            '3영업일순매수(백만)': round(flows['3d'] / 1000000, 1),
            '5영업일순매수(백만)': round(flows['5d'] / 1000000, 1)
        })

koact_records = []
for stock, flows in koact_agg.items():
    # 💡 [필터 해제] KoAct 역시 필터를 삭제하여 20개를 꽉 채웁니다.
    if flows['etf_5d']:
        best_etf = max(flows['etf_5d'], key=flows['etf_5d'].get)
        etf_short = best_etf.replace('TIME ', '').replace('TIME', '').replace('KoAct ', '').replace('KoAct', '').strip()
        
        koact_records.append({
            '기준일자': global_latest_date, 
            '종목명': stock,
            '표시명': f"{stock}<br>({etf_short})",
            '당일순매수(백만)': round(flows['1d'] / 1000000, 1),
            '3영업일순매수(백만)': round(flows['3d'] / 1000000, 1),
            '5영업일순매수(백만)': round(flows['5d'] / 1000000, 1)
        })

koact_records = []
for stock, flows in koact_agg.items():
    if flows['5d'] > 0:
        best_etf = max(flows['etf_5d'], key=flows['etf_5d'].get)
        etf_short = best_etf.replace('TIME ', '').replace('TIME', '').replace('KoAct ', '').replace('KoAct', '').strip()
        
        koact_records.append({
            '기준일자': global_latest_date, 
            '종목명': stock,
            '표시명': f"{stock}<br>({etf_short})",
            '당일순매수(백만)': round(flows['1d'] / 1000000, 1),
            '3영업일순매수(백만)': round(flows['3d'] / 1000000, 1),
            '5영업일순매수(백만)': round(flows['5d'] / 1000000, 1)
        })

def draw_top20_money_chart(records, category_name, color_map):
    if not records: 
        st.info(f"{category_name} 데이터가 부족합니다.")
        return []
    
    df_res = pd.DataFrame(records)
    df_res = df_res.sort_values(by='5영업일순매수(백만)', ascending=False).head(20)
    date_str = df_res['기준일자'].iloc[0]
    
    df_melted = df_res.melt(
        id_vars=['표시명'], 
        value_vars=['5영업일순매수(백만)', '3영업일순매수(백만)', '당일순매수(백만)'],
        var_name='기간', value_name='순매수대금(백만원)'
    )
    
    title_emoji = "🔥" if category_name == "TIME" else "🌊"
    
    fig = px.bar(
        df_melted, x='표시명', y='순매수대금(백만원)', color='기간', barmode='group', text='순매수대금(백만원)',
        title=f"{title_emoji} [{category_name} 그룹 전체통합] 5일 집중 순매수 대금 TOP 20 ({date_str} 기준)",
        color_discrete_map=color_map
    )
    
    fig.update_layout(xaxis_title="", yaxis_title="누적 순매수 대금 (단위: 백만원)", height=650, legend_title="매집 기간")
    fig.update_yaxes(zeroline=True, zerolinewidth=2, zerolinecolor='black')
    fig.update_traces(textposition='outside', textangle=-90, textfont_size=10)
    st.plotly_chart(fig, use_container_width=True)
    
    # 💡 탭(Tab) 제목과 다크모드 차트로 넘길 때는 깔끔한 '진짜 종목명'만 리스트로 반환!
    return df_res['종목명'].tolist()

# [TIME] 찐 주도주 렌더링
color_time = {'5영업일순매수(백만)': '#FFBB78', '3영업일순매수(백만)': '#FF7F0E', '당일순매수(백만)': '#D62728'}
time_top20_stocks = draw_top20_money_chart(time_records, "TIME", color_time)

if time_top20_stocks:
    with st.expander("🔍 [TIME 그룹] 주도주 TOP 20 종목별 다크모드 입체 분석 열기 (클릭)"):
        time_tabs = st.tabs([f"📈 {name}" for name in time_top20_stocks])
        for idx, tab in enumerate(time_tabs):
            with tab:
                draw_hts_chart(time_top20_stocks[idx], etf_data, unique_key=f"time_{time_top20_stocks[idx]}_{idx}")

st.markdown("<br><br>", unsafe_allow_html=True)

# [KoAct] 찐 주도주 렌더링
color_koact = {'5영업일순매수(백만)': '#AEC7E8', '3영업일순매수(백만)': '#1F77B4', '당일순매수(백만)': '#17BECF'}
koact_top20_stocks = draw_top20_money_chart(koact_records, "KoAct", color_koact)

if koact_top20_stocks:
    with st.expander("🔍 [KoAct 그룹] 주도주 TOP 20 종목별 다크모드 입체 분석 열기 (클릭)"):
        koact_tabs = st.tabs([f"📈 {name}" for name in koact_top20_stocks])
        for idx, tab in enumerate(koact_tabs):
            with tab:
                draw_hts_chart(koact_top20_stocks[idx], etf_data, unique_key=f"koact_{koact_top20_stocks[idx]}_{idx}")


# =====================================================================
# 4. 🦅 내 매입 종목 입체 분석 대시보드 (매입장부 연동)
# =====================================================================
st.markdown("---")
st.header("🦅 내 매입 종목 입체 분석 대시보드")
st.markdown("**💡 1층: 대장 ETF 비중 및 주가 / 2층: 전체 ETF 합산 총 수량증감**")

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
                        if pd.notna(b_date_val): buy_date = pd.to_datetime(b_date_val).strftime('%Y-%m-%d')
                        if pd.notna(b_price_val):
                            if isinstance(b_price_val, str): b_price_val = b_price_val.replace(',', '').replace('원', '').strip()
                            buy_price = float(b_price_val)

                draw_hts_chart(stock_name, etf_data, buy_price, buy_date, unique_key=f"my_stock_{stock_name}_{i}")

except Exception as e:
    st.warning(f"⚠️ 매입장부 데이터를 불러오는 중 에러가 발생했습니다: {e}")

st.markdown("<br><br><br>", unsafe_allow_html=True)

