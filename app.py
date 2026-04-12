import streamlit as st
import requests
import json
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. 介面與金鑰設定
# ==========================================
st.set_page_config(page_title="華航獵殺器 (Booking API 版)", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

try:
    BOOKING_API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 系統找不到 Booking API 金鑰！請確認您已在 Streamlit 後台的 Secrets 中設定了 BOOKING_API_KEY。")
    st.stop()

# 🌍 升級版：加上區域與中文名稱，大幅提升選取直覺度
ALL_HUBS = [
    "【東南亞】 KUL (吉隆坡)",
    "【東南亞】 BKK (曼谷)",
    "【東南亞】 SIN (新加坡)",
    "【東南亞】 SGN (胡志明市)",
    "【東南亞】 CGK (雅加達)",
    "【東南亞】 DPS (峇里島)",
    "【東南亞】 MNL (馬尼拉)",
    "【東北亞】 ICN (首爾)",
    "【東北亞】 PUS (釜山)",
    "【東北亞】 NRT (東京成田)",
    "【東北亞】 FUK (福岡)",
    "【港澳】 HKG (香港)"
]

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
    
    # 這裡送給 API 的會是乾淨的三碼 (如 KUL.AIRPORT)
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
    
    # 顯示給使用者看的會是完整的中文標籤
    bundle_title = f"{h_in_label} ➔ {h_out_label}"
    
    try:
        res = requests.get(url, headers=headers, params=querystring, timeout=45)
        if res.status_code == 200:
            raw_data = res.json()
            parsed_offer = parse_booking_response(raw_data, bundle_title, d1, d4, strict_ci)
            return {"status": "success", "raw": raw_data, "offer": parsed_offer, "title": bundle_title}
        else:
            return {"status": "error", "error": f"HTTP {res.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def parse_booking_response(raw_data, title, d1, d4, strict_ci):
    """解析 Booking API 回傳的 JSON (待用 Debug 模式校準)"""
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

st.warning("⚠️ 目前已切換為 RapidAPI Booking.com 引擎 (Pro 方案解鎖版)。")
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

# --- 外站接駁 (區間版) ---
st.subheader("🌍 外站接駁與地毯式搜索 (D1 / D4)")
st.info("💡 支援區間選擇！下拉選單已按區域分類，支援跨區多選大亂鬥。")

c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_hubs_raw = st.multiselect("D1 出發城市", ALL_HUBS, default=["【東南亞】 KUL (吉隆坡)"])
    d1_date_range = st.date_input("D1 日期區間", value=(date(2026, 6, 8), date(2026, 6, 10)))

with c_d4:
    d4_hubs_raw = st.multiselect("D4 抵達城市", ALL_HUBS, default=["【東南亞】 KUL (吉隆坡)"])
    d4_date_range = st.date_input("D4 日期區間", value=(date(2026, 6, 26), date(2026, 6, 28)))

c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

# ==========================================
# 3. 執行邏輯 (Pro 方案火力全開版)
# ==========================================
if st.button("🚀 啟動 Booking.com 聯程區間掃描", use_container_width=True):
    if len(d1_date_range) != 2 or len(d4_date_range) != 2:
        st.error("⚠️ 請確保 D1 和 D4 都選擇了完整的「開始」與「結束」日期！(需在日曆上點擊兩次)")
    elif not d1_hubs_raw or not d4_hubs_raw:
        st.error("⚠️ 請至少選擇一個外站！")
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
            # 從 "【東南亞】 KUL (吉隆坡)" 中萃取出 "KUL" 以供 API 使用
            h1_code = h1_raw.split(" ")[1]
            h4_code = h4_raw.split(" ")[1]
            
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 >= date.today() and d1 < d2_date and d4 > d3_date:
                    tasks.append((h1_code, h1_raw, d1, h4_code, h4_raw, d4))

        # 【Pro 方案專屬】解開單次掃描上限至 1500 組
        MAX_REQUESTS = 1500 
        
        if len(tasks) > MAX_REQUESTS:
            st.error(f"🚨 組合數 ({len(tasks)} 組) 超出單次掃描建議上限 ({MAX_REQUESTS})！\n為了避免觸發 API 的防護機制被阻擋，請稍微縮小日期或外站範圍。")
        elif len(tasks) == 0:
            st.warning("⚠️ 沒有產生任何有效的搜尋組合，請檢查日期邏輯 (例如 D1 必須早於 D2)。")
        else:
            msg.warning(f"🔥 Pro 方案火力展示！正在向 Booking.com 發送 {len(tasks)} 組連線請求，請稍候...")
            pb = st.progress(0)
            
            valid_results = []
            raw_debug_data = []

            # 引擎轉速提升：max_workers 提高到 5
            with ThreadPoolExecutor(max_workers=5) as exe:
                # 注意這裡傳遞參數的變化，把 code 和 label 都傳進去
                future_to_task = {
                    exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count, strict_ci_toggle): t 
                    for t in tasks
                }
                
                for idx, f in enumerate(as_completed(future_to_task)):
                    pb.progress((idx + 1) / len(tasks), text=f"高速掃描中 ({idx+1}/{len(tasks)})...")
                    res = f.result()
                    
                    if res["status"] == "success":
                        if debug_mode:
                            raw_debug_data.append(res["raw"])
                        
                        if res["offer"]:
                            valid_results.append(res["offer"])
                    else:
                        st.toast(f"⚠️ 某組請求發生錯誤: {res.get('error')}")
                            
            pb.empty()
            msg.empty()

            if valid_results:
                st.success("🎉 獵殺完畢！以下為即時回傳之報價：")
                valid_results.sort(key=lambda x: x['total'])
                
                for r in valid_results[:20]:
                    # 這裡的 r['title'] 現在會漂亮地顯示如: 【東南亞】 KUL (吉隆坡) ➔ 【東北亞】 NRT (東京成田)
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
