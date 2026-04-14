import streamlit as st
import httpx
import asyncio
import json
import time
import random
import uuid
from datetime import datetime, timedelta, date
from itertools import product

# ==========================================
# 0. 全局初始化 & 基準風格
# ==========================================
st.set_page_config(page_title="Flight Actuary | v34.0 HYBRID", page_icon="🚀", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp { background-color: #0b0e14; color: #e0e0e0; }
    html, body, [class*="st-"] { font-size: 13px !important; }
    .quota-box { padding: 10px; background: rgba(0, 230, 118, 0.05); border-radius: 8px; border: 1px solid #00e676; margin-bottom: 15px; }
</style>
""", unsafe_allow_html=True)

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 缺少 API KEY"); st.stop()

# 狀態管理
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "is_hunting" not in st.session_state: st.session_state.is_hunting = False
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000
if "run_id" not in st.session_state: st.session_state.run_id = None

CI_GLOBAL_HUBS = {
    "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
    "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
    "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
}
ALL_CITIES = [f"{code} ({name})" for r, cities in CI_GLOBAL_HUBS.items() for code, name in cities.items()]

def get_city_idx(code):
    for i, s in enumerate(ALL_CITIES):
        if s.startswith(code): return i
    return 0

# ==========================================
# 1. 任務執行引擎 (帶有防禦機制的 Asyncio)
# ==========================================
async def fetch_task_async(client, sem, task_data, current_run_id):
    # 🛡️ 排雷二：殭屍檢測，如果 ID 不符立刻退出
    if st.session_state.run_id != current_run_id: return None
    
    legs, cabin, h1, h4, d1, d4 = task_data
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    
    async with sem:
        for attempt in range(3):
            if st.session_state.run_id != current_run_id: return None # 二次檢測
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=18.0)
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
                            valid.append({"total": p, "legs": l_sum, "h1": h1[:3], "h4": h4[:3], "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429:
                    # 🛡️ 排雷一：隨機抖動 (Jitter)，破解 429 死亡螺旋
                    await asyncio.sleep(1.0 + random.uniform(0.5, 2.0))
            except:
                await asyncio.sleep(0.5)
        return None

# ==========================================
# 2. UI 佈局 (保持上一版的零卡頓結構)
# ==========================================
st.markdown(f'<div class="quota-box">🚀 <b>v34.0 終極引擎：</b> 破冰提速 & 防殭屍進程 | 🎯 基準：{st.session_state.ref_price:,}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 引擎控制")
    cab_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cab = st.selectbox("艙等", list(cab_map.keys()))
    workers = st.slider("異步併發上限", 20, 80, 40)
    show_all = st.checkbox("👁️ 透視模式", value=False)
    auto_ref = st.checkbox("自動對標直飛", value=True)
    manual_ref = st.number_input("手動基準", value=200000)
    
    st.markdown("---")
    # 🛡️ 急停開關
    if st.button("🛑 停止 / 重置引擎", type="primary"):
        st.session_state.run_id = None # 瞬間賜死所有背景工人
        st.session_state.is_hunting = False
        st.session_state.valid_offers = []
        st.rerun()

with st.container():
    trip_mode = st.radio("行程模式", ["來回", "多點進出"], horizontal=True)
    c1, c2 = st.columns(2)
    if trip_mode == "來回":
        with c1:
            b_org = st.selectbox("起點", ALL_CITIES, index=get_city_idx("TPE"))
            d2_dt = st.date_input("D2 去程", value=date(2026, 6, 11))
        with c2:
            b_dst = st.selectbox("終點", ALL_CITIES, index=get_city_idx("PRG"))
            d3_dt = st.date_input("D3 回程", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
    else:
        with c1:
            d2os = st.selectbox("D2 起點", ALL_CITIES, index=get_city_idx("TPE"))
            d2ds = st.selectbox("D2 目的地", ALL_CITIES, index=get_city_idx("PRG"))
            d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
        with c2:
            d3os = st.selectbox("D3 出發地", ALL_CITIES, index=get_city_idx("FRA"))
            d3ds = st.selectbox("D3 目的地", ALL_CITIES, index=get_city_idx("TPE"))
            d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

st.markdown("---")
with st.container():
    sync = st.checkbox("👯 D4 同步 D1", value=True)
    cr1, cr4 = st.columns(2)
    with cr1:
        regs = st.multiselect("區域", list(CI_GLOBAL_HUBS.keys()))
        if regs:
            flt = [f"{c} ({n})" for r in regs for c, n in CI_GLOBAL_HUBS[r].items()]
            d1_h = st.multiselect("📍 D1 起點", options=flt, default=flt)
        else:
            d1_h = st.multiselect("📍 D1 起點", options=ALL_CITIES)
        d1_r = st.date_input("D1 範圍", value=(date(2026, 6, 10), date(2026, 6, 10)))
    with cr4:
        d4_h = d1_h if sync else st.multiselect("📍 D4 終點", ALL_CITIES)
        d4_r = st.date_input("D4 範圍", value=(date(2026, 6, 26), date(2026, 6, 26)))

# ==========================================
# 3. 異步主控台
# ==========================================
async def start_async_hunt():
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
                tasks.append((l, cab_map[cab], h1r, h4r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks:
        st.warning("⚠️ 任務量為 0，請檢查日期或站點。")
        return

    # 生成本次任務專屬 ID
    my_run_id = str(uuid.uuid4())
    st.session_state.run_id = my_run_id

    bar = st.progress(0)
    status_area = st.empty()
    res_list = []
    
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    async with httpx.AsyncClient(timeout=25.0, limits=limits) as client:
        ref_val = manual_ref
        if auto_ref:
            status_area.info("🎯 校準核心直飛價格中...")
            d_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                      {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            ref_res = await fetch_task_async(client, asyncio.Semaphore(1), (d_legs, cab_map[cab], "", "", "", ""), my_run_id)
            if ref_res: ref_val = ref_res['total']; st.session_state.ref_price = ref_val

        sem = asyncio.Semaphore(workers)
        start_t = time.time()
        last_ui_update = time.time()
        
        coros = [fetch_task_async(client, sem, t, my_run_id) for t in tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            # 任務執行中，檢查是否已被使用者按下停止
            if st.session_state.run_id != my_run_id:
                status_area.warning("🚨 任務已由使用者強制中止！")
                return # 直接切斷迴圈

            r = await coro
            if r and (show_all or (ref_val - r['total'] >= 0)):
                r['ref'] = ref_val
                res_list.append(r)
            
            # 非阻塞更新 UI (每秒最多 1 次)
            now = time.time()
            if now - last_ui_update > 1.0 or i == len(tasks) - 1:
                rps = (i + 1) / (now - start_t) if now > start_t else 0
                bar.progress((i + 1) / len(tasks))
                status_area.markdown(f'<div style="color:#00e676; font-weight:bold;">⚡ 進度: {i+1}/{len(tasks)} | 時速: {rps:.1f} RPS | 尋獲神票: {len(res_list)}</div>', unsafe_allow_html=True)
                last_ui_update = now

    # 🛡️ 排雷四：結果瘦身，防止 UI 渲染癱瘓
    st.session_state.valid_offers = sorted(res_list, key=lambda x: x['total'])[:1000]
    st.session_state.is_hunting = False
    st.session_state.run_id = None
    st.rerun()

if st.button("🚀 啟動異步極速獵殺", disabled=st.session_state.is_hunting, use_container_width=True):
    st.session_state.valid_offers = []
    st.session_state.is_hunting = True
    try:
        asyncio.run(start_async_hunt())
    except Exception as e:
        st.error(f"系統異常: {e}")
        st.session_state.is_hunting = False

# ==========================================
# 4. 戰果展示
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    res = st.session_state.valid_offers
    
    st.write(f"🏆 成功鎖定 **{len(res)}** 組最佳神票 (對標價: {st.session_state.ref_price:,})")
    
    # 簡單列表展示 (最高效，不卡頓)
    for r in res[:50]:
        diff = st.session_state.ref_price - r['total']
        with st.expander(f"💰 {r['total']:,} | {'省' if diff>=0 else '貴'} {abs(diff):,} ({r['h1']}➔{r['h4']})"):
            st.write(f"日期: {r['d1']} ~ {r['d4']} | 航班: {' | '.join(r['legs'])}")
