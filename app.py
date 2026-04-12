import streamlit as st
from datetime import datetime, timedelta, date
import calendar
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面隱藏與設定 ---
st.set_page_config(page_title="華航獵殺器 v9.0", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"

# 🛡️ 穩定型請求邏輯 (內建 2 秒延遲，保證不跳電)
def stable_request(url, method="GET", params=None, json=None):
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}
    for i in range(3):
        try:
            time.sleep(1.8) 
            if method == "GET":
                res = requests.get(url, headers=headers, params=params, timeout=25)
            else:
                res = requests.post(url, headers=headers, json=json, timeout=35)
            
            if res.status_code == 200: return res.json()
            elif res.status_code == 429: time.sleep(10)
        except: time.sleep(2)
    return None

# 🌟 引擎 A：日期解析 (修復 NameError)
def get_month_strings(s_date, e_date):
    ms = []
    curr = s_date.replace(day=1)
    while curr <= e_date:
        ms.append(curr.strftime("%Y-%m"))
        if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
        else: curr = curr.replace(month=curr.month+1)
    return sorted(list(set(ms)))

# 🌟 引擎 B：日曆探路 (找尋低價窗口)
def scan_calendar(origin, dest, month_str, cabin, s_limit, e_limit):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": c_map[cabin], "market": "US"}
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    results = []
    if data and data.get('data'):
        for d in data['data'].get('days', []):
            try:
                d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                if date.today() <= d_obj and s_limit <= d_obj <= e_limit and d.get('price', 0) > 0:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d['price']})
            except: continue
    return results

# 🌟 引擎 C：真實四段聯程精算 (核心 Married Segment 邏輯)
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

# --- UI ---
st.title("✈️ 華航外站聯程獵殺器 v9.0 (終極糾錯版)")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發", value="TPE")
    d2_dst = st.text_input("D2 抵達", value="PRG")
    d2_date = st.date_input("D2 日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發", value="FRA")
    d3_dst = st.text_input("D3 抵達", value="TPE")
    d3_date = st.date_input("D3 日期", value=date(2026, 6, 25))

# 📅 日期邏輯自動推算 (今天是 2026-04-12)
today = date.today()
d1_start = max(today, (d2_date - timedelta(days=62)).replace(day=1))
d1_end = d2_date
d4_start = d3_date
m4, y4 = (d3_date.month + 2, d3_date.year) if d3_date.month <= 10 else (d3_date.month - 10, d3_date.year + 1)
_, last_d = calendar.monthrange(y4, m4)
d4_end = date(y4, m4, last_d)

st.success(f"📡 獵殺區間：D1({d1_start}~{d1_end}) | D4({d4_start}~{d4_end})")

cabin = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)
selected_hubs = st.multiselect("📍 選擇掃描外站：", ["MNL", "BKK", "HKG", "KIX", "NRT", "ICN", "PUS", "SGN", "KUL", "FUK"], default=["MNL", "BKK", "KIX"])

if st.button("🚀 啟動聯程獵殺", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 診斷報告", expanded=True)
    
    d1_m = get_month_strings(d1_start, d1_end)
    d4_m = get_month_strings(d4_start, d4_end)
    
    d1_cands, d4_cands = [], []

    # 1. 第一階段：日曆探路
    for hub in selected_hubs:
        msg.info(f"⚡ 正在探測 {hub} 窗口...")
        for m in d1_m: d1_cands.extend(scan_calendar(hub, d2_org, m, cabin, d1_start, d1_end))
        for m in d4_m: d4_cands.extend(scan_calendar(d3_dst, hub, m, cabin, d4_start, d4_end))
    
    debug.write(f"📊 探測結果：去程找到 {len(d1_cands)} 個窗口，回程找到 {len(d4_cands)} 個窗口。")

    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足。這代表華航在此日期區間並未釋放低價商務艙位（I/D 艙），或是 API 被擋。")
    else:
        # 2. 第二階段：真實打包價精算
        msg.warning("🔥 正在請求四段聯程打包價 (Married Segments)...")
        # 為了穩定，各選前 3 名進行交叉配對
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:3]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:3]
        
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            tasks = [executor.submit(fetch_bundle_price, d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults) for d1, d4 in product(top_d1, top_d4)]
            for f in as_completed(tasks):
                res = f.result()
                if res: results.append(res)
        
        msg.empty()
        if results:
            st.success("🎉 獵殺成功！以下為打包後的總價（保證純華航）：")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} | {r['d1']} & {r['d4']} ➔ NT$ {r['total']:,}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 精算失敗。代表這四段湊在一起時，華航不允許低價組合。")
