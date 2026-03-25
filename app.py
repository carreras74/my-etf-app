import streamlit as st
import gspread, pandas as pd, plotly.express as px, plotly.graph_objects as go
from plotly.subplots import make_subplots
import json, re, urllib.parse, numpy as np

st.set_page_config(page_title="ETF 분석 대시보드", layout="wide")

@st.cache_data(ttl=600)
def load_data():
    try:
        gc = gspread.service_account_from_dict(json.loads(st.secrets["google_key"]))
        sh = gc.open_by_key("1ZxIYeERuOWOWZudyjpMWpEWA0eljOct_uO9gXg6_2JA")
        all_d = {}
        for ws in sh.worksheets():
            data = ws.get_all_values()
            if data: all_d[ws.title] = pd.DataFrame(data[1:], columns=data[0])
        return all_d
    except: return None

etf_data = load_data()
if not etf_data: st.error("데이터 로드 실패"); st.stop()

st.title("📈 ETF 퀀트 분석 대시보드")
selected_etf = st.sidebar.selectbox("ETF 선택", list(etf_data.keys()))

# --- 범프 차트 (TOP 20 + 주말 제거) ---
df = etf_data[selected_etf].copy()
date_col = df.columns[0]
stocks = [c for c in df.columns if c != date_col and not str(c).endswith('_증감') and not str(c).endswith('_수량')]
df_melt = df.melt(id_vars=[date_col], value_vars=stocks, var_name='종목', value_name='비중')
df_melt['비중'] = pd.to_numeric(df_melt['비중'].astype(str).str.replace('%',''), errors='coerce').fillna(0)
df_melt[date_col] = pd.to_datetime(df_melt[date_col])
df_melt['순위'] = df_melt.groupby(date_col)['비중'].rank(method='first', ascending=False)
df_melt = df_melt[df_melt['순위'] <= 20] # 💡 상위 20위 제한
df_melt['DateStr'] = df_melt[date_col].dt.strftime('%Y-%m-%d') # 💡 주말 제거용 문자열 변환

latest_order = df_melt[df_melt[date_col] == df_melt[date_col].max()].sort_values('순위')['종목'].tolist()
fig = px.line(df_melt, x='DateStr', y='순위', color='종목', markers=True, category_orders={'종목': latest_order})
fig.update_layout(yaxis=dict(autorange="reversed", dtick=1), xaxis=dict(type='category'), template="plotly_dark", height=800)
st.plotly_chart(fig, use_container_width=True)

# (이후 수급 TOP 20 로직은 기존과 동일하게 유지...)
