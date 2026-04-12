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
# 0. 介面與金鑰設定
# ==========================================
st.set_page_config(page_title="華航獵殺器 (動態精算版)", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

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
            is_valid = True
            legs_summary = []
            segments = offer.get('segments', [])
            for seg in segments:
                legs_list = seg.get('legs', [])
                first_leg = legs_list[0] if len(legs_list) > 0 else {}
                carrier = first_leg.get('flightInfo', {}).get('carrierInfo', {}).get('operatingCarrier', 'Unknown')
                flight_num = first_leg.get('flightInfo', {}).get('flightNumber', '')
                dep_code = seg.get('departureAirport', {}).get('code', '???')
                arr_code = seg.get('arrivalAirport', {}).get('code', '???')
                dep_time = seg.get('departureTime', '').replace('T', ' ')[:16]

                if strict_ci and carrier != "CI":
                    is_valid = False
                    break
                legs_summary.append(f"{carrier}{flight_num} | {dep_code} ➔ {arr_code} | {dep_time}")

            if is_valid and len(legs_summary) == len(segments): # 確保每段都有解析到
                price = offer.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                valid_results.append({"title": title, "total": price, "currency": "TWD", "legs": legs_summary, "d1": d1, "d4": d4})
        
        if valid_results:
            valid_results.sort(key=lambda x: x['total'])
            return valid_results[0]
    except Exception:
        pass
    return None

def fetch_booking_bundle(legs, cabin, strict_ci, title="", d1="", d4="", debug_mode=False):
    """通用型 API 請求函數 (可用於主掃描與前置偵察)"""
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    querystring = {"legs": json.dumps(legs), "cabinClass": c_map[cabin], "adults": "1", "currency_code": "TWD"}
    
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, params=querystring, timeout=45)
            if res.status_code == 200:
                raw_data = res.json()
                if title: # 這是主掃描任務
                    parsed_offer = parse_booking_response(raw_data, title, d1, d4, strict_ci)
                    return {"status": "success", "raw": raw_data if debug_mode else None, "offer": parsed_offer, "title": title}
                else: # 這是前置偵察基準價任務
                    offers = raw_data.get('data', {}).get('flightOffers', [])
                    if offers:
                        return {"status": "success", "price": offers[0].get('priceBreakdown', {}).get('total', {}).get('units', 0)}
                    return {"status": "error", "error": "查無基準票價"}
            elif res.status_code == 429:
                time.sleep((2 ** attempt) + random.uniform(0.5, 1.5))
                continue
            else:
                return {"status": "error", "error": f"HTTP {res.status_code}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
    return {"status": "error", "error": "HTTP 429 (重試達上限)"}

# ==========================================
# 2. UI 面板
# ==========================================
st.title("✈️ 華航外站獵殺器 (動態精算版)")
st.warning("⚠️ 系統將於背景自動查詢真實的分段機票行情，為您精算出最真實的價差！")

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

st.markdown("---")
st.markdown("#### 🎯 保底基準價設定 (Fallback)")
st.caption("萬一 Booking.com 當天沒有該航線的報價，系統會使用以下您設定的金額來計算價差。")
c_ref1, c_ref2 = st.columns(2)
with c_ref1: fallback_d2d3 = st.number_input("保底 D2/D3 核心航段票價", value=185000, step=1000)
with c_ref2: fallback_d1d4 = st.number_input("保底 D1/D4 外站航段票價", value=20000, step=1000)
st.markdown("---")

st.subheader("🌍 外站接駁掃描 (地毯式搜索)")
c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_regions = st.multiselect("🗂️ 批次全選 (D1)", ["全部", "東南亞", "東北亞", "港澳"], default=["東南亞"])
    d1_defaults = ALL_FORMATTED_CITIES if "全部" in d1_regions else [f"{c} ({n})" for r in d1_regions if r in CI_ASIAN_HUBS for c, n in CI_ASIAN_HUBS[r].items()]
    d1_hubs_raw = st.multiselect("📍 D1 出發外站", ALL_FORMATTED_CITIES, default=d1_defaults, key="d1_city")
    d1_date_range = st.date_input("📅 D1 日期區間", value=(date(2026, 6, 8), date(2026, 6, 11)), key="d1_date")

with c_d4:
    d4_regions = st.multiselect("🗂️ 批次全選 (D4)", ["全部", "東南亞", "東北亞", "港澳"], default=["東南亞"])
    d4_defaults = ALL_FORMATTED_CITIES if "全部" in d4_regions else [f"{c} ({n})" for r in d4_regions if r in CI_ASIAN_HUBS for c, n in CI_ASIAN_HUBS[r].items()]
    d4_hubs_raw = st.multiselect("📍 D4 抵達外站", ALL_FORMATTED_CITIES, default=d4_defaults, key="d4_city")
    d4_date_range = st.date_input("📅 D4 日期區間", value=(date(2026, 6, 25), date(2026, 6, 28)), key="d4_date")

c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

# ==========================================
# 3. 執行邏輯 
# ==========================================
if st.button("🚀 啟動 Booking.com 獵殺引擎", use_container_width=True):
    if len(d1_date_range) != 2 or len(d4_date_range) != 2: st.error("⚠️ 日期區間錯誤")
    elif not d1_hubs_raw or not d4_hubs_raw: st.error("⚠️ 至少保留一個外站")
    else:
        d1_dates = [d1_date_range[0] + timedelta(days=i) for i in range((d1_date_range[1]-d1_date_range[0]).days + 1)]
        d4_dates = [d4_date_range[0] + timedelta(days=i) for i in range((d4_date_range[1]-d4_date_range[0]).days + 1)]
        
        d1_codes = [h.split(" ")[0] for h in d1_hubs_raw]
        d4_codes = [h.split(" ")[0] for h in d4_hubs_raw]

        # ---------------------------------------------------------
        # 【階段一：前置偵察戰術 (抓取動態基準價)】
        # ---------------------------------------------------------
        msg_pre = st.info("🕵️‍♂️ 階段一：正在背景動態查詢分段機票行情，作為精算基準...")
        baseline_cache = {}
        
        # 1. 查 D2/D3 核心票價
        core_legs = [
            {"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
            {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}
        ]
        res_core = fetch_booking_bundle(core_legs, cabin_choice, strict_ci=False) # 基準價不鎖定航空，取最便宜
        core_baseline_price = res_core.get("price", fallback_d2d3) if res_core["status"] == "success" else fallback_d2d3
        
        # 2. 查各組 D1/D4 外站票價 (取區間第一天作為代表日)
        d1_rep = d1_dates[0].strftime("%Y-%m-%d")
        d4_rep = d4_dates[0].strftime("%Y-%m-%d")
        
        for h1, h4 in product(d1_codes, d4_codes):
            out_legs = [
                {"fromId": f"{h1}.AIRPORT", "toId": "TPE.AIRPORT", "date": d1_rep},
                {"fromId": "TPE.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4_rep}
            ]
            res_out = fetch_booking_bundle(out_legs, cabin_choice, strict_ci=False)
            baseline_cache[f"{h1}_{h4}"] = res_out.get("price", fallback_d1d4) if res_out["status"] == "success" else fallback_d1d4
            
        msg_pre.success(f"✅ 前置偵察完成！核心航線基準價約為 {core_baseline_price:,} TWD。準備進入深度掃描...")

        # ---------------------------------------------------------
        # 【階段二：正式大規模掃描】
        # ---------------------------------------------------------
        all_tasks = []
        for h1_raw, h4_raw in product(d1_hubs_raw, d4_hubs_raw):
            h1_code, h4_code = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 <= d2_date and d4 >= d3_date: 
                    # 準備四段票 legs
                    scan_legs = [
                        {"fromId": f"{h1_code}.AIRPORT", "toId": f"{d2_org}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                        {"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
                        {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")},
                        {"fromId": f"{d3_dst}.AIRPORT", "toId": f"{h4_code}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}
                    ]
                    title = f"{h1_raw} ➔ {h4_raw}"
                    all_tasks.append((scan_legs, cabin_choice, strict_ci_toggle, title, d1, d4, debug_mode, h1_code, h4_code))

        total_tasks = len(all_tasks)
        if total_tasks == 0: st.warning("⚠️ 無有效組合。")
        else:
            msg = st.warning(f"🔥 階段二：任務總數 {total_tasks} 組。防崩潰分批處理中...")
            pb = st.progress(0)
            valid_results, raw_debug_data, error_count, processed_count = [], [], 0, 0  
            BATCH_SIZE = 100

            for i in range(0, total_tasks, BATCH_SIZE):
                batch_tasks = all_tasks[i : i + BATCH_SIZE]
                with ThreadPoolExecutor(max_workers=5) as exe:
                    futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5], t[6]): t for t in batch_tasks}
                    for f in as_completed(futures):
                        task_meta = futures[f]
                        h1_code, h4_code = task_meta[7], task_meta[8]
                        processed_count += 1
                        try:
                            res = f.result()
                            if res["status"] == "success":
                                if debug_mode and len(raw_debug_data) < 3 and res.get("raw"): raw_debug_data.append(res["raw"])
                                if res["offer"]: 
                                    # 動態綁定對應的基準價
                                    res["offer"]["dynamic_ref_price"] = core_baseline_price + baseline_cache[f"{h1_code}_{h4_code}"]
                                    valid_results.append(res["offer"])
                            else: error_count += 1
                        except Exception: error_count += 1
                
                valid_results.sort(key=lambda x: x['total'])
                valid_results = valid_results[:100]
                gc.collect()
                pb.progress(processed_count / total_tasks, text=f"穩定掃描中: {processed_count}/{total_tasks} (尋獲: {len(valid_results)} 組)")

            pb.empty()
            msg.empty()

            if error_count > 0: st.toast(f"⚠️ {error_count} 組查詢異常。")

            if valid_results:
                st.success(f"🎉 獵殺完畢！為您展示精算後的完美聯程票：")
                for r in valid_results:
                    ref_price = r["dynamic_ref_price"]
                    diff = ref_price - r['total']
                    if diff > 0:
                        diff_badge, emoji = f"🔥 狂省 {diff:,} TWD", "🤑"
                    else:
                        diff_badge, emoji = f"虧損 {abs(diff):,} TWD", "🤡"

                    with st.expander(f"{emoji} 四段總價: {r['total']:,} TWD | {diff_badge} | {r['title']} (D1:{r['d1']} & D4:{r['d4']})"):
                        st.markdown(f"**💰 價差精算：** 傳統分開買約 `{ref_price:,}` ➔ 外站聯程買 `{r['total']:,}` (為您省下 **`{diff:,}`** 旅費)")
                        st.markdown("---")
                        for j, leg in enumerate(r['legs'], 1): st.write(f"{j}️⃣ {leg}")
            else:
                st.error("❌ 查無符合條件的票價。")
