import streamlit as st
import httpx
import asyncio
import json
import time
import smtplib
from datetime import datetime, timedelta, date
from itertools import product
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 0. UI 初始化 & 極簡大數據風格
# ==========================================
st.set_page_config(page_title="Flight Actuary | BIG DATA EDITION", page_icon="🐘", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-color: #0e1117;
        background-image: radial-gradient(circle at 2px 2px, rgba(255,255,255,0.05) 1px, transparent 0);
        background-size: 40px 40px;
    }
    .custom-title {
        background: linear-gradient(90deg, #00e676, #00b0ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 2.2rem !important; margin-bottom: 0px;
    }
    .status-card {
        padding: 15px; background: rgba(255, 255, 255, 0.05); border-radius: 10px; border-left: 5px solid #00e676; margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 請檢查 Secrets 中的 BOOKING_API_KEY"); st.stop()

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "ref_price" not in st.session_state: st.session_state.ref_price = 0

CI_GLOBAL_HUBS = {
    "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
    "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
    "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
}
ALL_FORMATTED_CITIES = [f"{code} ({name})" for r, cities in CI_GLOBAL_HUBS.items() for code, name in cities.items()]

# ==========================================
# 1. 核心異步引擎 (大數據優化版)
# ==========================================
async def fetch_flight_async(client, semaphore, legs, cabin, h1, h4, d1, d4):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    
    async with semaphore:
        for attempt in range(3):
            try:
                res = await client.get(url, headers=headers, params={
                    "legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"
                }, timeout=30.0)
                
                if res.status_code == 200:
                    data = res.json()
                    valid = []
                    for offer in data.get('data', {}).get('flightOffers', []):
                        l_sum, is_ci = [], True
                        for seg in offer.get('segments', []):
                            f_info = seg.get('legs', [{}])[0].get('flightInfo', {})
                            if f_info.get('carrierInfo', {}).get('operatingCarrier') != "CI":
                                is_ci = False; break
                            l_sum.append(f"CI{f_info.get('flightNumber', '')}")
                        
                        price = offer.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        if is_ci and len(l_sum) == (4 if h1 else 2):
                            valid.append({"total": price, "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429:
                    await asyncio.sleep(2 * (attempt + 1))
                else: return None
            except:
                await asyncio.sleep(1)
        return None

# ==========================================
# 2. UI 配置
# ==========================================
st.markdown('<p class="custom-title">⚡ ULTRA BIG-DATA RADAR</p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("🛠️ 任務參數")
    trip_mode = st.radio("行程", ["來回", "多點進出"])
    cabin_opt = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cabin = st.selectbox("艙等", list(cabin_opt.keys()))
    show_all = st.checkbox("👁️ 透視模式", value=False)
    # 🏎️ 性能調優
    concurrency = st.slider("併發壓力 (RPS)", 10, 40, 30)

c1, c2 = st.columns(2)
with c1:
    st.subheader("📍 核心路徑")
    if trip_mode == "來回":
        b_org = st.selectbox("起點", ALL_FORMATTED_CITIES, index=0)
        b_dst = st.selectbox("終點", ALL_FORMATTED_CITIES, index=5)
        d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
    else:
        d2o_s = st.selectbox("D2 起點", ALL_FORMATTED_CITIES, index=0)
        d2d_s = st.selectbox("D2 終點", ALL_FORMATTED_CITIES, index=5)
        d3o_s = st.selectbox("D3 起點", ALL_FORMATTED_CITIES, index=32)
        d3d_s = st.selectbox("D3 終點", ALL_FORMATTED_CITIES, index=0)
        d2o, d2d, d3o, d3d = d2o_s.split(" ")[0], d2d_s.split(" ")[0], d3o_s.split(" ")[0], d3d_s.split(" ")[0]
    d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
    d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))

with c2:
    st.subheader("📡 獵殺範圍")
    d1_regs = st.multiselect("目標區域", list(CI_GLOBAL_HUBS.keys()))
    d1_hubs = st.multiselect("外站站點", [f"{c} ({n})" for r in d1_regs for c, n in CI_GLOBAL_HUBS[r].items()] if d1_regs else ALL_FORMATTED_CITIES)
    d1_range = st.date_input("D1 範圍", value=(date(2026, 6, 10), date(2026, 6, 12)))
    d4_range = st.date_input("D4 範圍", value=(date(2026, 6, 26), date(2026, 6, 28)))

# ==========================================
# 3. 執行邏輯 (大數據優化)
# ==========================================
async def start_big_data_hunt():
    # 日期展開
    d1_s, d1_e = (d1_range[0], d1_range[-1]) if isinstance(d1_range, (list, tuple)) else (d1_range, d1_range)
    d4_s, d4_e = (d4_range[0], d4_range[-1]) if isinstance(d4_range, (list, tuple)) else (d4_range, d4_range)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]

    tasks = []
    # 1. 先校準直飛
    async with httpx.AsyncClient(timeout=30.0) as client:
        with st.spinner("🎯 校準市場基準價..."):
            d_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                      {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            res = await fetch_flight_async(client, asyncio.Semaphore(1), d_legs, cabin_opt[cabin], "", "", "", "")
            ref_val = res['total'] if res else 200000
            st.session_state.ref_price = ref_val

        # 2. 生成海量任務
        for h1_r in d1_hubs:
            for h4_r in d1_hubs: # 預設同步
                h1, h4 = h1_r.split(" ")[0], h4_r.split(" ")[0]
                for d1, d4 in product(d1_list, d4_list):
                    if d1 <= d2_dt and d4 >= d3_dt:
                        l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                             {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                             {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                             {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                        tasks.append(fetch_flight_async(client, asyncio.Semaphore(concurrency), l, cabin_opt[cabin], h1_r, h4_r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

        if not tasks: st.error("❌ 任務量為 0，請檢查日期設定。"); return

        # 3. 異步爆破執行
        st.markdown(f"### 🚀 正在獵殺 {len(tasks)} 組組合...")
        prog_bar = st.progress(0)
        status_text = st.empty()
        
        results = []
        start_time = time.time()
        
        # 🛡️ 降頻刷新：每 50 筆才更新一次 UI
        update_step = 50 
        
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            res = await coro
            if res and (show_all or (ref_val - res['total'] >= 0)):
                res['ref'] = ref_val
                results.append(res)
            
            if (i + 1) % update_step == 0 or (i + 1) == len(tasks):
                elapsed = time.time() - start_time
                rps = (i + 1) / elapsed
                eta = (len(tasks) - (i + 1)) / rps
                prog_bar.progress((i + 1) / len(tasks))
                status_text.markdown(f"""
                <div class="status-card">
                    <b>進度:</b> {i+1} / {len(tasks)} | 
                    <b>當前速度:</b> {rps:.1f} 筆/秒 | 
                    <b>預估剩餘時間:</b> {int(eta)} 秒
                </div>
                """, unsafe_allow_html=True)
        
        st.session_state.valid_offers = results
        st.success(f"✅ 獵殺完成！共發現 {len(results)} 組獲利組合。")
        st.rerun()

if st.button("🔥 啟動海量任務爆破", use_container_width=True):
    asyncio.run(start_big_data_hunt())

# ==========================================
# 展示區
# ==========================================
def render_matrix_html(res_list, ref):
    if not res_list: return ""
    d1_dates = sorted(list(set(r['d1'] for r in res_list)))
    d4_dates = sorted(list(set(r['d4'] for r in res_list)))
    matrix = {}
    prices = [r['total'] for r in res_list]
    min_p, max_p = min(prices), max(prices)
    for r in res_list:
        key = (r['d1'], r['d4'])
        if key not in matrix or r['total'] < matrix[key]['total']: matrix[key] = r

    html = '<div style="background:#fff; padding:10px; border-radius:8px; overflow-x:auto;"><table style="width:100%; border-collapse:collapse; font-size:10px; color:#333;" border="1">'
    html += '<tr style="background:#444; color:#fff;"><th>D4↘\\D1➡</th>' + "".join([f"<th>{d[5:]}</th>" for d in d1_dates]) + '</tr>'
    for d4 in d4_dates:
        html += f'<tr><td style="background:#f2f2f2; font-weight:bold;">{d4[5:]}</td>'
        for d1 in d1_dates:
            rec = matrix.get((d1, d4))
            if rec:
                save = ref - rec['total']
                alpha = 0.8 if max_p <= min_p else 0.8 - 0.7 * ((rec['total'] - min_p) / (max_p - min_p))
                bg = f"rgba(0, 230, 118, {alpha:.2f})" if save >= 0 else "rgba(255, 182, 193, 0.4)"
                html += f'<td style="background:{bg}; padding:4px;"><b>{rec["total"]:,}</b><br><span style="color:{"#d32f2f" if save>=0 else "#1976d2"}">{"省" if save>=0 else "貴"}{abs(save):,}</span></td>'
            else: html += '<td>-</td>'
        html += '</tr>'
    return html + '</table></div>'

if st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    routes = sorted(list(set(f"{r['h1']} ➔ {r['h4']}" for r in res)))
    tabs = st.tabs(["🏆 綜合"] + routes)
    with tabs[0]:
        st.markdown(render_matrix_html(res, st.session_state.ref_price), unsafe_allow_html=True)
    for i, route in enumerate(routes):
        with tabs[i+1]:
            st.markdown(render_matrix_html([r for r in res if f"{r['h1']} ➔ {r['h4']}" == route], st.session_state.ref_price), unsafe_allow_html=True)
