import streamlit as st
import requests
import json
import time
import random
import gc  
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. 企業級 UI 與金鑰設定
# ==========================================
st.set_page_config(page_title="Flight Actuary | 華航外站獵殺器", page_icon="✈️", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-image: linear-gradient(rgba(10, 15, 30, 0.2), rgba(10, 15, 30, 0.6)), url("https://images.unsplash.com/photo-1436491865332-7a61a109cc05?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important; background-position: center !important; background-attachment: fixed !important;
    }
    [data-testid="stExpander"] {
        background-color: rgba(15, 25, 40, 0.4) !important;
        backdrop-filter: blur(16px) !important; -webkit-backdrop-filter: blur(16px) !important;
        border: 1px solid rgba(255, 255, 255, 0.2) !important; border-radius: 12px !important;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.4) !important; margin-bottom: 12px;
    }
    .stTextInput>div>div>input, .stSelectbox>div>div>div, .stDateInput>div>div>input, .stNumberInput>div>div>input {
        background-color: rgba(10, 15, 25, 0.5) !important; color: #ffffff !important; border: 1px solid rgba(255, 255, 255, 0.25) !important;
    }
    .custom-title {
        background: linear-gradient(45deg, #00d2ff, #3a7bd5); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 2.8rem; margin-bottom: -10px; letter-spacing: 1px; text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
    }
    .custom-subtitle {
        color: #e2e8f0; font-size: 1.1rem; font-weight: 600; margin-bottom: 20px; text-shadow: 1px 1px 3px rgba(0,0,0,0.5);
    }
    /* 即時戰報高亮區塊 */
    .live-hit {
        padding: 10px; border-left: 5px solid #00e676; background: rgba(0, 230, 118, 0.1); margin-bottom: 10px; border-radius: 4px;
    }
</style>
""", unsafe_allow_html=True)

try:
    raw_key = st.secrets["BOOKING_API_KEY"]
    BOOKING_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
except KeyError:
    st.error("🚨 系統找不到 Booking API 金鑰！請確認您已在 Streamlit 後台設定了 BOOKING_API_KEY。")
    st.stop()

CI_ASIAN_HUBS = {
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "TAK": "高松", "HIJ": "廣島", "KOJ": "鹿兒島", "KMQ": "小松", "TOY": "富山", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "港澳": {"HKG": "香港", "MFM": "澳門"}
}
ALL_FORMATTED_CITIES = [f"{code} ({name})" for region, cities in CI_ASIAN_HUBS.items() for code, name in cities.items()]

# ==========================================
# 1. 🌟 核心引擎：解析與搜尋
# ==========================================
def parse_booking_response(raw_data, title, d1, d4, strict_ci):
    try:
        flight_offers = raw_data.get('data', {}).get('flightOffers', [])
        valid_results = []
        for offer in flight_offers:
            is_valid, legs_summary = True, []
            for seg in offer.get('segments', []):
                legs_list = seg.get('legs', [])
                first_leg = legs_list[0] if len(legs_list) > 0 else {}
                carrier = first_leg.get('flightInfo', {}).get('carrierInfo', {}).get('operatingCarrier', 'Unknown')
                flight_num = first_leg.get('flightInfo', {}).get('flightNumber', '')
                dep_code, arr_code = seg.get('departureAirport', {}).get('code', '???'), seg.get('arrivalAirport', {}).get('code', '???')
                dep_time = seg.get('departureTime', '').replace('T', ' ')[:16]

                if strict_ci and carrier != "CI":
                    is_valid = False; break
                legs_summary.append(f"{carrier}{flight_num} | {dep_code} ➔ {arr_code} | {dep_time}")

            if is_valid and len(legs_summary) == 4: 
                price = offer.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                valid_results.append({"title": title, "total": price, "currency": "TWD", "legs": legs_summary, "d1": d1, "d4": d4})
        
        if valid_results:
            valid_results.sort(key=lambda x: x['total'])
            return valid_results[0]
    except Exception: pass
    return None

def fetch_booking_bundle(legs, cabin, strict_ci, title="", d1="", d4="", debug_mode=False):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": c_map[cabin], "adults": "1", "currency_code": "TWD"}, timeout=45)
            if res.status_code == 200:
                raw_data = res.json()
                if title: 
                    return {"status": "success", "raw": raw_data if debug_mode else None, "offer": parse_booking_response(raw_data, title, d1, d4, strict_ci), "title": title}
                else:
                    offers = raw_data.get('data', {}).get('flightOffers', [])
                    return {"status": "success", "price": offers[0].get('priceBreakdown', {}).get('total', {}).get('units', 0)} if offers else {"status": "error", "error": "查無基準票價"}
            elif res.status_code in [429, 403]:
                # 💣 額度耗盡偵測器
                if "exceeded" in res.text.lower() or "quota" in res.text.lower() or "limit" in res.text.lower():
                    return {"status": "quota_exceeded", "error": "API 額度已耗盡"}
                time.sleep((2 ** attempt) + random.uniform(0.5, 1.5))
                continue
            else: return {"status": "error", "error": f"HTTP {res.status_code}"}
        except Exception as e: return {"status": "error", "error": str(e)}
    return {"status": "error", "error": "HTTP 429 (重試達上限)"}

# ==========================================
# 2. UI 面板配置
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)
st.markdown('<p class="custom-subtitle">中華航空 (CI) 外站四段聯程票・全亞洲動態精算雷達</p>', unsafe_allow_html=True)
st.markdown("---")

c_toggles = st.columns(2)
with c_toggles[0]: strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI) 航班", value=True)
with c_toggles[1]: debug_mode = st.checkbox("🛠️ 開啟 Debug 模式 (顯示 JSON)", value=False) 

st.subheader("📌 第一步：核心行程 (D2 / D3)")
c_d2, c_d3 = st.columns(2)
with c_d2:
    d2_org = st.text_input("D2 出發", value="TPE").upper()
    d2_dst = st.text_input("D2 抵達", value="PRG").upper()
    d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
with c_d3:
    d3_org = st.text_input("D3 出發", value="FRA").upper()
    d3_dst = st.text_input("D3 抵達", value="TPE").upper()
    d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

st.subheader("🌍 第二步：外站雷達探測區間 (D1 / D4)")
c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_regions = st.multiselect("🗂️ 批次全選 (D1)", ["全部", "東南亞", "東北亞", "港澳"], default=["港澳"])
    d1_defaults = ALL_FORMATTED_CITIES if "全部" in d1_regions else [f"{c} ({n})" for r in d1_regions if r in CI_ASIAN_HUBS for c, n in CI_ASIAN_HUBS[r].items()]
    d1_hubs_raw = st.multiselect("📍 D1 盲測起點庫", ALL_FORMATTED_CITIES, default=d1_defaults, key="d1_city")
    d1_date_range = st.date_input("📅 D1 壓縮日期區間", value=(date(2026, 6, 10), date(2026, 6, 11)), key="d1_date")

with c_d4:
    d4_regions = st.multiselect("🗂️ 批次全選 (D4)", ["全部", "東南亞", "東北亞", "港澳"], default=["港澳"])
    d4_defaults = ALL_FORMATTED_CITIES if "全部" in d4_regions else [f"{c} ({n})" for r in d4_regions if r in CI_ASIAN_HUBS for c, n in CI_ASIAN_HUBS[r].items()]
    d4_hubs_raw = st.multiselect("📍 D4 盲測終點庫", ALL_FORMATTED_CITIES, default=d4_defaults, key="d4_city")
    d4_date_range = st.date_input("📅 D4 壓縮日期區間", value=(date(2026, 6, 25), date(2026, 6, 26)), key="d4_date")

st.subheader("🎯 第三步：精算參數與保底設定")
c_cab, c_ref1, c_ref2 = st.columns([1, 1.5, 1.5])
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_ref1: fallback_d2d3 = st.number_input("保底 D2/D3 直飛票價", value=175000, step=1000)
with c_ref2: fallback_d1d4 = st.number_input("保底 D1/D4 亞洲票價", value=25000, step=1000)

# ==========================================
# 3. 執行邏輯 
# ==========================================
if st.button("🚀 啟動 Actuary 獵殺引擎", use_container_width=True):
    if len(d1_date_range) != 2 or len(d4_date_range) != 2: st.error("⚠️ 日期區間錯誤"); st.stop()
    if not d1_hubs_raw or not d4_hubs_raw: st.error("⚠️ 請保留至少一個外站"); st.stop()

    d1_dates = [d1_date_range[0] + timedelta(days=i) for i in range((d1_date_range[1]-d1_date_range[0]).days + 1)]
    d4_dates = [d4_date_range[0] + timedelta(days=i) for i in range((d4_date_range[1]-d4_date_range[0]).days + 1)]
    d1_codes, d4_codes = [h.split(" ")[0] for h in d1_hubs_raw], [h.split(" ")[0] for h in d4_hubs_raw]
    
    baseline_cache = {}
    core_legs = [{"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}]
    res_core = fetch_booking_bundle(core_legs, cabin_choice, strict_ci=False)
    core_baseline_price = res_core.get("price", fallback_d2d3) if res_core["status"] == "success" else fallback_d2d3
    
    out_combinations = list(product(d1_codes, d4_codes))
    if len(out_combinations) > 10:
        for h1, h4 in out_combinations: baseline_cache[f"{h1}_{h4}"] = fallback_d1d4
    else:
        d1_rep, d4_rep = d1_dates[0].strftime("%Y-%m-%d"), d4_dates[0].strftime("%Y-%m-%d")
        for h1, h4 in out_combinations:
            res_out = fetch_booking_bundle([{"fromId": f"{h1}.AIRPORT", "toId": "TPE.AIRPORT", "date": d1_rep}, {"fromId": "TPE.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4_rep}], cabin_choice, strict_ci=False)
            baseline_cache[f"{h1}_{h4}"] = res_out.get("price", fallback_d1d4) if res_out["status"] == "success" else fallback_d1d4

    all_tasks = []
    for h1_raw, h4_raw in product(d1_hubs_raw, d4_hubs_raw):
        h1_code, h4_code = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
        for d1, d4 in product(d1_dates, d4_dates):
            if d1 <= d2_date and d4 >= d3_date: 
                scan_legs = [{"fromId": f"{h1_code}.AIRPORT", "toId": f"{d2_org}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, {"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_dst}.AIRPORT", "toId": f"{h4_code}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                all_tasks.append((scan_legs, cabin_choice, strict_ci_toggle, f"{h1_raw} ➔ {h4_raw}", d1, d4, debug_mode, h1_code, h4_code))

    total_tasks = len(all_tasks)
    if total_tasks == 0: st.warning("⚠️ 無有效日期組合。"); st.stop()

    msg = st.warning(f"🔥 任務總數 {total_tasks} 組。掃描啟動中...")
    pb = st.progress(0)
    live_feed = st.empty() # 即時戰報顯示區
    
    valid_results, raw_debug_data, error_count, processed_count = [], [], 0, 0  
    BATCH_SIZE = 100
    quota_dead = False

    for i in range(0, total_tasks, BATCH_SIZE):
        if quota_dead: break
        batch_tasks = all_tasks[i : i + BATCH_SIZE]
        
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5], t[6]): t for t in batch_tasks}
            for f in as_completed(futures):
                task_meta = futures[f]
                h1_code, h4_code = task_meta[7], task_meta[8]
                processed_count += 1
                try:
                    res = f.result()
                    if res["status"] == "quota_exceeded":
                        quota_dead = True
                    elif res["status"] == "success" and res["offer"]:
                        res["offer"]["dynamic_ref_price"] = core_baseline_price + baseline_cache[f"{h1_code}_{h4_code}"]
                        valid_results.append(res["offer"])
                        
                        # 🌟 即時戰報：只要有省錢，立刻印在畫面上！
                        diff = res["offer"]["dynamic_ref_price"] - res["offer"]['total']
                        if diff > 0:
                            with live_feed.container():
                                st.markdown(f"<div class='live-hit'>🔔 <b>即時尋獲！</b> {res['offer']['title']} | 總價: {res['offer']['total']:,} | <span style='color:#00e676'>省下 {diff:,}</span></div>", unsafe_allow_html=True)
                    else: error_count += 1
                except Exception: error_count += 1
                
                if processed_count % 5 == 0 or processed_count == total_tasks:
                    pb.progress(processed_count / total_tasks, text=f"掃描中: {processed_count}/{total_tasks} (尋獲: {len(valid_results)} 組)")
        
        valid_results.sort(key=lambda x: x['total'])
        valid_results = valid_results[:100]
        gc.collect()

    pb.empty(); msg.empty()

    if quota_dead:
        st.error("🚨 致命警告：您的 RapidAPI 每月免費額度已被耗盡！系統已緊急煞車。以下為斷線前為您搶救下來的機票：")

    if valid_results:
        st.success(f"🎉 為您揭曉全亞洲隱藏的最低價甜點站：")
        for r in valid_results:
            ref_price = r["dynamic_ref_price"]
            diff = ref_price - r['total']
            diff_badge = f"<span style='color:#00e676; font-weight:bold;'>🔥 狂省 {diff:,} TWD</span>" if diff > 50000 else f"<span style='color:#b2ff59;'>✨ 省下 {diff:,} TWD</span>" if diff > 0 else f"<span style='color:#ff5252;'>⚠️ 虧損 {abs(diff):,} TWD</span>"
            with st.expander(f"總價: {r['total']:,} TWD | {r['title']} (D1:{r['d1']} & D4:{r['d4']})"):
                st.markdown(f"**💰 價差精算：** 傳統分段買約 `{ref_price:,}` ➔ 隱藏聯程底價 `{r['total']:,}` ( {diff_badge} )", unsafe_allow_html=True)
                for j, leg in enumerate(r['legs'], 1): st.write(f"**段落 {j}** | 🛫 {leg}")
