import streamlit as st
import requests
import json
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. 全局初始化 & 基準風格
# ==========================================
st.set_page_config(page_title="Flight Actuary | BASELINE", page_icon="🧪", layout="wide")

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
if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000

# 建立 TCP 長連接渦輪 (退回最穩定的 requests)
if "http_session" not in st.session_state:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    session.headers.update({"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"})
    st.session_state.http_session = session

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
# 1. 任務執行引擎 (純淨 Threading 版)
# ==========================================
def fetch_task_sync(task_data):
    legs, cabin, h1, h4, d1, d4 = task_data
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    
    for _ in range(3): # 簡單重試機制
        try:
            res = st.session_state.http_session.get(url, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=15)
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
                time.sleep(1.5) # 撞牆冷卻
        except:
            time.sleep(1)
    return None

# ==========================================
# 2. UI 佈局 (無連動負擔)
# ==========================================
st.markdown(f'<div class="quota-box">🧪 <b>基準測試版：</b> 原生多執行緒架構 | 🎯 基準：{st.session_state.ref_price:,}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 引擎")
    cab_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cab = st.selectbox("艙等", list(cab_map.keys()))
    workers = st.slider("併發執行緒 (Workers)", 10, 60, 35)
    show_all = st.checkbox("👁️ 透視模式", value=False)
    auto_ref = st.checkbox("自動對標直飛", value=True)
    manual_ref = st.number_input("手動基準", value=200000)

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
# 3. 獵殺邏輯 (退回 ThreadPoolExecutor)
# ==========================================
if st.button("🚀 啟動基準獵殺", use_container_width=True):
    st.session_state.valid_offers = [] # 啟動時清空舊資料
    
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
    else:
        bar = st.progress(0, text="準備發射...")
        res_list = []
        ref_val = manual_ref
        
        # 校準直飛
        if auto_ref:
            d_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                      {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            ref_res = fetch_task_sync((d_legs, cab_map[cab], "", "", "", ""))
            if ref_res: ref_val = ref_res['total']; st.session_state.ref_price = ref_val

        # 多執行緒開跑
        start_t = time.time()
        with ThreadPoolExecutor(max_workers=workers) as exe:
            futures = [exe.submit(fetch_task_sync, t) for t in tasks]
            for i, f in enumerate(as_completed(futures)):
                r = f.result()
                if r and (show_all or (ref_val - r['total'] >= 0)):
                    r['ref'] = ref_val
                    res_list.append(r)
                
                # 簡單的進度條刷新 (降低頻率防卡頓)
                if i % max(1, len(tasks)//20) == 0 or i == len(tasks) - 1:
                    rps = (i + 1) / (time.time() - start_t)
                    bar.progress((i + 1) / len(tasks), text=f"⚡ 進度: {i+1}/{len(tasks)} | 時速: {rps:.1f} 筆/秒 | 獲取: {len(res_list)}")

        st.session_state.valid_offers = res_list
        st.rerun()

# ==========================================
# 4. 戰果區
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    
    st.write(f"🏆 共找到 **{len(res)}** 組符合條件的機票 (對標價: {st.session_state.ref_price:,})")
    
    # 簡單列表展示
    for r in res[:50]:
        diff = st.session_state.ref_price - r['total']
        with st.expander(f"💰 {r['total']:,} | {'省' if diff>=0 else '貴'} {abs(diff):,} ({r['h1']}➔{r['h4']})"):
            st.write(f"日期: {r['d1']} ~ {r['d4']} | 航班: {' | '.join(r['legs'])}")
