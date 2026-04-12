import streamlit as st
import requests
import json
import time
import random
import gc
import os
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. 企業級 UI、金鑰與狀態初始化
# ==========================================
st.set_page_config(page_title="Flight Actuary | 華航外站獵殺器", page_icon="✈️", layout="wide")
BLACKBOX_FILE = "blackbox_log.jsonl"

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-image: linear-gradient(rgba(15, 20, 35, 0.2), rgba(15, 20, 35, 0.5)), 
        url("https://images.unsplash.com/photo-1436491865332-7a61a109cc05?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important; background-position: center !important; background-attachment: fixed !important;
    }
    [data-testid="stExpander"] {
        background-color: rgba(20, 35, 55, 0.6) !important; backdrop-filter: blur(15px) !important;
        border: 1px solid rgba(255, 255, 255, 0.25) !important; border-radius: 12px !important;
        box-shadow: 0 10px 40px 0 rgba(0, 0, 0, 0.5) !important; margin-bottom: 15px;
    }
    .custom-title {
        background: linear-gradient(45deg, #ffffff, #4da8da); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 3rem; margin-bottom: -5px; text-shadow: 0px 4px 10px rgba(0,0,0,0.5);
    }
    .live-hit {
        padding: 12px; border-left: 6px solid #00e676; background: rgba(0, 230, 118, 0.15); 
        margin-bottom: 12px; border-radius: 8px; color: #ffffff; font-weight: 600; backdrop-filter: blur(5px);
    }
</style>
""", unsafe_allow_html=True)

try:
    raw_key = st.secrets["BOOKING_API_KEY"]
    BOOKING_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
except KeyError:
    st.error("🚨 找不到 API 金鑰。"); st.stop()

# --- 初始化 Session State (永不掉線的核心) ---
if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "core_price" not in st.session_state: st.session_state.core_price = 175000
if "base_cache" not in st.session_state: st.session_state.base_cache = {}
if "quota_dead" not in st.session_state: st.session_state.quota_dead = False

CI_ASIAN_HUBS = {
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "TAK": "高松", "HIJ": "廣島", "KOJ": "鹿兒島", "KMQ": "小松", "TOY": "富山", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "港澳": {"HKG": "香港", "MFM": "澳門"}
}
ALL_FORMATTED_CITIES = [f"{code} ({name})" for region, cities in CI_ASIAN_HUBS.items() for code, name in cities.items()]

# ==========================================
# 1. API 請求引擎
# ==========================================
def fetch_booking_bundle(legs, cabin, strict_ci, title="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": c_map[cabin], "adults": "1", "currency_code": "TWD"}, timeout=30)
            if res.status_code == 200:
                raw = res.json()
                if not title:
                    offers = raw.get('data', {}).get('flightOffers', [])
                    return {"status": "success", "price": offers[0].get('priceBreakdown', {}).get('total', {}).get('units', 0)} if offers else {"status": "error"}
                
                valid_res = []
                for offer in raw.get('data', {}).get('flightOffers', []):
                    is_valid, l_sum = True, []
                    for seg in offer.get('segments', []):
                        f_leg = seg.get('legs', [{}])[0]
                        c_info = f_leg.get('flightInfo', {}).get('carrierInfo', {})
                        car = c_info.get('operatingCarrier') or c_info.get('marketingCarrier', '??')
                        num = f_leg.get('flightInfo', {}).get('flightNumber', '')
                        dep = seg.get('departureAirport', {}).get('code', '???')
                        arr = seg.get('arrivalAirport', {}).get('code', '???')
                        dt = seg.get('departureTime', '').replace('T', ' ')[:16]
                        if strict_ci and car != "CI": is_valid = False; break
                        l_sum.append(f"**{car}{num}** | {dep} ➔ {arr} | {dt}")
                    if is_valid and len(l_sum) == 4:
                        valid_res.append({"title": title, "total": offer.get('priceBreakdown', {}).get('total', {}).get('units', 0), "legs": l_sum, "d1": d1, "d4": d4})
                
                if valid_res:
                    valid_res.sort(key=lambda x: x['total'])
                    return {"status": "success", "offer": valid_res[0]}
                return {"status": "success", "offer": None}
            elif res.status_code in [403, 429]:
                if "quota" in res.text.lower(): return {"status": "quota_exceeded"}
                time.sleep(2); continue
            else: return {"status": "error"}
        except: return {"status": "error"}
    return {"status": "error"}

# ==========================================
# 2. UI 介面與參數設定區
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)
st.markdown('<p style="color:#cbd5e1; font-weight:600; margin-bottom:25px;">永不掉線接力版 (Anti-Timeout Engine)</p>', unsafe_allow_html=True)

# 如果引擎正在運作中，隱藏輸入框，只顯示進度與緊急按鈕
if st.session_state.engine_running:
    st.info("⚙️ **自動接力引擎運作中...** (為防止伺服器強制斷線，系統將自動分批執行並重整畫面。請勿關閉視窗。)")
    if st.button("🛑 緊急停止並檢視結果", type="primary"):
        st.session_state.engine_running = False
        st.rerun()
else:
    # --- 參數輸入區 ---
    c_toggles = st.columns(2)
    with c_toggles[0]: strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI) 航班", value=True)
    
    st.subheader("📌 核心行程 (D2 / D3)")
    c_d2, c_d3 = st.columns(2)
    with c_d2:
        d2_org = st.text_input("D2 出發", value="TPE").upper()
        d2_dst = st.text_input("D2 抵達", value="PRG").upper()
        d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
    with c_d3:
        d3_org = st.text_input("D3 出發", value="FRA").upper()
        d3_dst = st.text_input("D3 抵達", value="TPE").upper()
        d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

    st.markdown("#### 🎯 基準價分析設定")
    c_ref1, c_ref2 = st.columns(2)
    with c_ref1: fallback_d2d3 = st.number_input("保底 D2/D3 直飛價", value=175000, step=1000)
    with c_ref2: fallback_d1d4 = st.number_input("保底 D1/D4 亞洲價", value=25000, step=1000)

    st.subheader("🌍 外站雷達 (D1 / D4)")
    c_d1, c_d4 = st.columns(2)
    with c_d1:
        d1_hubs_raw = st.multiselect("📍 D1 起點庫", ALL_FORMATTED_CITIES, default=[f"HKG ({CI_ASIAN_HUBS['港澳']['HKG']})"])
        d1_date_range = st.date_input("📅 D1 日期", value=(date(2026, 6, 10), date(2026, 6, 11)))
    with c_d4:
        d4_hubs_raw = st.multiselect("📍 D4 終點庫", ALL_FORMATTED_CITIES, default=[f"HKG ({CI_ASIAN_HUBS['港澳']['HKG']})"])
        d4_date_range = st.date_input("📅 D4 日期", value=(date(2026, 6, 25), date(2026, 6, 26)))

    c_cab, c_adt = st.columns([1, 1])
    with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])

    if st.button("🚀 啟動不中斷接力獵殺", use_container_width=True):
        if len(d1_date_range) != 2 or len(d4_date_range) != 2: st.error("日期不完整"); st.stop()
        if not d1_hubs_raw or not d4_hubs_raw: st.error("需保留外站"); st.stop()
        
        d1_dates = [d1_date_range[0] + timedelta(days=i) for i in range((d1_date_range[1]-d1_date_range[0]).days + 1)]
        d4_dates = [d4_date_range[0] + timedelta(days=i) for i in range((d4_date_range[1]-d4_date_range[0]).days + 1)]
        d1_codes, d4_codes = [h.split(" ")[0] for h in d1_hubs_raw], [h.split(" ")[0] for h in d4_hubs_raw]
        
        # 建立任務清單
        tasks = []
        for h1_raw, h4_raw in product(d1_hubs_raw, d4_hubs_raw):
            h1_c, h4_c = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 <= d2_date and d4 >= d3_date: 
                    legs = [{"fromId": f"{h1_c}.AIRPORT", "toId": f"{d2_org}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, {"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_dst}.AIRPORT", "toId": f"{h4_c}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    tasks.append((legs, cabin_choice, strict_ci_toggle, f"{h1_raw} ➔ {h4_raw}", d1, d4, h1_c, h4_c))

        if not tasks: st.warning("無有效組合"); st.stop()
        
        # 寫入 Session State 準備接力
        st.session_state.task_list = tasks
        st.session_state.task_idx = 0
        st.session_state.valid_offers = []
        st.session_state.quota_dead = False
        st.session_state.core_price = fallback_d2d3
        st.session_state.base_cache = {f"{h1}_{h4}": fallback_d1d4 for h1, h4 in product(d1_codes, d4_codes)}
        st.session_state.engine_running = True
        
        with open(BLACKBOX_FILE, "w", encoding="utf-8") as file: pass # 清空舊紀錄
        st.rerun()

# ==========================================
# 3. 接力賽執行區 (Auto-Rerun Loop)
# ==========================================
if st.session_state.engine_running:
    total_tasks = len(st.session_state.task_list)
    curr_idx = st.session_state.task_idx
    BATCH_SIZE = 20 # 每次只跑 20 組，確保在 15 秒內完成，完美避開超時
    
    # 取出這一棒的任務
    current_batch = st.session_state.task_list[curr_idx : curr_idx + BATCH_SIZE]
    
    # 畫面更新進度條
    progress = min(curr_idx / total_tasks, 1.0)
    st.progress(progress, text=f"接力掃描中... {curr_idx} / {total_tasks} (已尋獲 {len(st.session_state.valid_offers)} 組)")
    
    live_feed = st.empty()
    
    # 執行這一棒
    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5]): t for t in current_batch}
        for f in as_completed(futures):
            task_meta = futures[f]
            try:
                res = f.result()
                if res["status"] == "quota_exceeded": 
                    st.session_state.quota_dead = True
                    break
                elif res["status"] == "success" and res.get("offer"):
                    offer = res["offer"]
                    offer["ref"] = st.session_state.core_price + st.session_state.base_cache[f"{task_meta[6]}_{task_meta[7]}"]
                    st.session_state.valid_offers.append(offer)
                    
                    diff = offer["ref"] - offer['total']
                    with open(BLACKBOX_FILE, "a", encoding="utf-8") as file:
                        file.write(json.dumps(offer, ensure_ascii=False) + "\n")
                    
                    if diff > 10000:
                        with live_feed.container():
                            st.markdown(f"<div class='live-hit'>🔔 <b>捕獲！</b> {offer['title']} | 總價: {offer['total']:,} | <span style='color:#00e676'>省下 {diff:,}</span></div>", unsafe_allow_html=True)
            except Exception: pass

    # 準備交棒
    if st.session_state.quota_dead or (curr_idx + BATCH_SIZE >= total_tasks):
        st.session_state.engine_running = False # 抵達終點，關閉引擎
        st.rerun()
    else:
        st.session_state.task_idx += BATCH_SIZE
        time.sleep(1) # 喘口氣避免 UI 閃爍過快
        st.rerun() # 🚀 自動觸發下一次執行！

# ==========================================
# 4. 戰果結算區
# ==========================================
if not st.session_state.engine_running and st.session_state.task_list:
    st.markdown("---")
    if st.session_state.quota_dead:
        st.error("🚨 API 額度耗盡，引擎已緊急煞車！以下為已搜得之結果：")
    else:
        st.success("🎉 獵殺引擎安全抵達終點！完美避開超時斷線。")
        
    results = st.session_state.valid_offers
    if results:
        results.sort(key=lambda x: x['total'])
        for r in results[:50]:
            diff = r["ref"] - r['total']
            badge_plain = f"🔥 狂省 {diff:,}" if diff > 50000 else f"✨ 省下 {diff:,}" if diff > 0 else f"⚠️ 虧損 {abs(diff):,}"
            badge_html = f"<span style='color:#00e676; font-weight:bold;'>🔥 狂省 {diff:,}</span>" if diff > 50000 else f"<span style='color:#b2ff59;'>✨ 省下 {diff:,}</span>" if diff > 0 else f"<span style='color:#ff5252;'>⚠️ 虧損 {abs(diff):,}</span>"
            
            with st.expander(f"💰 {r['total']:,} TWD | {badge_plain} | {r['title']} (D1:{r['d1']} / D4:{r['d4']})"):
                st.markdown(f"**💰 價差精算：** 傳統分開買約 `{r['ref']:,}` ➔ 隱藏聯程價 `{r['total']:,}` ( {badge_html} )", unsafe_allow_html=True)
                st.markdown("---")
                for j, leg in enumerate(r['legs'], 1): st.write(f"**航段 {j}** | {leg}")
    else:
        st.error("❌ 本次掃描未尋獲符合條件之特價聯程票。")
    
    if st.button("🧹 清除結果並重新設定"):
        st.session_state.task_list = []
        st.rerun()
