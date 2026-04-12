import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面隱藏與設定 ---
st.set_page_config(page_title="華航獵殺器 v11.0", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"

# 🛡️ 穩定型請求邏輯 (內建 2.2 秒強效冷卻)
def stable_request(url, method="GET", params=None, json=None):
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}
    for i in range(3):
        try:
            time.sleep(2.2) # 這是保護 API 的保險絲
            if method == "GET":
                res = requests.get(url, headers=headers, params=params, timeout=25)
            else:
                res = requests.post(url, headers=headers, json=json, timeout=35)
            
            if res.status_code == 200:
                data = res.json()
                if data and data.get('data'): return data
            elif res.status_code == 429:
                time.sleep(10)
        except:
            time.sleep(2)
    return None

# 🌟 引擎 A：日曆探路 (自動校正過去日期)
def scan_calendar(origin, dest, month_str, cabin, s_limit, e_limit):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": c_map[cabin], "market": "US"}
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    results = []
    # 🛡️ 關鍵：今天是 2026/04/12，絕不搜 4/1~4/11
    today = date.today() + timedelta(days=1) 
    if data and data.get('data'):
        days = data['data'].get('days', [])
        for d in days:
            try:
                d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                if d_obj >= today and s_limit <= d_obj <= e_limit:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d.get('price', 99999)})
            except: continue
    return results

# 🌟 引擎 B：真實聯程精算 (Married Segments 核心)
def fetch_bundle_price(h_in, d1, h_out, d4, d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": c_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_o, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_o, "toEntityId": d2_d, "departDate": d2_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_o, "toEntityId": d3_d, "departDate": d3_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_d, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if data and data.get('data'):
        itins = data['data'].get('itineraries', [])
        for itin in itins:
            if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in itin.get('legs', [])):
                legs_info = []
                for l in itin['legs']:
                    seg = l.get('segments', [{}])[0]
                    bc = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                    legs_info.append(f"CI {seg.get('flightNumber')} ({bc}) | {l.get('departure','').split('T')[1][:5]}")
                return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": legs_info, "d1": d1, "d4": d4}
    return None

# --- 主程式 ---
st.title("✈️ 華航外站聯程獵殺器 v11.0 (終極電改版)")

col1, col2 = st.columns(2)
with col1:
    d2_o = st.text_input("D2 出發 (TPE)", value="TPE")
    d2_d = st.text_input("D2 抵達 (PRG)", value="PRG")
    d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
with col2:
    d3_o = st.text_input("D3 出發 (FRA)", value="FRA")
    d3_d = st.text_input("D3 抵達 (TPE)", value="TPE")
    d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))

# 📅 日期邏輯自動對齊 (2026-04-12)
today = date.today()
d1_start = max(today + timedelta(days=1), (d2_dt - timedelta(days=65)).replace(day=1))
d1_end = d2_dt
d4_start = d3_dt
m4, y4 = (d3_dt.month + 2, d3_dt.year) if d3_dt.month <= 10 else (d3_dt.month - 10, d3_dt.year + 1)
_, last_d = calendar.monthrange(y4, m4)
d4_end = date(y4, m4, last_d)

st.success(f"📡 獵殺區間：D1({d1_start}~{d1_end}) | D4({d4_start}~{d4_end})")

cabin = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adult_count = st.number_input("大人人數", value=1, min_value=1)
selected_hubs = st.multiselect("📍 選擇掃描外站：", ["MNL", "BKK", "HKG", "KIX", "NRT", "ICN", "PUS", "SGN", "KUL", "FUK"], default=["MNL", "BKK", "KIX", "HKG"])

if st.button("🚀 啟動全自動獵殺", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 診斷報告", expanded=True)
    
    # 月份清單
    def get_ms(s, e):
        ms = []
        curr = s.replace(day=1)
        while curr <= e:
            ms.append(curr.strftime("%Y-%m"))
            curr = (curr + timedelta(days=32)).replace(day=1)
        return list(set(ms))

    d1_m, d4_m = get_ms(d1_start, d1_end), get_ms(d4_start, d4_end)
    d1_cands, d4_cands = [], []

    # 1. 第一階段：日曆探路
    for hub in selected_hubs:
        msg.info(f"⚡ 正在探測 {hub}...")
        for m in d1_m: d1_cands.extend(scan_calendar(hub, d2_o, m, cabin, d1_start, d1_end))
        for m in d4_m: d4_cands.extend(scan_calendar(d3_d, hub, m, cabin, d4_start, d4_end))
    
    # 🛡️ 補丁：如果雷達真的掃不到商務艙日曆，強制加入「理想斷點」日期測試
    if not d1_cands: d1_cands.append({"hub": "MNL", "day": d1_start, "price": 0})
    if not d4_cands: d4_cands.append({"hub": "MNL", "day": d4_end, "price": 0})

    msg.warning("🔥 正在進行『四段聯程』總價打包精算...")
    top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:3]
    top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:3]
    
    results = []
    # 為了成功率，不併發，一個一個穩穩查
    for d1, d4 in product(top_d1, top_d4):
        debug.write(f"正在測試：{d1['hub']}({d1['day']}) ➔ {d4['hub']}({d4['day']})")
        res = fetch_bundle_price(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adult_count)
        if res: results.append(res)
    
    msg.empty()
    if results:
        st.success("🎉 獵殺成功！以下為 Married Segment 真實打包價：")
        for r in sorted(results, key=lambda x: x['total'])[:10]:
            with st.expander(f"🏆 {r['title']} | {r['d1']} & {r['d4']} ➔ NT$ {r['total']:,}"):
                for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
    else:
        st.error("❌ 獵殺失敗。可能是華航在這些組合下不給低價位，或 API 被封鎖。")
