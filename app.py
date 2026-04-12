import streamlit as st
import requests
import json
import time
import random
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. 介面與金鑰設定
# ==========================================
st.set_page_config(page_title="華航獵殺器 (Booking API 正式版)", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

try:
    raw_key = st.secrets["BOOKING_API_KEY"]
    BOOKING_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
except KeyError:
    st.error("🚨 系統找不到 Booking API 金鑰！請確認您已在 Streamlit 後台設定了 BOOKING_API_KEY。")
    st.stop()

# 🌍 華航亞洲站點資料庫
CI_ASIAN_HUBS = {
    "東南亞": {
        "BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", 
        "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", 
        "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", 
        "PNH": "金邊", "RGN": "仰光"
    },
    "東北亞": {
        "NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", 
        "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "TAK": "高松", 
        "HIJ": "廣島", "KOJ": "鹿兒島", "KMQ": "小松", "TOY": "富山",
        "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"
    },
    "港澳": {
        "HKG": "香港", "MFM": "澳門"
    }
}

ALL_FORMATTED_CITIES = []
for region, cities in CI_ASIAN_HUBS.items():
    for code, name in cities.items():
        ALL_FORMATTED_CITIES.append(f"{code} ({name})")

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
                
                flight_info = first_leg.get('flightInfo', {})
                carrier_info = flight_info.get('carrierInfo', {})
                
                carrier = carrier_info.get('operatingCarrier', 'Unknown')
                flight_num = flight_info.get('flightNumber', '')
                dep_code = seg.get('departureAirport', {}).get('code', '???')
                arr_code = seg.get('arrivalAirport', {}).get('code', '???')
                dep_time = seg.get('departureTime', '').replace('T', ' ')[:16]

                if strict_ci and carrier != "CI":
                    is_valid = False
                    break
                
                legs_summary.append(f"{carrier}{flight_num} | {dep_code} ➔ {arr_code} | {dep_time}")

            if is_valid and len(legs_summary) >= 4:
                price = offer.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                valid_results.append({
                    "title": title,
                    "total": price,
                    "currency": "TWD",
                    "legs": legs_summary,
                    "d1": d1,
                    "d4": d4
                })
        
        if valid_results:
            valid_results.sort(key=lambda x: x['total'])
            return valid_results[0]
            
    except Exception:
        pass
    return None

# 引擎更新：接收完整的 d2_org, d2_dst, d3_org, d3_dst
def fetch_booking_bundle(h_in_code, h_in_label, d1, h_out_code, h_out_label, d4, d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, strict_ci):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    
    headers = {
        "x-rapidapi-key": BOOKING_API_KEY,
        "x-rapidapi-host": "booking-com15.p.rapidapi.com"
    }
    
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    # 完美還原開口程邏輯
    legs = [
        {"fromId": f"{h_in_code}.AIRPORT", "toId": f"{d2_org}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
        {"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
        {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")},
        {"fromId": f"{d3_dst}.AIRPORT", "toId": f"{h_out_code}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}
    ]
    
    querystring = {
        "legs": json.dumps(legs),
        "cabinClass": c_map[cabin],
        "adults": "1",
        "currency_code": "TWD" 
    }
    
    bundle_title = f"{h_in_label} ➔ {h_out_label}"
    
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, params=querystring, timeout=45)
            if res.status_code == 200:
                raw_data = res.json()
                parsed_offer = parse_booking_response(raw_data, bundle_title, d1, d4, strict_ci)
                return {"status": "success", "raw": raw_data, "offer": parsed_offer, "title": bundle_title}
            elif res.status_code == 429:
                time.sleep((2 ** attempt) + random.uniform(0.5, 1.5))
                continue
            else:
                return {"status": "error", "error": f"HTTP {res.status_code}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
            
    return {"status": "error", "error": "HTTP 429 Limit Exceeded"}

# ==========================================
# 2. UI 面板
# ==========================================
st.title("✈️ 華航外站獵殺器 (Booking API 正式版)")
st.warning("⚠️ 此工具專門鎖定 CI 外站四段聯程票。Pro 方案已就緒，支援大範圍掃描。")

c_toggles = st.columns(2)
with c_toggles[0]:
    strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI) 航班", value=True)
with c_toggles[1]:
    debug_mode = st.checkbox("🛠️ 開啟 Debug 模式 (顯示原始 JSON)", value=False) 

# --- 核心行程 (完整還原 D2 / D3 開口程) ---
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

# --- 外站接駁 (D1 / D4) ---
st.subheader("🌍 外站接駁掃描 (地毯式搜索)")

c_d1, c_d4 = st.columns(2)
with c_d1:
    st.markdown("#### 🛫 D1 出發外站")
    d1_regions = st.multiselect("🗂️ 批次全選區域 (D1)", ["全部", "東南亞", "東北亞", "港澳"], default=["東南亞"])
    d1_defaults = ALL_FORMATTED_CITIES if "全部" in d1_regions else [f"{code} ({name})" for r in d1_regions if r in CI_ASIAN_HUBS for code, name in CI_ASIAN_HUBS[r].items()]
    d1_hubs_raw = st.multiselect("📍 細部微調站點 (D1)", ALL_FORMATTED_CITIES, default=d1_defaults, key=f"d1_city_{'-'.join(d1_regions)}")
    d1_date_range = st.date_input("📅 D1 日期區間", value=(date(2026, 6, 8), date(2026, 6, 11)), key="d1_date")

with c_d4:
    st.markdown("#### 🛬 D4 抵達外站")
    d4_regions = st.multiselect("🗂️ 批次全選區域 (D4)", ["全部", "東南亞", "東北亞", "港澳"], default=["東南亞"])
    d4_defaults = ALL_FORMATTED_CITIES if "全部" in d4_regions else [f"{code} ({name})" for r in d4_regions if r in CI_ASIAN_HUBS for code, name in CI_ASIAN_HUBS[r].items()]
    d4_hubs_raw = st.multiselect("📍 細部微調站點 (D4)", ALL_FORMATTED_CITIES, default=d4_defaults, key=f"d4_city_{'-'.join(d4_regions)}")
    d4_date_range = st.date_input("📅 D4 日期區間", value=(date(2026, 6, 25), date(2026, 6, 28)), key="d4_date")

c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

# ==========================================
# 3. 執行邏輯 (Pro 版併發加速)
# ==========================================
if st.button("🚀 啟動 Booking.com 獵殺引擎", use_container_width=True):
    if len(d1_date_range) != 2 or len(d4_date_range) != 2:
        st.error("⚠️ 請確保日期區間已選擇完整的起迄日。")
    elif not d1_hubs_raw or not d4_hubs_raw:
        st.error("⚠️ 請至少保留一個外站。")
    else:
        d1_dates = [d1_date_range[0] + timedelta(days=i) for i in range((d1_date_range[1]-d1_date_range[0]).days + 1)]
        d4_dates = [d4_date_range[0] + timedelta(days=i) for i in range((d4_date_range[1]-d4_date_range[0]).days + 1)]
        
        tasks = []
        for h1_raw, h4_raw in product(d1_hubs_raw, d4_hubs_raw):
            h1_code, h4_code = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 <= d2_date and d4 >= d3_date: 
                    tasks.append((h1_code, h1_raw, d1, h4_code, h4_raw, d4))

        if len(tasks) > 1500:
            st.error(f"🚨 組合數 ({len(tasks)} 組) 過多，請縮小範圍。")
        elif not tasks:
            st.warning("⚠️ 無有效組合，請檢查日期先後順序 (例如 D1 必須早於或等於 D2)。")
        else:
            msg = st.warning(f"🔥 正在對 {len(tasks)} 組日期與航點進行交叉精算...")
            pb = st.progress(0)
            valid_results = []
            raw_debug_data = []

            with ThreadPoolExecutor(max_workers=5) as exe:
                # 把 d2_org, d2_dst, d3_org, d3_dst 全部送進去！
                future_to_task = {
                    exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, strict_ci_toggle): t 
                    for t in tasks
                }
                
                for idx, f in enumerate(as_completed(future_to_task)):
                    pb.progress((idx + 1) / len(tasks), text=f"進度: {idx+1}/{len(tasks)}")
                    res = f.result()
                    
                    if res["status"] == "success":
                        if debug_mode: raw_debug_data.append(res["raw"])
                        if res["offer"]: valid_results.append(res["offer"])
                    else:
                        st.toast(f"⚠️ 某組查詢失敗: {res.get('error')}")

            pb.empty()
            msg.empty()

            if valid_results:
                st.success(f"🎉 成功找到 {len(valid_results)} 組符合條件的聯程票！")
                valid_results.sort(key=lambda x: x['total'])
                
                for r in valid_results[:30]:
                    with st.expander(f"💰 {r['total']:,} TWD | {r['title']} (D1:{r['d1']} & D4:{r['d4']})"):
                        for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
            else:
                st.error("❌ 查無符合條件之票價。可能原因：艙等無位、日期組合無報價或嚴格過濾導致。")

            if debug_mode and raw_debug_data:
                st.markdown("---")
                st.subheader("🛠️ Debug 原始 JSON")
                st.json(raw_debug_data[0])
