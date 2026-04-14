import streamlit as st
import httpx
import asyncio
import json
import time
from datetime import datetime, timedelta, date
from itertools import product

# ==========================================
# 0. 全局初始化 & 旗艦風格
# ==========================================
st.set_page_config(page_title="Flight Actuary | ULTRA v30.1", page_icon="💎", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp { background-color: #0e1117; color: #e0e0e0; }
    html, body, [class*="st-"] { font-size: 13px !important; }
    .custom-title {
        background: linear-gradient(90deg, #00e676, #00b0ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 2.2rem !important; margin-bottom: 5px;
    }
    .status-card {
        padding: 12px; background: rgba(0, 230, 118, 0.1); border-radius: 8px; border: 1px solid #00e676; margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 請在 Secrets 中設定 BOOKING_API_KEY"); st.stop()

# 狀態管理
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "ref_price" not in st.session_state: st.session_state.ref_price = 0
if "is_hunting" not in st.session_state: st.session_state.is_hunting = False

CI_GLOBAL_HUBS = {
    "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
    "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
    "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
}
# 🛡️ 排雷 1：修正變數名稱 Typo ({n} -> {name})
ALL_CITIES = [f"{c} ({name})" for r, cities in CI_GLOBAL_HUBS.items() for c, name in cities.items()]

# ==========================================
# 1. 異步核心 (鑽石級穩定版)
# ==========================================
async def fetch_task(client, sem, task_data):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    legs, cabin, h1, h4, d1, d4 = task_data
    
    async with sem:
        for attempt in range(3):
            try:
                res = await client.get(url, headers=headers, params={
                    "legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"
                }, timeout=30.0)
                if res.status_code == 200:
                    data = res.json()
                    offers = data.get('data', {}).get('flightOffers', [])
                    valid = []
                    for o in offers:
                        l_sum, is_ci = [], True
                        for seg in o.get('segments', []):
                            f = seg.get('legs', [{}])[0].get('flightInfo', {})
                            if f.get('carrierInfo', {}).get('operatingCarrier') != "CI":
                                is_ci = False; break
                            l_sum.append(f"CI{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        if is_ci and len(l_sum) == len(legs):
                            valid.append({"total": p, "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429:
                    await asyncio.sleep(2 * (attempt + 1))
            except:
                await asyncio.sleep(1)
        return None

# ==========================================
# 2. UI 設計
# ==========================================
st.markdown('<p class="custom-title">⚡ ULTRA v30.1 DIAMOND RADAR</p>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 配置")
    trip_mode = st.radio("行程", ["來回", "多點進出"])
    cabin_opt = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cabin = st.selectbox("艙等", list(cabin_opt.keys()))
    show_all = st.checkbox("👁️ 透視模式", value=False)
    concurrency = st.slider("併發數 (RPS)", 10, 40, 30)

c1, c2 = st.columns(2)
with c1:
    st.subheader("📍 核心行程")
    if trip_mode == "來回":
        b_org = st.selectbox("起點", ALL_CITIES, index=0)
        b_dst = st.selectbox("終點", ALL_CITIES, index=5)
        d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
    else:
        d2os = st.selectbox("D2 起點", ALL_CITIES, index=0)
        d2ds = st.selectbox("D2 終點", ALL_CITIES, index=5)
        d3os = st.selectbox("D3 起點", ALL_CITIES, index=32)
        d3ds = st.selectbox("D3 終點", ALL_CITIES, index=0)
        d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]
    d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
    d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))

with c2:
    st.subheader("📡 獵殺範圍")
    d1_regs = st.multiselect("區域", list(CI_GLOBAL_HUBS.keys()))
    # 這裡的 {n} 是合法的，因為迴圈變數是 c, n
    d1_hubs = st.multiselect("外站站點", [f"{c} ({n})" for r in d1_regs for c, n in CI_GLOBAL_HUBS[r].items()] if d1_regs else ALL_CITIES)
    d1_range = st.date_input("D1 範圍", value=(date(2026, 6, 10), date(2026, 6, 10)))
    d4_range = st.date_input("D4 範圍", value=(date(2026, 6, 26), date(2026, 6, 26)))

# ==========================================
# 3. 獵殺邏輯
# ==========================================
async def start_hunt():
    d1_s, d1_e = (d1_range[0], d1_range[-1]) if isinstance(d1_range, (list, tuple)) else (d1_range, d1_range)
    d4_s, d4_e = (d4_range[0], d4_range[-1]) if isinstance(d4_range, (list, tuple)) else (d4_range, d4_range)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]

    # 1. 建立任務列表
    raw_tasks = []
    for h1_r in d1_hubs:
        for h4_r in d1_hubs:
            h1, h4 = h1_r.split(" ")[0], h4_r.split(" ")[0]
            for d1, d4 in product(d1_list, d4_list):
                if d1 <= d2_dt and d4 >= d3_dt:
                    legs = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                            {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                            {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                            {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    raw_tasks.append((legs, cabin_opt[cabin], h1_r, h4_r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not raw_tasks: 
        st.error("❌ 任務量為 0，請檢查日期順序。")
        return # 這裡 return 會被外層的 finally 接住，按鈕安全解鎖

    status_area = st.empty()
    prog_bar = st.progress(0)
    
    # 🛡️ 排雷 3：加大 limits，避免高併發連線池耗盡
    limits = httpx.Limits(max_keepalive_connections=200, max_connections=200)
    async with httpx.AsyncClient(timeout=40.0, limits=limits) as client:
        # 校準直飛
        status_area.info("🎯 正在獲取市場基準價...")
        d_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                  {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
        ref_res = await fetch_task(client, asyncio.Semaphore(1), (d_legs, cabin_opt[cabin], "", "", "", ""))
        ref_val = ref_res['total'] if ref_res else 250000
        st.session_state.ref_price = ref_val

        # 批量獵殺
        sem = asyncio.Semaphore(concurrency)
        results = []
        start_time = time.time()
        
        chunk_size = 10 
        for i in range(0, len(raw_tasks), chunk_size):
            chunk = raw_tasks[i : i + chunk_size]
            batch_tasks = [fetch_task(client, sem, t) for t in chunk]
            batch_results = await asyncio.gather(*batch_tasks)
            
            for r in batch_results:
                if r and (show_all or (ref_val - r['total'] >= 0)):
                    r['ref'] = ref_val
                    results.append(r)
            
            done = min(i + chunk_size, len(raw_tasks))
            elapsed = time.time() - start_time
            rps = done / elapsed if elapsed > 0 else 0
            prog_bar.progress(done / len(raw_tasks))
            status_area.markdown(f"""
            <div class="status-card">
                <b>進度:</b> {done} / {len(raw_tasks)} | 
                <b>時速:</b> {rps:.1f} 筆/秒 | 
                <b>捕捉到:</b> {len(results)} 組
            </div>
            """, unsafe_allow_html=True)

        st.session_state.valid_offers = results
        st.rerun()

# 🛡️ 排雷 2：使用 try...finally 確保按鈕不會永久假死
if st.button("🔥 啟動鋼鐵獵殺", disabled=st.session_state.is_hunting):
    st.session_state.is_hunting = True
    try:
        asyncio.run(start_hunt())
    finally:
        st.session_state.is_hunting = False

# ==========================================
# 📊 矩陣展示
# ==========================================
def render_matrix(res_list, ref):
    if not res_list: return ""
    d1_dates = sorted(list(set(r['d1'] for r in res_list)))
    d4_dates = sorted(list(set(r['d4'] for r in res_list)))
    matrix = {}
    prices = [r['total'] for r in res_list]
    # 🛡️ 排雷 5：確保 prices 有值才計算 min/max
    min_p, max_p = min(prices) if prices else 0, max(prices) if prices else 0
    for r in res_list:
        key = (r['d1'], r['d4'])
        if key not in matrix or r['total'] < matrix[key]['total']: matrix[key] = r

    h = '<div style="background:#fff; padding:10px; border-radius:8px; overflow-x:auto;"><table style="width:100%; border-collapse:collapse; font-size:10px; color:#333;" border="1">'
    h += '<tr style="background:#333; color:#fff;"><th>D4↘\\D1➡</th>' + "".join([f"<th>{d[5:]}</th>" for d in d1_dates]) + '</tr>'
    for d4 in d4_dates:
        h += f'<tr><td style="background:#f2f2f2; font-weight:bold;">{d4[5:]}</td>'
        for d1 in d1_dates:
            rec = matrix.get((d1, d4))
            if rec:
                save = ref - rec['total']
                alpha = 0.8 if max_p <= min_p else 0.8 - 0.7 * ((rec['total'] - min_p) / (max_p - min_p))
                bg = f"rgba(0, 230, 118, {alpha:.2f})" if save >= 0 else "rgba(255, 182, 193, 0.4)"
                h += f'<td style="background:{bg}; padding:4px;"><b>{rec["total"]:,}</b><br><span style="color:{"#d32f2f" if save>=0 else "#1976d2"}">{"省" if save>=0 else "貴"}{abs(save):,}</span></td>'
            else: h += '<td>-</td>'
        h += '</tr>'
    return h + '</table></div>'

if st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    routes = sorted(list(set(f"{r['h1']} ➔ {r['h4']}" for r in res)))
    tabs = st.tabs(["🏆 綜合最優"] + routes)
    with tabs[0]:
        st.markdown(render_matrix(res, st.session_state.ref_price), unsafe_allow_html=True)
        st.write("📋 詳細排行:")
        for r in res[:30]:
            save = st.session_state.ref_price - r['total']
            with st.expander(f"💰 {r['total']:,} | {'🔥 省' if save>=0 else '📉 貴'} {abs(save):,} ({r['h1'][:3]} {r['d1']} ➔ {r['h4'][:3]} {r['d4']})"):
                st.write(f"航班: {' | '.join(r['legs'])}")
    for i, route in enumerate(routes):
        with tabs[i+1]:
            st.markdown(render_matrix([r for r in res if f"{r['h1']} ➔ {r['h4']}" == route], st.session_state.ref_price), unsafe_allow_html=True)
