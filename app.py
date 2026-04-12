import streamlit as st
import requests
import json
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面設定 ---
st.set_page_config(page_title="華航獵殺器 (Booking API 版)", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🔑 Booking.com RapidAPI 金鑰
try:
    BOOKING_API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 系統找不到 Booking API 金鑰！請確認您已在 Streamlit 後台的 Secrets 中設定了 BOOKING_API_KEY。")
    st.stop()

# 常用外站樞紐
ALL_HUBS = ["PUS", "ICN", "KUL", "BKK", "MNL", "HKG", "NRT", "FUK", "SGN", "CGK", "DPS", "SIN"]

# ==========================================
# 🌟 引擎：Booking.com 四段聯程精算
# ==========================================
def fetch_booking_bundle(h_in, d1, h_out, d4, d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults, strict_ci):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/getMinPriceMultiStops"
    
    headers = {
        "x-rapidapi-key": BOOKING_API_KEY,
        "x-rapidapi-host": "booking-com15.p.rapidapi.com"
    }
    
    # 艙等對應 (依據 Booking RapidAPI 規範)
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    # 依據截圖，組裝 legs 陣列，並自動加上 .AIRPORT 後綴
    legs = [
        {"fromId": f"{h_in}.AIRPORT", "toId": "TPE.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
        {"fromId": "TPE.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
        {"fromId": f"{d3_o}.AIRPORT", "toId": "TPE.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
        {"fromId": "TPE.AIRPORT", "toId": f"{h_out}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}
    ]
    
    querystring = {
        "legs": json.dumps(legs),
        "cabinClass": c_map[cabin],
        "currency_code": "TWD" 
        # 註：API 截圖中無特別提及 adult，如有需要可再補上 "adults": adults
    }
    
    bundle_title = f"{h_in} ➔ {h_out}"
    
    try:
        res = requests.get(url, headers=headers, params=querystring, timeout=45)
        if res.status_code == 200:
            raw_data = res.json()
            # 這裡呼叫解析函數 (目前為防禦性寫法)
            parsed_offer = parse_booking_response(raw_data, bundle_title, d1, d4, strict_ci)
            return {"status": "success", "raw": raw_data, "offer": parsed_offer, "title": bundle_title}
        else:
            return {"status": "error", "error": f"HTTP {res.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def parse_booking_response(raw_data, title, d1, d4, strict_ci):
    """
    解析 Booking API 的 JSON。
    【重要】這段邏輯需等您用 Debug 模式看到實際 JSON 後再行微調！
    """
    # 假設資料結構，若不符會回傳 None
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
                
                # 嚴格華航檢查
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
            return valid_offers[0] # 回傳該組合最便宜的
            
    except Exception:
        pass
    return None

# ==========================================
# UI 面板
# ==========================================
st.title("✈️ 華航外站獵殺器 (Booking.com API 版)")

st.warning("⚠️ 目前已切換為 RapidAPI Booking.com 引擎。")
c_toggles = st.columns(2)
with c_toggles[0]:
    strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI) 航班", value=False)
with c_toggles[1]:
    debug_mode = st.checkbox("🛠️ 開啟 Debug 模式 (用於校準 JSON 格式)", value=False)

# 1. 核心行程
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

# 2. 外站接駁
st.subheader("🌍 外站接駁與精確打擊 (D1 / D4)")
st.info("💡 系統會自動幫您掃描 D1/D4 基準日的前後 ±1 天 (若選單一外站共 9 種組合)。")
c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_hubs = st.multiselect("D1 出發城市", ALL_HUBS, default=["KUL"])
    d1_base_date = st.date_input("D1 基準日", value=date(2026, 6, 9))
with c_d4:
    d4_hubs = st.multiselect("D4 抵達城市", ALL_HUBS, default=["KUL"])
    d4_base_date = st.date_input("D4 基準日", value=date(2026, 6, 27))

c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

if st.button("🚀 啟動 Booking.com 聯程精算", use_container_width=True):
    if not d1_hubs or not d4_hubs:
        st.error("請至少選擇一個外站！")
    else:
        msg = st.empty()
        
        # 產生 ±1 天的日期陣列
        def get_date_range(base_d):
            return [base_d + timedelta(days=i) for i in range(-1, 2)]
            
        d1_dates = get_date_range(d1_base_date)
        d4_dates = get_date_range(d4_base_date)
        
        # 準備所有組合任務
        tasks = []
        for h1, h4 in product(d1_hubs, d4_hubs):
            for d1, d4 in product(d1_dates, d4_dates):
                # 確保日期不回溯且邏輯正確
                if d1 >= date.today() and d1 < d2_date and d4 > d3_date:
                    tasks.append((h1, d1, h4, d4))

        msg.warning(f"🔥 正在向 Booking.com 發送 {len(tasks)} 組即時定價請求，請稍候...")
        pb = st.progress(0)
        
        valid_results = []
        raw_debug_data = []

        # 並行發送請求
        with ThreadPoolExecutor(max_workers=5) as exe:
            future_to_task = {
                exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count, strict_ci_toggle): t 
                for t in tasks
            }
            
            for idx, f in enumerate(as_completed(future_to_task)):
                pb.progress((idx + 1) / len(tasks), text=f"精算中 ({idx+1}/{len(tasks)})...")
                res = f.result()
                
                if res["status"] == "success":
                    if debug_mode:
                        raw_debug_data.append(res["raw"])
                    
                    if res["offer"]:
                        valid_results.append(res["offer"])
                        
        pb.empty()
        msg.empty()

        if valid_results:
            st.success("🎉 獵殺完畢！以下為 Booking.com 即時回傳之真實打包價：")
            valid_results.sort(key=lambda x: x['total'])
            
            for r in valid_results[:10]:
                with st.expander(f"✅ {r['title']} | D1: {r['d1']} & D4: {r['d4']} ➔ 總價: {r['total']:,} {r['currency']}"):
                    for i, leg in enumerate(r['legs'], 1): 
                        st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 查無符合條件的結果。可能原因：\n1. 該日期組合無機位。\n2. 「嚴格純 CI」過濾掉了聯營航班。\n3. JSON 解析格式有誤（建議開啟 Debug 模式檢查）。")

        # 顯示 Debug 資料
        if debug_mode and raw_debug_data:
            st.markdown("---")
            st.subheader("🛠️ Debug 模式：API 原始回傳資料")
            st.caption("請檢查下方 JSON，找出 `Carrier` 和 `Price` 的確切欄位名稱，以便我們修改 `parse_booking_response` 函數。")
            st.json(raw_debug_data[0])
