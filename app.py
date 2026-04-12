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
        background-image: linear-gradient(rgba(15, 20, 35, 0.2), rgba(15, 20, 35, 0.5)), 
        url("https://images.unsplash.com/photo-1436491865332-7a61a109cc05?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important;
        background-position: center !important;
        background-attachment: fixed !important;
    }
    
    [data-testid="stExpander"] {
        background-color: rgba(20, 35, 55, 0.6) !important;
        backdrop-filter: blur(15px) !important;
        border: 1px solid rgba(255, 255, 255, 0.25) !important;
        border-radius: 12px !important;
        box-shadow: 0 10px 40px 0 rgba(0, 0, 0, 0.5) !important;
        margin-bottom: 15px;
    }
    
    .custom-title {
        background: linear-gradient(45deg, #ffffff, #4da8da);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 900;
        font-size: 3rem;
        margin-bottom: -5px;
        text-shadow: 0px 4px 10px rgba(0,0,0,0.5);
    }

    .live-hit {
        padding: 12px; border-left: 6px solid #00e676; 
        background: rgba(0, 230, 118, 0.15); 
        margin-bottom: 12px; border-radius: 8px;
        color: #ffffff; font-weight: 600;
        backdrop-filter: blur(5px);
    }
</style>
""", unsafe_allow_html=True)

try:
    raw_key = st.secrets["BOOKING_API_KEY"]
    BOOKING_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
except KeyError:
    st.error("🚨 找不到 API 金鑰，請確認 Streamlit Secrets 設定。")
    st.stop()

CI_ASIAN_HUBS = {
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "TAK": "高松", "HIJ": "廣島", "KOJ": "鹿兒島", "KMQ": "小松", "TOY": "富山", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "港澳": {"HKG": "香港", "MFM": "澳門"}
}
ALL_FORMATTED_CITIES = [f"{code} ({name})" for region, cities in CI_ASIAN_HUBS.items() for code, name in cities.items()]

# ==========================================
# 1. 🌟 核心引擎
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
                
                # 💣 排雷修復：同時抓取實際執飛與銷售航空，避免代碼共享航班被誤殺
                c_info = first_leg.get('flightInfo', {}).get('carrierInfo', {})
                carrier = c_info.get('operatingCarrier') or c_info.get('marketingCarrier', '??')
                f_num = first_leg.get('flightInfo', {}).get('flightNumber', '')
                
                dep_code = seg.get('departureAirport', {}).get('code', '???')
                arr_code = seg.get('arrivalAirport', {}).get('code', '???')
                dep_time = seg.get('departureTime', '').replace('T', ' ')[:16]

                if strict_ci and carrier != "CI":
                    is_valid = False; break
                legs_summary.append(f"**{carrier}{f_num}** | {dep_code} ➔ {arr_code} | {dep_time}")

            if is_valid and len(legs_summary) == 4: 
                price = offer.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                valid_results.append({"title": title, "total": price, "legs": legs_summary, "d1": d1, "d4": d4})
        
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
                    return {"status": "success", "price": offers[0].get('priceBreakdown', {}).get('total', {}).get('units', 0)} if offers else {"status": "error", "error": "查無票價"}
            elif res.status_code in [403, 429]:
                if "quota" in res.text.lower(): return {"status": "quota_exceeded"}
                time.sleep(2); continue
            else: return {"status": "error", "error": f"HTTP {res.status_code}"}
        except Exception as e: return {"status": "error", "error": str(e)}
    return {"status": "error", "error": "逾時"}

# ==========================================
# 2. UI 面板
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)
st.markdown('<p style="color:#cbd5e1; font-weight:600; margin-bottom:25px;">中華航空 (CI) 外站四段聯程・動態獵殺儀表板</p>', unsafe_allow_html=True)

c_toggles = st.columns(2)
with c_toggles[0]: strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI) 航班", value=True)
with c_toggles[1]: debug_mode = st.checkbox("🛠️ 開啟 Debug 模式", value=False) 

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
    d1_regions = st.multiselect("🗂️ 區域 (D1)", ["全部", "東南亞", "東北亞", "港澳"], default=["港澳", "東南亞"])
    d1_defaults = [f"{c} ({n})" for r in d1_regions if r in CI_ASIAN_HUBS for c, n in CI_ASIAN_HUBS[r].items()]
    d1_hubs_raw = st.multiselect("📍 D1 起點庫", ALL_FORMATTED_CITIES, default=d1_defaults[:5], key="d1_city")
    d1_date_range = st.date_input("📅 D1 日期", value=(date(2026, 6, 10), date(2026, 6, 11)))

with c_d4:
    d4_regions = st.multiselect("🗂️ 區域 (D4)", ["全部", "東南亞", "東北亞", "港澳"], default=["港澳", "東南亞"])
    d4_defaults = [f"{c} ({n})" for r in d4_regions if r in CI_ASIAN_HUBS for c, n in CI_ASIAN_HUBS[r].items()]
    d4_hubs_raw = st.multiselect("📍 D4 終點庫", ALL_FORMATTED_CITIES, default=d4_defaults[:5], key="d4_city")
    d4_date_range = st.date_input("📅 D4 日期", value=(date(2026, 6, 25), date(2026, 6, 26)))

c_cab, c_adt = st.columns([1, 1])
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

# ==========================================
# 3. 執行邏輯 
# ==========================================
if st.button("🚀 啟動動態精算獵殺", use_container_width=True):
    # 💣 排雷修復：防呆日期檢驗，避免陷入無效的死胡同搜尋
    if len(d1_date_range) != 2 or len(d4_date_range) != 2: 
        st.error("⚠️ 日期區間未填寫完整。"); st.stop()
    if d2_date >= d3_date:
        st.error("⚠️ 邏輯錯誤：D2 去程日期必須早於 D3 回程日期！"); st.stop()
    if d1_date_range[0] > d2_date or d4_date_range[1] < d3_date:
        st.error("⚠️ 邏輯錯誤：D1 出發日不能晚於 D2；D4 抵達日不能早於 D3！"); st.stop()
    if not d1_hubs_raw or not d4_hubs_raw: 
        st.error("⚠️ 請至少保留一個 D1 與 D4 的外站城市。"); st.stop()
    
    d1_dates = [d1_date_range[0] + timedelta(days=i) for i in range((d1_date_range[1]-d1_date_range[0]).days + 1)]
    d4_dates = [d4_date_range[0] + timedelta(days=i) for i in range((d4_date_range[1]-d4_date_range[0]).days + 1)]
    d1_codes, d4_codes = [h.split(" ")[0] for h in d1_hubs_raw], [h.split(" ")[0] for h in d4_hubs_raw]
    
    baseline_cache = {}
    core_legs = [{"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}]
    res_core = fetch_booking_bundle(core_legs, cabin_choice, strict_ci=False)
    core_baseline_price = res_core.get("price", fallback_d2d3) if res_core["status"] == "success" else fallback_d2d3
    
    out_combinations = list(product(d1_codes, d4_codes))
    for h1, h4 in out_combinations: baseline_cache[f"{h1}_{h4}"] = fallback_d1d4

    all_tasks = []
    for h1_raw, h4_raw in product(d1_hubs_raw, d4_hubs_raw):
        h1_c, h4_c = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
        for d1, d4 in product(d1_dates, d4_dates):
            if d1 <= d2_date and d4 >= d3_date: 
                legs = [{"fromId": f"{h1_c}.AIRPORT", "toId": f"{d2_org}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, {"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_dst}.AIRPORT", "toId": f"{h4_c}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                all_tasks.append((legs, cabin_choice, strict_ci_toggle, f"{h1_raw} ➔ {h4_raw}", d1, d4, debug_mode, h1_c, h4_c))

    total = len(all_tasks)
    if total == 0: 
        st.warning("⚠️ 根據您設定的日期，無法產生任何合理的四段票組合。")
        st.stop()

    msg = st.warning(f"🔥 任務總數 {total} 組。啟動實時戰報機制，請安心掛機...")
    pb = st.progress(0)
    live_feed = st.empty()
    valid_results, processed, quota_dead = [], 0, False

    for i in range(0, total, 100):
        if quota_dead: break
        batch = all_tasks[i : i + 100]
        with ThreadPoolExecutor(max_workers=5) as exe:
            futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5], t[6]): t for t in batch}
            for f in as_completed(futures):
                task_meta = futures[f]
                processed += 1
                try:
                    res = f.result()
                    if res["status"] == "quota_exceeded": quota_dead = True
                    elif res["status"] == "success" and res["offer"]:
                        res["offer"]["ref"] = core_baseline_price + baseline_cache[f"{task_meta[7]}_{task_meta[8]}"]
                        valid_results.append(res["offer"])
                        diff = res["offer"]["ref"] - res["offer"]['total']
                        if diff > 10000:
                            with live_feed.container():
                                st.markdown(f"<div class='live-hit'>🔔 <b>捕獲高價值票！</b> {res['offer']['title']} | 總價: {res['offer']['total']:,} | <span style='color:#00e676'>現省 {diff:,}</span></div>", unsafe_allow_html=True)
                except Exception: pass
                if processed % 5 == 0: pb.progress(processed / total, text=f"掃描中: {processed}/{total}")
        gc.collect()

    pb.empty(); msg.empty()
    if quota_dead: st.error("🚨 API 額度耗盡，已為您顯示斷線前搜得之結果：")

    if valid_results:
        valid_results.sort(key=lambda x: x['total'])
        st.success(f"🎉 獵殺完成！最佳組合已列於下方：")
        for r in valid_results[:50]:
            diff = r["ref"] - r['total']
            badge = f"<span style='color:#00e676; font-weight:bold;'>🔥 狂省 {diff:,}</span>" if diff > 50000 else f"<span style='color:#b2ff59;'>✨ 省下 {diff:,}</span>" if diff > 0 else f"<span style='color:#ff5252;'>⚠️ 虧損 {abs(diff):,}</span>"
            with st.expander(f"💰 {r['total']:,} TWD | {badge} | {r['title']} (D1:{r['d1']} / D4:{r['d4']})"):
                st.markdown(f"**💰 價差精算：** 傳統分開買約 `{r['ref']:,}` ➔ 隱藏聯程價 `{r['total']:,}`")
                st.markdown("---")
                for j, leg in enumerate(r['legs'], 1): st.write(f"**航段 {j}** | {leg}")
    else: 
        # 💣 排雷修復：找不到票時給予明確的除錯建議
        st.error("❌ 本次掃描未尋獲符合條件之特價聯程票。")
        st.info("💡 **駭客建議：**\n1. 嘗試擴大 D1 與 D4 的日期區間 (放寬到 48 小時內)\n2. 關閉「嚴格鎖定純華航」，看看是否有國泰或新航的破盤價\n3. 該檔期可能是該外站的連假旺季，請更換其他區域盲測。")
