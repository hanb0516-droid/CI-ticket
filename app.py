import streamlit as st
import httpx
import asyncio
import json
import time
from datetime import datetime, timedelta, date
from itertools import product

# ==========================================
# 0. 高性能初始化 (靜態快取)
# ==========================================
st.set_page_config(page_title="Flight Actuary | v32.0 LIGHT", page_icon="🚀", layout="wide")

@st.cache_data
def get_hubs():
    h = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
        "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
        "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
    }
    all_c = [f"{code} ({name})" for r, cities in h.items() for code, name in cities.items()]
    def f_idx(target):
        for i, s in enumerate(all_c):
            if s.startswith(target): return i
        return 0
    return h, all_c, f_idx("TPE"), f_idx("PRG"), f_idx("FRA")

CI_HUBS, ALL_CITIES, IDX_TPE, IDX_PRG, IDX_FRA = get_hubs()

# 極簡 CSS，減少瀏覽器繪圖負擔
st.markdown("<style>[data-testid='stAppViewContainer']{background-color:#0b0e14;color:#e0e0e0;}.quota-box{padding:8px;background:rgba(0,230,118,0.03);border-radius:8px;border:1px solid #00e676;margin-bottom:15px;}</style>", unsafe_allow_html=True)

try: API_KEY = st.secrets["BOOKING_API_KEY"]
except: st.error("Missing API KEY"); st.stop()

# 狀態管理 (只存前 1000 名最優解，防止 Lag)
if "results" not in st.session_state: st.session_state.results = []
if "is_hunting" not in st.session_state: st.session_state.is_hunting = False
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000

# ==========================================
# 1. 核心引擎 (異步流式)
# ==========================================
async def fetch_api(client, sem, legs, cabin, h1, h4, d1, d4):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    async with sem:
        for _ in range(2):
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=18.0)
                if res.status_code == 200:
                    raw = res.json()
                    offers = []
                    for o in raw.get('data', {}).get('flightOffers', []):
                        l_sum, is_ci = [], True
                        for seg in o.get('segments', []):
                            f = seg.get('legs', [{}])[0].get('flightInfo', {})
                            if f.get('carrierInfo', {}).get('operatingCarrier') != "CI":
                                is_ci = False; break
                            l_sum.append(f"CI{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        if is_ci and len(l_sum) == len(legs):
                            offers.append({"total": p, "legs": l_sum, "h1": h1[:3], "h4": h4[:3], "d1": d1, "d4": d4})
                    return sorted(offers, key=lambda x: x['total'])[0] if offers else None
                elif res.status_code == 429: await asyncio.sleep(2)
            except: pass
        return None

# ==========================================
# 2. UI 佈局 (隔離渲染，保證秒開)
# ==========================================
st.markdown(f'<div class="quota-box">🚀 <b>v32.0 極速版：</b> 已解決 UI 卡頓 | 🎯 基準：{st.session_state.ref_price:,}</div>', unsafe_allow_html=True)

# 把設定欄位放在前面
with st.container():
    trip_mode = st.radio("模式", ["來回", "多點進出"], horizontal=True)
    c1, c2 = st.columns(2)
    if trip_mode == "來回":
        with c1:
            b_org = st.selectbox("起點", ALL_CITIES, index=IDX_TPE)
            d2_dt = st.date_input("D2 去程", value=date(2026, 6, 11))
        with c2:
            b_dst = st.selectbox("終點", ALL_CITIES, index=IDX_PRG)
            d3_dt = st.date_input("D3 回程", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
    else:
        with c1:
            d2os = st.selectbox("D2 起點", ALL_CITIES, index=IDX_TPE)
            d2ds = st.selectbox("D2 目的地", ALL_CITIES, index=IDX_PRG)
            d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
        with c2:
            d3os = st.selectbox("D3 出發地", ALL_CITIES, index=IDX_FRA)
            d3ds = st.selectbox("D3 目的地", ALL_CITIES, index=IDX_TPE)
            d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

with st.expander("🌍 外站雷達設定", expanded=True):
    sync = st.checkbox("D4 同步 D1", value=True)
    cr1, cr4 = st.columns(2)
    with cr1:
        regs = st.multiselect("區域", list(CI_HUBS.keys()))
        if regs:
            flt = [f"{c} ({n})" for r in regs for c, n in CI_HUBS[r].items()]
            d1_h = st.multiselect("📍 D1 起點", options=flt, default=flt)
        else: d1_h = st.multiselect("📍 D1 起點", options=ALL_CITIES)
        d1_r = st.date_input("D1 範圍", value=(date(2026, 6, 10), date(2026, 6, 10)))
    with cr4:
        d4_h = d1_h if sync else st.multiselect("📍 D4 終點", ALL_CITIES)
        d4_r = st.date_input("D4 範圍", value=(date(2026, 6, 26), date(2026, 6, 26)))

with st.sidebar:
    st.header("⚙️ 引擎")
    cabin_opt = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cab = st.selectbox("艙等", list(cabin_opt.keys()))
    concy = st.slider("併發壓力", 20, 100, 40)
    show_all = st.checkbox("👁️ 透視模式", value=False)
    if st.button("🚨 重置/清除"): 
        st.session_state.results = []; st.session_state.is_hunting = False; st.rerun()

# ==========================================
# 3. 獵殺邏輯
# ==========================================
async def run_hunt():
    d1_s, d1_e = (d1_r[0], d1_r[-1]) if isinstance(d1_r, (list, tuple)) else (d1_r, d1_r)
    d4_s, d4_e = (d4_r[0], d4_r[-1]) if isinstance(d4_r, (list, tuple)) else (d4_r, d4_r)
    tasks = []
    for h1r, h4r in product(d1_h, d4_h):
        h1, h4 = h1r.split(" ")[0], h4r.split(" ")[0]
        for d1, d4 in product([d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)], 
                              [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]):
            if d1 <= d2_dt and d4 >= d3_dt:
                l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                     {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                tasks.append((l, cabin_opt[cab], h1r, h4r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks: st.warning("無效日期"); return

    bar = st.progress(0)
    status = st.empty()
    res_list = []
    
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    async with httpx.AsyncClient(timeout=25.0, limits=limits) as client:
        # 校準直飛
        d_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                  {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
        ref_res = await fetch_api(client, asyncio.Semaphore(1), d_legs, cabin_opt[cab], "", "", "", "")
        ref_val = ref_res['total'] if ref_res else 200000
        st.session_state.ref_price = ref_val

        sem = asyncio.Semaphore(concy)
        start_t, last_up = time.time(), time.time()
        coros = [fetch_api(client, sem, t[0], t[1], t[2], t[3], t[4], t[5]) for t in tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            r = await coro
            if r and (show_all or (ref_val - r['total'] >= 0)):
                res_list.append(r)
            
            # 🛡️ 排雷 4：降頻 UI 刷新，每 2 秒才更新一次
            now = time.time()
            if now - last_up > 2.0 or (i+1) == len(tasks):
                done = i + 1
                rps = done / (now - start_t)
                bar.progress(done / len(tasks))
                status.info(f"⚡ 進度: {done}/{len(tasks)} | 時速: {rps:.1f} RPS | 已獲取: {len(res_list)}")
                last_up = now

        # 🛡️ 排雷 1：只存前 1,000 筆，徹底解決 Lag
        st.session_state.results = sorted(res_list, key=lambda x: x['total'])[:1000]
        st.rerun()

if st.button("🔥 啟動極速獵殺", disabled=st.session_state.is_hunting, use_container_width=True):
    st.session_state.is_hunting = True
    try: asyncio.run(run_hunt())
    finally: st.session_state.is_hunting = False; st.rerun()

# ==========================================
# 📊 戰果區 (🛡️ 排雷 2：僅渲染 Top 50)
# ==========================================
def draw_table(data, ref):
    if not data: return ""
    d1_d = sorted(list(set(r['d1'] for r in data)))
    d4_d = sorted(list(set(r['d4'] for r in data)))
    matrix = {(r['d1'], r['d4']): r for r in data}
    prices = [r['total'] for r in data]
    mi, ma = min(prices), max(prices)
    
    h = '<div style="overflow-x:auto;"><table border="1" style="width:100%;border-collapse:collapse;font-size:10px;text-align:center;color:#333;background:#fff;">'
    h += '<tr style="background:#333;color:#fff;"><th>D4↘\\D1➡</th>' + "".join([f"<th>{d[5:]}</th>" for d in d1_d]) + '</tr>'
    for d4 in d4_d:
        h += f'<tr><td style="background:#f2f2f2;font-weight:bold;">{d4[5:]}</td>'
        for d1 in d1_d:
            r = matrix.get((d1, d4))
            if r:
                diff = ref - r['total']
                alpha = 0.8 if ma <= mi else 0.8 - 0.7*((r['total']-mi)/(ma-mi))
                bg = f"rgba(0,230,118,{alpha:.2f})" if diff >= 0 else "rgba(255,182,193,0.4)"
                h += f'<td style="background:{bg};padding:4px;"><b>{r["total"]:,}</b><br><span style="color:{"#d32f2f" if diff>=0 else "#1976d2"}">{"省" if diff>=0 else "貴"}{abs(diff):,}</span></td>'
            else: h += '<td>-</td>'
        h += '</tr>'
    return h + '</table></div>'

if st.session_state.results:
    st.markdown("---")
    tabs = st.tabs(["🏆 綜合排行", "📊 價格矩陣"])
    with tabs[0]:
        st.write("📋 獲利神票 Top 50:")
        for r in st.session_state.results[:50]:
            diff = st.session_state.ref_price - r['total']
            with st.expander(f"💰 {r['total']:,} | {'省' if diff>=0 else '貴'} {abs(diff):,} ({r['h1']}➔{r['h4']})"):
                st.write(f"日期: {r['d1']}~{r['d4']} | 航班: {' | '.join(r['legs'])}")
    with tabs[1]:
        st.markdown(draw_table(st.session_state.results, st.session_state.ref_price), unsafe_allow_html=True)
