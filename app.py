import streamlit as st
import requests
import json
import time
import random
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. 介面與金鑰設定 (加入暴力消毒法)
# ==========================================
st.set_page_config(page_title="華航獵殺器 (Booking API 版)", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

try:
    # 暴力消毒：將字串轉為純 ASCII，強制濾除所有中文、全形空白與隱藏字元
    raw_key = st.secrets["BOOKING_API_KEY"]
    BOOKING_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
except KeyError:
    st.error("🚨 系統找不到 Booking API 金鑰！請確認您已在 Streamlit 後台的 Secrets 中設定了 BOOKING_API_KEY。")
    st.stop()

# 🌍 華航亞洲站點資料庫 (已剔除大陸)
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
# 1. 🌟 引擎：Booking.com 四段聯程精算
# ==========================================
def fetch_booking_bundle(h_in_code, h_in_label, d1, h_out_code, h_out_label, d4, d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults, strict_ci):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/getMinPriceMultiStops"
    
    headers = {
        "x-rapidapi-key": BOOKING_API_KEY,
        "x-rapidapi-host": "booking-com15.p.rapidapi.com"
    }
    
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    legs = [
        {"fromId": f"{h_in_code}.AIRPORT", "toId": "TPE.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
        {"fromId": "TPE.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
        {"fromId": f"{d3_o}.AIRPORT", "toId": "TPE.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
        {"fromId": "TPE.AIRPORT", "toId": f"{h_out_code}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}
    ]
    
    querystring = {
        "legs": json.dumps(legs),
        "cabinClass": c_map[cabin],
        "currency_code": "TWD" 
    }
    
    bundle_title = f"{h_in_label} ➔ {h_out_label}"
    
    # 🛡️ 加入防 429 退避重試機制 (最多重試 3 次)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            res = requests.get(url, headers=headers, params=querystring, timeout=45)
            
            if res.status_code == 200:
                raw_data = res.json()
                parsed_offer = parse_booking_response(raw_data, bundle_title, d1, d4, strict_ci)
                return {"status": "success", "raw": raw_data, "offer": parsed_offer, "title": bundle_title}
            
            elif res.status_code == 429:
                # 遇到 429 限制，暫停 1.5 ~ 4 秒後重試 (加入隨機亂數避免多線程同時甦醒)
                wait_time = (2 ** attempt) + random.uniform(0.5, 1.5)
                time.sleep(wait_time)
                continue
                
            else:
                return {"status": "error", "error": f"HTTP {res.status_code}"}
                
        except Exception as e:
            return {"status": "error", "error": str(e)}
            
    return {"status": "error", "error": "HTTP 429: 請求過於頻繁，已達重試上限。請減少組合數量。"}

def parse_booking_response(raw_data, title, d1, d4, strict_ci):
    """解析 Booking API 回傳的 JSON"""
    try:
        flights = raw_data.get('data', [])
        if isinstance(flights, dict):
            flights = flights.get('flightOffers', []) or flights.get('itineraries', [])
            
        valid_offers = []
        for f in flights:
            is_valid = True
            legs_info = []
            segments = f.get('segments', [])
            
            for seg in segments:
                carrier = seg.get("carrierCode", "Unknown")
                flight_num = seg.get("flightNumber", "")
                dep_air = seg.get("departureAirport", "")
                arr_air = seg.get("arrivalAirport", "")
                
                if strict_ci and carrier != "CI":
                    is_valid = False
                    
                legs_info.append(f"{carrier} {flight_num} | {dep_air} ➔ {arr_air}")
            
            if is_valid and legs_info:
                price = f.get('price', {}).get('total', 999999)
                valid_offers.append({
                    "title": title,
                    "total": float(price),
                    "currency": "TWD",
                    "legs": legs_info,
                    "d1": d1,
                    "d4": d4
                })
                
        if valid_offers:
            valid_offers.sort(key=lambda x: x['total'])
            return valid_offers[0] 
            
    except Exception:
        pass
    return None

# ==========================================
# 2. UI 面板
# ==========================================
st.title("✈️ 華航外站獵殺器 (Booking.com API 版)")

st.warning("⚠️ 目前已切換為 RapidAPI Booking.com 引擎 (防 429 裝甲版)。")
c_toggles = st.columns(2)
with c_toggles[0]:
    strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI) 航班", value=False)
with c_toggles[1]:
    debug_mode = st.checkbox("🛠️ 開啟 Debug 模式 (用於校準 JSON 格式)", value=True) 

# --- 核心行程 ---
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

# --- 外站接駁 ---
st.subheader("🌍 外站接駁與地毯式搜索 (D1 / D4)")
st.info("💡 快速選擇：點選上方區域後，下方城市會「自動全選」帶入該區所有站點，你可以再手動踢除不想去的城市。")

c_d1, c_d4 = st.columns(2)
with c_d1:
    st.markdown("#### 🛫 D1 出發外站")
    d1_regions = st.multiselect("🗂️ 批次全選區域 (D1)", ["全部", "東南亞", "東北亞", "港澳"], default=["東南亞"])
    
    d1_defaults = []
    if "全部" in d1_regions:
        d1_defaults = ALL_FORMATTED_CITIES
    else:
        for r in d1_regions:
            if r in CI_ASIAN_HUBS:
                for code, name in CI_ASIAN_HUBS[r].items():
                    d1_defaults.append(f"{code} ({name})")
                    
    d1_hubs_raw = st.multiselect(
        "📍 細部微調站點 (D1)", 
        ALL_FORMATTED_CITIES, 
        default=d1_defaults, 
        key=f"d1_city_{'-'.join(d1_regions)}" 
    )
    d1_date_range = st.date_input("📅 D1 日期區間", value=(date(2026, 6, 8), date(2026, 6, 10)), key="d1_date")

with c_d4:
    st.markdown("#### 🛬 D4 抵達外站")
    d4_regions = st.multiselect("🗂️ 批次全選區域 (D4)", ["全部", "東南亞", "東北亞", "港澳"], default=["東南亞"])
    
    d4_defaults = []
    if "全部" in d4_regions:
        d4_defaults = ALL_FORMATTED_CITIES
    else:
        for r in d4_regions:
            if r in CI_ASIAN_HUBS:
                for code, name in CI_ASIAN_HUBS[r].items():
                    d4_defaults.append(f"{code} ({name})")
                    
    d4_hubs_raw = st.multiselect(
        "📍 細部微調站點 (D4)", 
        ALL_FORMATTED_CITIES, 
        default=d4_defaults, 
        key=f"d4_city_{'-'.join(d4_regions)}"
    )
    d4_date_range = st.date_input("📅 D4 日期區間", value=(date(2026, 6, 26), date(2026, 6, 28)), key="d4_date")

c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

# ==========================================
# 3. 執行邏輯 
# ==========================================
if st.button("🚀 啟動 Booking.com 聯程區間掃描", use_container_width=True):
    if len(d1_date_range) != 2 or len(d4_date_range) != 2:
        st.error("⚠️ 請確保 D1 和 D4 都選擇了完整的「開始」與「結束」日期！(需在日曆上點擊兩次)")
    elif not d1_hubs_raw or not d4_hubs_raw:
        st.error("⚠️ 請在「細部微調站點」中至少保留一個外站！")
    else:
        msg = st.empty()
        
        def get_dates_from_range(date_tuple):
            start_date, end_date = date_tuple
            delta = end_date - start_date
            return [start_date + timedelta(days=i) for i in range(delta.days + 1)]
            
        d1_dates = get_dates_from_range(d1_date_range)
        d4_dates = get_dates_from_range(d4_date_range)
        
        tasks = []
        for h1_raw, h4_raw in product(d1_hubs_raw, d4_hubs_raw):
            h1_code = h1_raw.split(" ")[0]
            h4_code = h4_raw.split(" ")[0]
            
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 >= date.today() and d1 < d2_date and d4 > d3_date:
                    tasks.append((h1_code, h1_raw, d1, h4_code, h4_raw, d4))

        MAX_REQUESTS = 1500 
        
        if len(tasks) > MAX_REQUESTS:
            st.error(f"🚨 組合數 ({len(tasks)} 組) 超出單次掃描建議上限 ({MAX_REQUESTS})！\n為了避免觸發 API 的防護機制被阻擋，請稍微縮小日期或外站範圍。")
        elif len(tasks) == 0:
            st.warning("⚠️ 沒有產生任何有效的搜尋組合，請檢查日期邏輯 (例如 D1 必須早於 D2)。")
        else:
            msg.warning(f"🔥 裝甲版火力展示！正在向 Booking.com 發送 {len(tasks)} 組連線請求 (已啟動自動退避機制)，請稍候...")
            pb = st.progress(0)
            
            valid_results = []
            raw_debug_data = []

            # 🛡️ 引擎轉速調降：max_workers 從 5 降至 3，搭配上面的 retry 機制，讓掃描更穩
            with ThreadPoolExecutor(max_workers=3) as exe:
                future_to_task = {
                    exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count, strict_ci_toggle): t 
                    for t in tasks
                }
                
                for idx, f in enumerate(as_completed(future_to_task)):
                    pb.progress((idx + 1) / len(tasks), text=f"穩定掃描中 ({idx+1}/{len(tasks)})...")
                    res = f.result()
                    
                    if res["status"] == "success":
                        if debug_mode:
                            raw_debug_data.append(res["raw"])
                        
                        if res["offer"]:
                            valid_results.append(res["offer"])
                    else:
                        st.toast(f"⚠️ {res.get('error')}")
                            
            pb.empty()
            msg.empty()

            if valid_results:
                st.success("🎉 獵殺完畢！以下為即時回傳之報價：")
                valid_results.sort(key=lambda x: x['total'])
                
                for r in valid_results[:20]:
                    with st.expander(f"✅ {r['title']} | D1: {r['d1']} & D4: {r['d4']} ➔ 總價: {r['total']:,} {r['currency']}"):
                        for i, leg in enumerate(r['legs'], 1): 
                            st.write(f"{i}️⃣ {leg}")
            else:
                st.error("❌ 查無符合條件的結果。建議先取消「嚴格鎖定純華航」，並查看下方 Debug 資料。")

            if debug_mode and raw_debug_data:
                st.markdown("---")
                st.subheader("🛠️ Debug 模式：API 原始回傳資料")
                st.caption("以下為第一組回傳的原始 JSON 資料，請複製裡面的結構給我，我們來完成最後的解析邏輯！")
                st.json(raw_debug_data[0])
