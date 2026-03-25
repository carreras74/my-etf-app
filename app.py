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
st.set_page_config(page_title="ETF 퀀트 분석 대시보드", layout="wide")

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
                agg_data[d] = {'Shares': 0.0, 'Price': np.nan, 'TotalQtyChange': 0}
                
            if etf_name == best_etf:
                w = pd.to_numeric(row[stock_name], errors='coerce')
                agg_data[d]['Shares'] = w if pd.notna(w) else 0.0
                
            diff_str = str(row[diff_col]) if diff_col in df.columns else ""
            qty_change = 0
            
            if " | " in diff_str:
                parts = diff_str.split(" | ")
                q_str = parts[0].strip()
                p_str = parts[1].strip()
                
                # 안전 파싱 (숫자만 추출)
                p_num = re.sub(r'[^\d]', '', p_str)
                if p_num: agg_data[d]['Price'] = int(p_num)
                    
                q_num = re.sub(r'[^\d]', '', q_str)
                if q_num:
                    if any(x in q_str for x in ['🔵', '▼', '-', '하락']): qty_change = -int(q_num)
                    else: qty_change = int(q_num)
                    
            agg_data[d]['TotalQtyChange'] += qty_change

    plot_data = [{'Date': k, 'Shares': v['Shares'], 'Price': v['Price'], 'QtyChange': v['TotalQtyChange']} for k, v in agg_data.items()]
    p_df = pd.DataFrame(plot_data)
    
    if p_df.empty: return
    
    p_df['DateObj'] = pd.to_datetime(p_df['Date'], errors='coerce')
    p_df = p_df.dropna(subset=['DateObj']).sort_values('DateObj')
    p_df['Date'] = p_df['DateObj'].dt.strftime('%Y-%m-%d')
    valid_p_df = p_df.dropna(subset=['Price'])
    
    st.subheader(f"📊 {stock_name} 입체 분석 (대장: {best_etf})")
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3], specs=[[{"secondary_y": True}], [{"secondary_y": False}]])
    
    fig.update_xaxes(type='category')
    
    # 💡 데이터 성격에 맞게 '비중'에서 '보유 수량(주)'으로 라벨 수정
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['Shares'], name='보유 수량(주)', opacity=0.5, marker_color='#AEC7E8', width=0.35), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=valid_p_df['Date'], y=valid_p_df['Price'], name='주가(원)', mode='lines+markers', line=dict(color='#FFD700', width=3), marker=dict(size=6)), row=1, col=1, secondary_y=True)
    
    colors = ['#FF4B4B' if q > 0 else '#1F77B4' if q < 0 else '#CCCCCC' for q in p_df['QtyChange']]
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['QtyChange'], name='전체 수량 합산', marker_color=colors, width=0.35), row=2, col=1)
    
    if buy_price:
        fig.add_trace(go.Scatter(x=[p_df['Date'].iloc[0], p_df['Date'].iloc[-1]], y=[buy_price, buy_price], mode="lines+text", line=dict(color="#00C853", dash="dash", width=2), name="내 매수단가", text=[f"매수단가 ({buy_price:,.0f}원)", ""], textposition="bottom right", textfont=dict(color='white'), showlegend=False), row=1, col=1, secondary_y=True)

    fig.update_layout(height=600, hovermode="x unified", template="plotly_dark", margin=dict(l=10, r=10, t=50, b=10), showlegend=False)
    fig.update_yaxes(title_text="보유 수량 (주)", secondary_y=False, row=1, col=1)
    fig.update_yaxes(title_text="주가 (원)", secondary_y=True, row=1, col=1)
    st.plotly_chart(fig, use_container_width=True, key=unique_key or f"chart_{stock_name}")

# =====================================================================
# 2. 구글 시트 데이터 로드
# =====================================================================
@st.cache_data(ttl=600)
def load_data_from_google():
    try:
        creds_json = json.loads(st.secrets["google_key"])
        gc = gspread.service_account_from_dict(creds_json)
        sh = gc.open_by_key("1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA")
        
        all_data = {}
        for ws in sh.worksheets():
            data = ws.get_all_values()
            if not data: continue
            
            headers = data[0]
            seen = {}
            new_headers = []
            for h in headers:
                h = str(h).strip() if h else "Unnamed"
                if h in seen:
                    new_headers.append(f"{h}.{seen[h]}")
                    seen[h] += 1
                else:
                    new_headers.append(h)
                    seen[h] = 1
            
            df = pd.DataFrame(data[1:], columns=new_headers)
            if not df.empty: all_data[ws.title] = df
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 실패: {e}")
        return None

# =====================================================================
# 3. 메인 대시보드 렌더링
# =====================================================================
st.title("📈 ETF 퀀트 분석 대시보드")
etf_data = load_data_from_google()

if not etf_data:
    st.error("데이터 로드에 실패했습니다.")
    st.stop()

# --- [섹션 1: 범프 차트 (상위 20위 정예화 버전)] ---
st.header("🏁 ETF 종목별 순위 변동 (TOP 20 Bump Chart)")
selected_etf = st.sidebar.selectbox("분석할 ETF 선택", list(etf_data.keys()))
st.sidebar.markdown("<br>" * 15, unsafe_allow_html=True)

raw_df = etf_data[selected_etf].copy()
if len(raw_df.columns) > 3:
    date_col = raw_df.columns[0]
    stock_cols = [c for c in raw_df.columns if c != date_col and not str(c).endswith('_증감')]
    
    # 💡 [핵심 패치] 데이터가 '주식수'이므로, 평가금액을 계산하여 진짜 비중을 산출!
    records = []
    for _, row in raw_df.iterrows():
        d = row[date_col]
        for s in stock_cols:
            # 1. 주식수 파싱
            shares_str = str(row[s]).replace(',', '').strip()
            try:
                shares = float(shares_str)
            except ValueError:
                shares = 0.0

            # 2. 주가 파싱 (_증감 컬럼에서 추출)
            diff_c = f"{s}_증감"
            price = np.nan
            if diff_c in raw_df.columns:
                diff_str = str(row[diff_c])
                if " | " in diff_str:
                    p_str = diff_str.split(" | ")[1].strip()
                    p_num = re.sub(r'[^\d]', '', p_str)
                    if p_num: price = float(p_num)

            records.append({'날짜': d, '종목명': s, '주식수': shares, '주가': price})

    df_calc = pd.DataFrame(records)

    # 날짜 정렬 및 결측치 전처리
    df_calc['날짜'] = pd.to_datetime(df_calc['날짜'], errors='coerce')
    df_calc = df_calc.dropna(subset=['날짜']).sort_values(by='날짜')
    df_calc['날짜_문자열'] = df_calc['날짜'].dt.strftime('%Y-%m-%d')

    # 3. 주가가 빈 날은 이전 날짜의 주가로 채우기 (Forward Fill)
    df_calc['주가'] = df_calc.groupby('종목명')['주가'].ffill().fillna(0)

    # 4. 진짜 '비중(%)' 계산 로직: (해당 종목 평가금액 / 당일 전체 평가금액) * 100
    df_calc['평가금액'] = df_calc['주식수'] * df_calc['주가']
    daily_total = df_calc.groupby('날짜')['평가금액'].transform('sum')
    df_calc['비중'] = np.where(daily_total > 0, (df_calc['평가금액'] / daily_total) * 100, 0.0)

    # 5. 순위 계산 (계산된 '진짜 비중' 기준 정렬)
    df_calc['순위'] = df_calc.groupby('날짜')['비중'].rank(method='first', ascending=False)

    # 상위 20위까지만 필터링
    df_weight = df_calc[df_calc['순위'] <= 20].copy()

    # 비중 텍스트 포맷 (점 위에 깔끔하게 소수점 2자리까지만 표시)
    df_weight['비중_텍스트'] = df_weight['비중'].apply(lambda x: f"{x:.2f}%" if x > 0 else "")

    latest_date = df_weight['날짜'].max()

    # 범례 매핑 (가장 최근 진짜 비중 기준)
    latest_weights = df_weight[df_weight['날짜'] == latest_date].set_index('종목명')['비중']
    name_to_legend = {name: f"{name} ({weight:.2f}%)" for name, weight in latest_weights.items()}

    # 혹시 최근 날짜에 없지만 과거에 TOP 20이었던 종목 범례 처리
    for name in df_weight['종목명'].unique():
        if name not in name_to_legend:
            w = df_weight[df_weight['종목명'] == name].sort_values(by='날짜').iloc[-1]['비중']
            name_to_legend[name] = f"{name} ({w:.2f}%)"

    df_weight['종목명_범례'] = df_weight['종목명'].map(name_to_legend)

    # 범례 정렬 (최신 날짜 순위 기준)
    latest_order = df_weight[df_weight['날짜'] == latest_date].sort_values(by='순위')['종목명'].tolist()
    latest_order_legend = [name_to_legend[name] for name in latest_order if name in name_to_legend]

    # X축 날짜 순서 고정 (꼬임 방지)
    date_order = df_weight['날짜_문자열'].drop_duplicates().tolist()

    # 차트 그리기
    fig_bump = px.line(
        df_weight,
        x='날짜_문자열',
        y='순위',
        color='종목명_범례',
        text='비중_텍스트',
        markers=True,
        category_orders={
            '종목명_범례': latest_order_legend,
            '날짜_문자열': date_order
        }
    )

    # 텍스트가 마커를 가리지 않도록 위치 조정
    fig_bump.update_traces(textposition="top center", textfont=dict(size=10))

    fig_bump.update_layout(
        yaxis=dict(title="종목 순위 (1~20위)", autorange="reversed", tickmode="linear", dtick=1, range=[20.5, 0.5]),
        xaxis=dict(type='category', title="날짜"),
        template="plotly_dark",
        height=850,
        legend=dict(title="종목명 (최근 비중)", orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02)
    )
    st.plotly_chart(fig_bump, use_container_width=True)
    
    with st.expander("📊 구글 시트 원본 데이터 펴보기"):
        st.dataframe(raw_df, use_container_width=True, hide_index=True)

# --- [섹션 2: 수급 격전지 찐 주도주 분석] ---
st.divider()
st.header("🔥 최근 5영업일 누적 순매수/매도 격전지 TOP 20")

time_agg, koact_agg = {}, {}
all_dates = []

for name, df in etf_data.items():
    if len(df.columns) <= 3: continue
    target_agg = time_agg if "TIME" in name else (koact_agg if "KoAct" in name else None)
    if target_agg is None: continue
        
    d_col = df.columns[0]
    df[d_col] = pd.to_datetime(df[d_col])
    df = df.sort_values(by=d_col)
    all_dates.extend(df[d_col].dt.strftime('%Y-%m-%d').tolist())
    
    last_5, last_3, last_1 = df.tail(5), df.tail(3), df.tail(1)
    stocks = [c for c in df.columns if c != d_col and not str(c).endswith('_증감')]

    for s in stocks:
        diff_c = f"{s}_증감"
        if diff_c not in df.columns: continue
        if s not in target_agg: target_agg[s] = {'1d':0.0, '3d':0.0, '5d':0.0, 'etf_5d':{}}
        
        def calc_money(sub_df):
            n_buy = 0.0
            for v in sub_df[diff_c]:
                if " | " in str(v):
                    parts = str(v).split(" | ")
                    q_str, p_str = parts[0].strip(), parts[1].strip()
                    q_num = re.sub(r'[^\d]', '', q_str)
                    qty = int(q_num) if q_num else 0
                    if any(x in q_str for x in ['🔵', '▼', '-', '하락']): qty = -qty
                    p_num = re.sub(r'[^\d]', '', p_str)
                    price = int(p_num) if p_num else 0
                    n_buy += (qty * price)
            return n_buy

        v1, v3, v5 = calc_money(last_1), calc_money(last_3), calc_money(last_5)
        target_agg[s]['1d'] += v1; target_agg[s]['3d'] += v3; target_agg[s]['5d'] += v5
        target_agg[s]['etf_5d'][name] = target_agg[s]['etf_5d'].get(name, 0.0) + v5

global_latest = max(all_dates) if all_dates else "알 수 없음"

def make_records(agg_dict):
    recs = []
    for s, f in agg_dict.items():
        if f['etf_5d']:
            best = max(f['etf_5d'], key=lambda x: abs(f['etf_5d'][x]))
            s_name = best.replace('TIME ','').replace('TIME','').replace('KoAct ','').replace('KoAct','').strip()
            recs.append({'기준일자':global_latest, '종목명':s, '표시명':f"{s}<br>({s_name})", '1d':f['1d']/1e6, '3d':f['3d']/1e6, '5d':f['5d']/1e6})
    return recs

def draw_top20(records, title, color_map):
    if not records:
        st.info(f"{title} 데이터가 없습니다.")
        return []
    res = pd.DataFrame(records)
    res['절대값'] = res['5d'].abs()
    res = res[res['절대값'] > 0].sort_values(by='절대값', ascending=False).head(20)
    if res.empty: return []
    melted = res.melt(id_vars=['표시명'], value_vars=['5d', '3d', '1d'], var_name='기간', value_name='순매수(백만)')
    emo = "🔥" if title=="TIME" else "🌊"
    fig = px.bar(melted, x='표시명', y='순매수(백만)', color='기간', barmode='group', title=f"{emo} [{title} 통합] 5일 집중 매수/매도 격전지 TOP 20", color_discrete_map=color_map)
    fig.update_layout(template="plotly_dark", height=600, yaxis_title="누적 대금 (단위: 백만원)")
    fig.update_yaxes(zeroline=True, zerolinewidth=2, zerolinecolor='black')
    st.plotly_chart(fig, use_container_width=True)
    return res['종목명'].tolist()

c_time = {'5d': '#FFBB78', '3d': '#FF7F0E', '1d': '#D62728'}
t_top20 = draw_top20(make_records(time_agg), "TIME", c_time)
if t_top20:
    with st.expander("🔍 [TIME 그룹] 다크모드 입체 분석 열기"):
        tabs = st.tabs([f"📈 {n}" for n in t_top20])
        for i, t in enumerate(tabs):
            with t: draw_hts_chart(t_top20[i], etf_data, unique_key=f"t_{i}")

c_koact = {'5d': '#AEC7E8', '3d': '#1F77B4', '1d': '#17BECF'}
k_top20 = draw_top20(make_records(koact_agg), "KoAct", c_koact)
if k_top20:
    with st.expander("🔍 [KoAct 그룹] 다크모드 입체 분석 열기"):
        tabs = st.tabs([f"📈 {n}" for n in k_top20])
        for i, t in enumerate(tabs):
            with t: draw_hts_chart(k_top20[i], etf_data, unique_key=f"k_{i}")

# --- [섹션 3: 내 매입 종목] ---
st.divider()
st.header("🦅 내 매입 종목 입체 분석")
try:
    url = f"https://raw.githubusercontent.com/carreras74/ETF_Auto_Bot/main/{urllib.parse.quote('매입장부.xlsx')}"
    ledger = pd.read_excel(url)
    my_s = ledger['종목명'].dropna().unique().tolist()
    if my_s:
        tabs = st.tabs([f"📈 {n}" for n in my_s])
        for i, t in enumerate(tabs):
            with t:
                row = ledger[ledger['종목명']==my_s[i]].iloc[0]
                bp = float(str(row.get('매수단가','')).replace(',','').replace('원','')) if pd.notna(row.get('매수단가')) else None
                draw_hts_chart(my_s[i], etf_data, buy_price=bp, unique_key=f"my_{i}")
except:
    st.info("💡 깃허브에서 '매입장부.xlsx'를 찾을 수 없습니다.")
