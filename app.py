import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 核心引擎：多點搜尋 (用於最後的 100% 真實總價與艙等精算)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_exact_4_legs(hub_in, hub_out, out_dest, in_origin, d1, d2, d3, d4, cabin_class, adults, children, infants):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-multi-city"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_mapping[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": hub_in, "toEntityId": "TPE", "departDate": d1},
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3},
            {"fromEntityId": "TPE", "toEntityId": hub_out, "departDate": d4}
        ]
    }
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

    try:
        time.sleep(1.0) 
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        data = response.json()
        itineraries = data.get('data', {}).get('itineraries', [])
        if not itineraries: return {"status": "❌"}

        ci_itinerary = None
        for itin in itineraries:
            is_all_ci = True
            for leg in itin.get('legs', []):
                carriers = leg.get('carriers', {}).get('marketing', [])
                if not carriers or carriers[0].get('alternateId', '') != 'CI':
                    is_all_ci = False; break
            if is_all_ci:
                ci_itinerary = itin; break

        if not ci_itinerary: return {"status": "❌"}
        
        # 🎯 提取細節 (航班編號 + 艙等)
        leg_infos = []
        for leg in ci_itinerary.get('legs', []):
            segment = leg.get('segments', [{}])[0]
            f_num = segment.get('flightNumber', '')
            b_class = segment.get('bookingCode', 'N/A') # 抓取 O, J, K 等
            dep_time = leg.get('departure', '').split('T')[1][:5]
            leg_infos.append(f"CI {f_num} ({b_class}) | {dep_time}")
            
        return {"status": "✅", "total": int(ci_itinerary['price']['raw']), "legs": leg_details, "booking_class": b_class, "raw_legs": leg_infos}
    except:
        return {"status": "❌"}

# 🌟 長程基準價查詢 (單買 A進B出)
@st.cache_data(ttl=3600, show_spinner=False)
def get_long_haul_base(out_dest, in_origin, d2, d3, cabin_class, adults, children, infants):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-multi-city"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_mapping[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3}
        ]
    }
    try:
        res = requests.post(url, json=payload, headers={"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}, timeout=25)
        itins = res.json().get('data', {}).get('itineraries', [])
        for itin in itins:
            if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
                return int(itin['price']['raw'])
        return 0
    except: return 0

# 🌟 單程快掃雷達
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asia_radar(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", "cabinClass": "business" if cabin_class=="商務艙" else ("premiumeconomy" if cabin_class=="豪經艙" else "economy")}
    try:
        time.sleep(0.4)
        res = requests.get(url, headers={"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com"}, params=params, timeout=12)
        itins = res.json().get('data', {}).get('itineraries', [])
        for itin in itins:
            if itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI':
                return itin['price']['raw']
        return 999999
    except: return 999999

# --- App 介面 ---
st.title("✈️ 華航外站全境盲掃 (專業玩家版)")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=2)
with c2: children = st.number_input("兒童", value=1)
with c3: infants = st.number_input("嬰兒", value=1)

all_asia_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 執行全境漏斗掃描", use_container_width=True):
    d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
    d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
    
    progress_bar = st.progress(0, text="📡 第一階段：正在鎖定長程原始票價...")
    
    # 🔍 先查長程單買當基準
    base_long_price = get_long_haul_base(out_dest, in_origin, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), cabin_choice, adults, children, infants)
    
    # 📡 雷達掃描亞洲站點
    in_found, out_found = [], []
    for i, hub in enumerate(all_asia_hubs):
        progress_bar.progress(int((i/22)*40), text=f"📡 雷達掃描：{hub}...")
        p1 = fetch_asia_radar(hub, "TPE", d1_date, cabin_choice)
        if p1 < 999999: in_found.append((hub, p1))
        p4 = fetch_asia_radar("TPE", hub, d4_date, cabin_choice)
        if p4 < 999999: out_found.append((hub, p4))

    if not in_found or not out_found:
        st.error("樣本不足，請更換日期。")
    else:
        best_in = [x[0] for x in sorted(in_found, key=lambda x: x[1])[:4]]
        best_out = [x[0] for x in sorted(out_found, key=lambda x: x[1])[:4]]
        combos = list(product(best_in, best_out))
        results = []
        
        for i, (h_in, h_out) in enumerate(combos):
            progress_bar.progress(40 + int(((i+1)/len(combos))*60), text=f"🔥 深度精算：{h_in} ➔ {h_out}...")
            res = fetch_exact_4_legs(h_in, h_out, out_dest, in_origin, d1_date, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), d4_date, cabin_choice, adults, children, infants)
            if res["status"] == "✅":
                diff = base_long_price - res["total"]
                results.append({
                    "title": f"【{h_in} 進 / {h_out} 出】",
                    "total": res["total"],
                    "diff": diff,
                    "legs": res["raw_legs"]
                })
                
        progress_bar.empty()
        if results:
            st.success(f"🎉 掃描完成！長程直飛基準價為 NT$ {base_long_price:,}")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} 總價：NT$ {r['total']:,}"):
                    st.write(f"🤑 四段開法比「直接長程來回」省下：**NT$ {r['diff']:,}**")
                    st.write("---")
                    st.write("**✈️ 航班明細 (含艙等代碼)：**")
                    st.write(f"1️⃣ {d1_date} | {r['legs'][0]}")
                    st.write(f"2️⃣ {date_out} | {r['legs'][1]}")
                    st.write(f"3️⃣ {date_in} | {r['legs'][2]}")
                    st.write(f"4️⃣ {d4_date} | {r['legs'][3]}")
