import streamlit as st
import httpx
import asyncio
import json
import time
from datetime import datetime, timedelta, date
from itertools import product

# ==========================================
# 0. 全局初始化 & 性能快取
# ==========================================
st.set_page_config(page_title="Flight Actuary | v31.3 INSTANT", page_icon="🚀", layout="wide")

@st.cache_data
def get_static_data():
    hubs = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
        "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
        "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
    }
    all_c = [f"{c} ({n})" for r, cities in hubs.items() for c, n in cities.items()]
    def find_idx(code):
        for i, s in enumerate(all_c):
            if s.startswith(code): return i
        return 0
    return hubs, all_c, find_idx("TPE"), find_idx("PRG"), find_idx("FRA")

CI_HUBS, ALL_CITIES, IDX_TPE, IDX_PRG, IDX_FRA = get_static_data()

# 🛡️ 排雷 3：CSS 最小化注入
st.markdown("""
<style>
    [data-testid="stAppViewContainer"] { background-color: #0b0e14; color: #e0e0e0; }
    .stTable { font-size: 10px !important; }
    .quota-box { padding: 10px; background: rgba(0, 230, 118, 0.03); border-radius: 8px; border: 1px solid #00e676; margin: 10px 0 20px 0; }
    .status-card { padding: 12px; background: rgba(0, 230, 118, 0.08); border-radius: 8px; border: 1px solid #00e676; }
</style>
""", unsafe_allow_html=True)

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except:
    st.error("🚨 API_KEY Missing"); st.stop()

# 輕量化狀態管理
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "ref_price" not in st.session_state: st.session_state.ref_price = 0
if "is_hunting" not in st.session_state: st.session_state.is_hunting = False

# ==========================================
# 1. 核心異步引擎
# ==========================================
async def fetch_task(client, sem, task_data):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    legs, cabin, h1, h4, d1, d4 = task_data
    async with sem:
        for attempt in range(2):
            try:
                res = await client.get(url, headers=headers, params={
                    "legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"
                }, timeout=18.0)
                if res.status_code == 200:
                    raw = res.json()
                    valid = []
                    for o in raw.get('data', {}).get('flightOffers', []):
                        l_sum, is_ci = [], True
                        for seg in o.get('segments', []):
                            f = seg.get('legs', [{}])[0].get('flightInfo', {})
                            if f.get('carrierInfo', {}).get('operatingCarrier') != "CI":
                                is_ci = False; break
                            l_sum.append(f"CI{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        if is_ci and len(l_sum) == len(legs):
                            # 🛡️ 排雷 2：數據精簡存儲
                            valid.append({"total": p, "legs": l_sum, "h1": h1[:3], "h4": h4[:3], "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: await asyncio.sleep(3)
            except: pass
        return None

# ==========================================
# 2. UI 佈局 (優先渲染)
# ==========================================
st.markdown(f'<div class="quota-box">💎 <b>v31.3 瞬時引擎：</b> 已優化 6,000 筆數據渲染效率 | 🎯 基準：{st.session_state.ref_price:,} TWD</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 引擎超頻")
    cabin_opt = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cabin = st.selectbox("艙等", list(cabin_opt.keys()))
    show_all = st.checkbox("👁️ 透視模式", value=False)
    concurrency = st.slider("併發壓力", 20, 100, 50)
    st.markdown("---")
    auto_ref = st.checkbox("自動對標直飛", value=True)
    manual_ref = st.number_input("手動基準", value=200000)
    if st.button("🚨 重置引擎"):
        st.session_state.valid_offers = []; st.session_state.is_hunting = False; st.rerun()

# 核心行程區塊
with st.container():
    trip_mode = st.radio("模式", ["來回", "多點進出"], horizontal=True)
    c1, c2 = st.columns(2)
    if trip_mode == "來回":
        with c1:
            b_org = st.selectbox("起點", ALL_CITIES, index=IDX_TPE)
            d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
        with c2:
            b_dst = st.selectbox("終點", ALL_CITIES, index=IDX_PRG)
            d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
    else:
        with c1:
            d2os = st.selectbox("D2 起點", ALL_CITIES, index=IDX_TPE)
            d2ds = st.selectbox("D2 終點", ALL_CITIES, index=IDX_PRG)
            d2_dt = st.date_input("D2 出發", value=date(2026, 6, 11))
        with c2:
            d3os = st.selectbox("D3 起點", ALL_CITIES, index=IDX_FRA)
            d3ds = st.selectbox("D3 終點", ALL_CITIES, index=IDX_TPE)
            d3_dt = st.date_input("D3 回程", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

# 外站雷達區塊
with st.container():
    st.markdown("---")
    st.checkbox("👯 D4 同步 D1", value=True, key="sync_ui")
    cr1, cr4 = st.columns(2)
    with cr1:
        d1_regs = st.multiselect("區域過濾", list(CI_HUBS.keys()))
        if d1_regs:
            opts = [f"{c} ({n})" for r in d1_regs for c, n in CI_HUBS[r].items()]
            d1_hubs = st.multiselect("📍 D1 起點", options=opts, default=opts)
        else:
            d1_hubs = st.multiselect("📍 D1 起點", options=ALL_CITIES)
        d1_range = st.date_input("D1 範圍", value=(date(2026, 6, 10), date(2026, 6, 10)))
    with cr4:
        d4_hubs = d1_hubs if st.session_state.sync_ui else st.multiselect("📍 D4 終點", ALL_CITIES)
        d4_range = st.date_input("D4 範圍", value=(date(2026, 6, 26), date(2026, 6, 26)))

# ==========================================
# 3. 獵殺邏輯
# ==========================================
async def start_hunt():
    d1_s, d1_e = (d1_range[0], d1_range[-1]) if isinstance(d1_range, (list, tuple)) else (d1_range, d1_range)
    d4_s, d4_e = (d4_range[0], d4_range[-1]) if isinstance(d4_range, (list, tuple)) else (d4_range, d4_range)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]

    raw_tasks = []
    for h1_r, h4_r in product(d1_hubs, d4_hubs):
        h1, h4 = h1_r.split(" ")[0], h4_r.split(" ")[0]
        for d1, d4 in product(d1_list, d4_list):
            if d1 <= d2_dt and d4 >= d3_dt:
                l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                     {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                raw_tasks.append((l, cabin_opt[cabin], h1_r, h4_r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not raw_tasks: st.warning("任務為 0"); return

    status_area = st.empty()
    prog_bar = st.progress(0)
    
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        ref_val = manual_ref
        if auto_ref:
            d_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                      {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            res = await fetch_task(client, asyncio.Semaphore(1), (d_legs, cabin_opt[cabin], "", "", "", ""))
            if res: ref_val = res['total']; st.session_state.ref_price = ref_val

        sem = asyncio.Semaphore(concurrency)
        results, start_time, last_ui = [], time.time(), time.time()
        coros = [fetch_task(client, sem, t) for t in raw_tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            res = await coro
            if res and (show_all or (ref_val - res['total'] >= 0)):
                res['ref'] = ref_val
                results.append(res)
            
            curr = time.time()
            if curr - last_ui > 1.2 or (i + 1) == len(raw_tasks):
                done = i + 1
                rps = done / (curr - start_time) if curr > start_time else 0
                prog_bar.progress(done / len(raw_tasks))
                status_area.markdown(f'<div class="status-card"><b>進度:</b> {done}/{len(raw_tasks)} | <b>時速:</b> {rps:.1f} RPS | <b>鎖定:</b> {len(results)}</div>', unsafe_allow_html=True)
                last_ui = curr

        st.session_state.valid_offers = results
        st.rerun()

if st.button("🔥 啟動極速獵殺", disabled=st.session_state.is_hunting, use_container_width=True):
    st.session_state.valid_offers = []
    st.session_state.is_hunting = True
    try: asyncio.run(start_hunt())
    finally: st.session_state.is_hunting = False; st.rerun()

# ==========================================
# 📊 矩陣展示 (🛡️ 排雷 3：高效渲染)
# ==========================================
def render_matrix(res_list, ref):
    if not res_list: return ""
    # 預先處理數據，減少 HTML 迴圈負擔
    d1_dates = sorted(list(set(r['d1'] for r in res_list)))
    d4_dates = sorted(list(set(r['d4'] for r in res_list)))
    matrix = {(r['d1'], r['d4']): r for r in sorted(res_list, key=lambda x: x['total'], reverse=True)}
    
    prices = [r['total'] for r in res_list]
    min_p, max_p = min(prices), max(prices)

    h = '<div style="background:#fff; padding:8px; border-radius:8px; overflow-x:auto;"><table style="width:100%; border-collapse:collapse; font-size:10px; color:#333;" border="1">'
    h += '<tr style="background:#333; color:#fff;"><th>D4↘\\D1➡</th>' + "".join([f"<th>{d[5:]}</th>" for d in d1_dates]) + '</tr>'
    for d4 in d4_dates:
        h += f'<tr><td style="background:#f2f2f2; font-weight:bold;">{d4[5:]}</td>'
        for d1 in d1_dates:
            rec = matrix.get((d1, d4))
            if rec:
                save = ref - rec['total']
                alpha = 0.8 if max_p <= min_p else 0.8 - 0.7 * ((rec['total'] - min_p) / (max_p - min_p))
                bg = f"rgba(0, 230, 118, {alpha:.2f})" if save >= 0 else "rgba(255, 182, 193, 0.4)"
                h += f'<td style="background:{bg}; padding:2px; text-align:center;"><b>{rec["total"]:,}</b><br><span style="color:{"#d32f2f" if save>=0 else "#1976d2"}">{"省" if save>=0 else "貴"}{abs(save):,}</span></td>'
            else: h += '<td>-</td>'
        h += '</tr>'
    return h + '</table></div>'

if st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    routes = sorted(list(set(f"{r['h1']} ➔ {r['h4']}" for r in res)))
    tabs = st.tabs(["🏆 綜合"] + routes)
    
    with tabs[0]:
        st.markdown(render_matrix(res, st.session_state.ref_price), unsafe_allow_html=True)
        st.write("📋 獲利排行 (Top 50):") # 🛡️ 排雷 4：限制 DOM 節點數量
        for r in res[:50]:
            save = st.session_state.ref_price - r['total']
            with st.expander(f"💰 {r['total']:,} | {'省' if save>=0 else '貴'} {abs(save):,} ({r['h1']}➔{r['h4']})"):
                st.write(f"日期: {r['d1']} / {r['d4']} | 航班: {' | '.join(r['legs'])}")

    for i, route in enumerate(routes):
        with tabs[i+1]:
            route_data = [r for r in res if f"{r['h1']} ➔ {r['h4']}" == route]
            st.markdown(render_matrix(route_data, st.session_state.ref_price), unsafe_allow_html=True)
