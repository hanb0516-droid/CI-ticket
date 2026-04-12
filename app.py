import streamlit as st
import requests
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# --- 介面設定 ---
st.set_page_config(page_title="華航獵殺器 (Duffel GDS 直連版)", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🔑 Duffel API 金鑰 (安全隱藏版：透過 Streamlit Secrets 讀取)
try:
    DUFFEL_TOKEN = st.secrets["DUFFEL_TOKEN"]
except KeyError:
    st.error("🚨 系統找不到 Duffel 金鑰！請確認您已在 Streamlit 後台的 Secrets 中設定了 DUFFEL_TOKEN。")
    st.stop()

BASE_URL = "https://api.duffel.com/air/offer_requests"

ALL_HUBS = ["PUS", "ICN", "KUL", "BKK", "MNL", "HKG", "NRT", "FUK", "SGN", "CGK", "DPS", "SIN"]

# 🌟 引擎：Duffel 四段聯程精算
def fetch_duffel_bundle(h_in, d1, h_out, d4, d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults, strict_ci):
    headers = {
        "Authorization": f"Bearer {DUFFEL_TOKEN}",
        "Duffel-Version": "v1",
        "Content-Type": "application/json"
    }
    
    # 艙等對應
    c_map = {"商務艙": "business", "豪經艙": "premium_economy", "經濟艙": "economy"}
    passengers = [{"type": "adult"} for _ in range(int(adults))]
    
    # Duffel 標準 payload (直接發送四段 Multi-city)
    payload = {
        "data": {
            "slices": [
                {"origin": h_in, "destination": "TPE", "departure_date": d1.strftime("%Y-%m-%d")},
                {"origin": "TPE", "destination": d2_d, "departure_date": d2_dt.strftime("%Y-%m-%d")},
                {"origin": d3_o, "destination": "TPE", "departure_date": d3_dt.strftime("%Y-%m-%d")},
                {"origin": "TPE", "destination": h_out, "departure_date": d4.strftime("%Y-%m-%d")}
            ],
            "passengers": passengers,
            "cabin_class": c_map[cabin],
            "return_offers": True # 讓系統直接回傳報價
        }
    }
    
    try:
        # GDS 系統算票需要一點時間，timeout 設長一點
        res = requests.post(BASE_URL, headers=headers, json=payload, timeout=40)
        
        if res.status_code == 201:
            data = res.json()
            offers = data.get("data", {}).get("offers", [])
            
            valid_offers = []
            for o in offers:
                is_valid = True
                legs_info = []
                
                # 解析每一段航班
                for slice_data in o.get("slices", []):
                    for seg in slice_data.get("segments", []):
                        carrier = seg.get("operating_carrier", {}).get("iata_code", "Unknown")
                        flight_num = seg.get("operating_carrier_flight_number", "")
                        dep_air = seg.get("origin", {}).get("iata_code", "")
                        arr_air = seg.get("destination", {}).get("iata_code", "")
                        dep_time = seg.get("departing_at", "")[:16].replace("T", " ")
                        
                        # 如果開啟嚴格華航模式，且航空公司不是 CI，就淘汰
                        if strict_ci and carrier != "CI":
                            is_valid = False
                            
                        legs_info.append(f"{carrier} {flight_num} | {dep_air} ➔ {arr_air} | {dep_time}")
                
                if is_valid:
                    valid_offers.append({
                        "title": f"{h_in} ➔ {h_out}",
                        "total": float(o.get("total_amount")),
                        "currency": o.get("total_currency"),
                        "legs": legs_info,
                        "d1": d1,
                        "d4": d4
                    })
            
            # 回傳該日期組合中最便宜的一個
            if valid_offers:
                valid_offers.sort(key=lambda x: x['total'])
                return valid_offers[0]
                
    except Exception as e:
        return None
        
    return None

# --- UI 面板 ---
st.title("✈️ 華航外站獵殺器 (GDS 直連版)")

st.warning("⚠️ 目前使用 Duffel Test Token。測試環境下系統會回傳虛擬航班 (Duffel Airways)。請開啟下方「解除華航鎖定」開關以查看測試結果。")
strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI) 航班 (轉為 Live 帳號後請務必勾選)", value=False)

# 1. 核心行程
st.subheader("📌 核心行程 (D2 / D3)")
c_d2, c_d3 = st.columns(2)
with c_d2:
    d2_org = st.text_input("D2 出發", value="TPE")
    d2_dst = st.text_input("D2 抵達", value="PRG")
    d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
with c_d3:
    d3_org = st.text_input("D3 出發", value="FRA")
    d3_dst = st.text_input("D3 抵達", value="TPE")
    d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

# 2. 外站接駁
st.subheader("🌍 外站接駁與精確打擊 (D1 / D4)")
st.info("💡 GDS 系統為即時運算，請指定 D1/D4 基準日，系統會自動幫您掃描該日期的前後 ±1 天 (共 9 種組合)。")
c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_hubs = st.multiselect("D1 出發城市", ALL_HUBS, default=["PUS"])
    d1_base_date = st.date_input("D1 基準日", value=date(2026, 4, 20))
with c_d4:
    d4_hubs = st.multiselect("D4 抵達城市", ALL_HUBS, default=["PUS"])
    d4_base_date = st.date_input("D4 基準日", value=date(2026, 8, 10))

c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

if st.button("🚀 啟動 GDS 聯程精算", use_container_width=True):
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

        msg.warning(f"🔥 正在向 GDS 系統發送 {len(tasks)} 組即時定價請求，請稍候...")
        pb = st.progress(0)
        results = []

        # 並行發送請求 (Duffel 承受力極強)
        with ThreadPoolExecutor(max_workers=5) as exe:
            future_to_task = {exe.submit(fetch_duffel_bundle, t[0], t[1], t[2], t[3], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count, strict_ci_toggle): t for t in tasks}
            
            for idx, f in enumerate(as_completed(future_to_task)):
                pb.progress((idx + 1) / len(tasks), text=f"精算中 ({idx+1}/{len(tasks)})...")
                res = f.result()
                if res:
                    results.append(res)
                    
        pb.empty()
        msg.empty()

        if results:
            st.success("🎉 獵殺完畢！以下為 GDS 即時回傳之真實打包價：")
            # 依總價排序
            results.sort(key=lambda x: x['total'])
            
            for r in results[:10]:
                with st.expander(f"✅ {r['title']} | D1: {r['d1']} & D4: {r['d4']} ➔ 總價: {r['total']:,} {r['currency']}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 查無結果。可能是 GDS 該日期無可用機位，或測試環境未提供該路線之虛擬航班。")
