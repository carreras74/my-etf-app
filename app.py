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
                agg_data[d] = {'Weight': 0.0, 'Price': np.nan, 'TotalQtyChange': 0}
                
            if etf_name == best_etf:
                w = pd.to_numeric(row[stock_name], errors='coerce')
                agg_data[d]['Weight'] = w if pd.notna(w) else 0.0
                
            diff_str = str(row[diff_col]) if diff_col in df.columns else ""
            qty_change = 0
            
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
    if p_df.empty: return
    
    p_df['DateObj'] = pd.to_datetime(p_df['Date'], errors='coerce')
    p_df = p_df.dropna(subset=['DateObj']).sort_values('DateObj')
    p_df['Date'] = p_df['DateObj'].dt.strftime('%Y-%m-%d')
    valid_p_df = p_df.dropna(subset=['Price'])
    
    st.subheader(f"📊 {stock_name} 입체 분석 (대장: {best_etf})")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.7, 0.3], specs=[[{"secondary_y": True}], [{"secondary_y": False}]])
    fig.update_xaxes(type='category')
    
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['Weight'], name='비중(%)', opacity=0.5, marker_color='#AEC7E8'), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=valid_p_df['Date'], y=valid_p_df['Price'], name='주가(원)', mode='lines+markers', line=dict(color='#FFD700', width=3)), row=1, col=1, secondary_y=True)
    
    colors = ['#FF4B4B' if q > 0 else '#1F77B4' if q < 0 else '#CCCCCC' for q in p_df['QtyChange']]
    fig.add_trace(go.Bar(x=p_df['Date'], y=p_df['QtyChange'], name='수량증감', marker_color=colors), row=2, col=1)
    
    if buy_price:
        fig.add_trace(go.Scatter(x=[p_df['Date'].iloc[0], p_df['Date'].iloc[-1]], y=[buy_price, buy_price], mode="lines", line=dict(color="#00C853", dash="dash"), name="내 매수단가"), row=1, col=1, secondary_y=True)

    fig.update_layout(height=600, hovermode="x unified", template="plotly_dark", plot_bgcolor='#131722', paper_bgcolor='#131722', margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True, key=unique_key or f"chart_{stock_name}")

# =====================================================================
# 2. 구글 시트 데이터 로드 엔진 (중복 헤더 방어 패치 완료)
# =====================================================================
@st.cache_data(ttl=600)
def load_data_from_google():
    try:
        creds_json = json.loads(st.secrets["google_key"])
        gc = gspread.service_account_from_dict(creds_json)
        sh = gc.open_by_key("1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA")
        worksheets = sh.worksheets()
        
        all_data = {}
        for ws in worksheets:
            data = ws.get_all_values()
            if not data: continue
            
            # 💡 [중요 패치] 중복된 제목('0', '6' 등)이 있으면 이름을 자동으로 보정
            headers = data[0]
            seen = {}
            new_headers = []
            for h in headers:
                h = str(h).strip() if h else "Unnamed"
                count = seen.get(h, 0)
                if count > 0:
                    new_headers.append(f"{h}.{count}")
                else:
                    new_headers.append(h)
                seen[h] = count + 1
            
            df = pd.DataFrame(data[1:], columns=new_headers)
            if not df.empty:
                all_data[ws.title] = df
        return all_data
    except Exception as e:
        st.error(f"❌ 데이터 로드 실패: {e}")
        return None

def draw_top20_money_chart(records, category_name, color_map):
    if not records: return []
    df_res = pd.DataFrame(records)
    df_res['절대값'] = df_res['5영업일순매수(백만)'].abs()
    df_res = df_res[df_res['절대값'] > 0].sort_values(by='절대값', ascending=False).head(20)
    
    if df_res.empty: return []
    
    df_melted = df_res.melt(id_vars=['표시명'], value_vars=['5영업일순매수(백만)', '3영업일순매수(백만)', '당일순매수(백만)'], var_name='기간', value_name='금액')
    fig = px.bar(df_melted, x='표시명', y='금액', color='기간', barmode='group', title=f"🔥 {category_name} 그룹 수급 TOP 20", color_discrete_map=color_map)
    fig.update_layout(template="plotly_dark", height=500)
    st.plotly_chart(fig, use_container_width=True)
    return df_res['종목명'].tolist()

# =====================================================================
# 3. 메인 대시보드 실행
# =====================================================================
st.title("📈 ETF 퀀트 분석 대시보드")
etf_data = load_data_from_google()

if etf_data:
    # --- [섹션 1: 범프 차트] ---
    st.header("🏁 ETF 종목별 순위 변동 (Bump Chart)")
    selected_etf = st.selectbox("분석할 ETF 선택", list(etf_data.keys()))
    raw_df = etf_data[selected_etf].copy()
    
    if len(raw_df.columns) > 3:
        date_col = raw_df.columns[0]
        stock_cols = [c for c in raw_df.columns if c != date_col and not str(c).endswith('_증감')]
        df_weight = raw_df[[date_col] + stock_cols].melt(id_vars=[date_col], var_name='종목명', value_name='비중')
        df_weight['비중'] = pd.to_numeric(df_weight['비중'], errors='coerce').fillna(0)
        df_weight[date_col] = pd.to_datetime(df_weight[date_col])
        df_weight['순위'] = df_weight.groupby(date_col)['비중'].rank(method='first', ascending=False)
        
        fig_bump = px.line(df_weight, x=date_col, y='순위', color='종목명', markers=True)
        fig_bump.update_layout(yaxis=dict(autorange="reversed", tickmode="linear", dtick=1), template="plotly_dark", height=600)
        st.plotly_chart(fig_bump, use_container_width=True)

    # --- [섹션 2: 수급 격전지 분석 엔진] ---
    st.divider()
    st.header("🔥 최근 5영업일 누적 순매수/매도 격전지")
    
    time_agg, koact_agg = {}, {}
    all_dates = []

    for name, df in etf_data.items():
        if len(df.columns) <= 3: continue
        d_col = df.columns[0]
        df[d_col] = pd.to_datetime(df[d_col])
        df = df.sort_values(by=d_col)
        all_dates.extend(df[d_col].dt.strftime('%Y-%m-%d').tolist())
        
        # 그룹 판별
        target_agg = time_agg if "TIME" in name else (koact_agg if "KoAct" in name else None)
        if target_agg is None: continue
            
        last_5, last_3, last_1 = df.tail(5), df.tail(3), df.tail(1)
        stocks = [c for c in df.columns if c != d_col and not str(c).endswith('_증감')]

        for s in stocks:
            diff_c = f"{s}_증감"
            if diff_c not in df.columns: continue
            if s not in target_agg: target_agg[s] = {'1d':0.0, '3d':0.0, '5d':0.0, 'etf_5d':{}}
            
            def get_val(sub):
                total = 0.0
                for v in sub[diff_c]:
                    if " | " in str(v):
                        q_p = str(v).split(" | ")
                        q_str = q_p[0].replace('🔴▲','').replace('🔵▼','-').replace(',','').strip()
                        try:
                            q = int(q_str)
                            p_match = re.search(r'₩([\d,]+)', q_p[1])
                            p = int(p_match.group(1).replace(',','')) if p_match else 0
                            total += (q * p)
                        except: continue
                return total

            v1, v3, v5 = get_val(last_1), get_val(last_3), get_val(last_5)
            target_agg[s]['1d'] += v1; target_agg[s]['3d'] += v3; target_agg[s]['5d'] += v5
            target_agg[s]['etf_5d'][name] = target_agg[s]['etf_5d'].get(name, 0) + v5

    latest_date = max(all_dates) if all_dates else "알 수 없음"
    
    def prep_records(agg):
        recs = []
        for s, f in agg.items():
            if f['etf_5d']:
                best = max(f['etf_5d'], key=lambda x: abs(f['etf_5d'][x]))
                recs.append({'기준일자':latest_date, '종목명':s, '표시명':f"{s}<br>({best})", '당일순매수(백만)':f['1d']/1e6, '3영업일순매수(백만)':f['3d']/1e6, '5영업일순매수(백만)':f['5d']/1e6})
        return recs

    c_time = {'5영업일순매수(백만)': '#FFBB78', '3영업일순매수(백만)': '#FF7F0E', '당일순매수(백만)': '#D62728'}
    t_top20 = draw_top20_money_chart(prep_records(time_agg), "TIME", c_time)
    
    c_koact = {'5영업일순매수(백만)': '#AEC7E8', '3영업일순매수(백만)': '#1F77B4', '당일순매수(백만)': '#17BECF'}
    k_top20 = draw_top20_money_chart(prep_records(koact_agg), "KoAct", c_koact)

    # --- [섹션 3: 내 매입 종목 분석] ---
    st.divider()
    st.header("🦅 내 매입 종목 입체 분석")
    try:
        ledger_url = f"https://raw.githubusercontent.com/carreras74/ETF_Auto_Bot/main/{urllib.parse.quote('매입장부.xlsx')}"
        ledger = pd.read_excel(ledger_url)
        for _, row in ledger.iterrows():
            draw_hts_chart(row['종목명'], etf_data, buy_price=row.get('매수단가'), unique_key=f"my_{row['종목명']}")
    except:
        st.info("💡 매입장부(Excel)를 불러올 수 없습니다. GitHub 저장소에 '매입장부.xlsx'가 있는지 확인하세요.")

else:
    st.error("데이터 로드에 실패했습니다. 구글 시트 제목 중복이나 Secrets 설정을 확인해 주세요.")
else:
    st.error("데이터 로드에 실패했습니다. 구글 시트 제목 중복이나 Secrets 설정을 확인해 주세요.")

