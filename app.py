import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 引擎 A：多點搜尋 (用於最後的 100% 真實總價與艙等精算)
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
                # 嚴格過濾：必須是華航 (CI)
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
            b_class = segment.get('bookingCode', 'N/A')
            dep_time = leg.get('departure', '').split('T')[1][:5]
            leg_infos.append(f"CI {f_num} ({b_class}) | {dep_time}")
            
        # 修正後的變數名稱：將 leg_details 改回 leg_infos
        return {"status": "✅", "total": int(ci_itinerary['price']['raw']), "legs": leg_infos}
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
            # 確保長程段也是華航
            if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
                return int(itin['price']['raw'])
        return 0
    except: return 0

# 🌟 單程快掃雷達
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asia_radar(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", "cabinClass": cabin_mapping[cabin_class]}
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
st.title("✈️ 華航外站全境盲掃 (專業玩家修正版)")

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
with c1: adults = st.number_input("大人", value=1) # 預設改回 1 人測試
with c2: children = st.number_input("兒童", value=0)
with c3: infants = st.number_input("嬰兒", value=0)

all_asia_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 執行一鍵精算", use_container_width=True):
    d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
    d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
    
    progress_bar = st.progress(0, text="📡 正在初始化系統...")
    
    # 🔍 先查長程單買基準
    progress_bar.progress(5, text="🌍 正在鎖定長程原始票價基準...")
    base_long_price = get_long_haul_base(out_dest, in_origin, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), cabin_choice, adults, children, infants)
    
    # 📡 雷達掃描亞洲站點
    in_found, out_found = [], []
    for i, hub in enumerate(all_asia_hubs):
        progress_bar.progress(5 + int((i/22)*35), text=f"📡 雷達掃描：{hub}...")
        p1 = fetch_asia_radar(hub, "TPE", d1_date, cabin_choice)
        if p1 < 999999: in_found.append((hub, p1))
        p4 = fetch_asia_radar("TPE", hub, d4_date, cabin_choice)
        if p4 < 999999: out_found.append((hub, p4))

    st.write(f"📊 雷達報告：去程找到 {len(in_found)} 站，回程找到 {len(out_found)} 站。")

    if not in_found or not out_found:
        st.error("🚨 雷達樣本不足，無法組成四段票，請換個日期試試。")
    else:
        # 取前 4 名潛力點
        best_in = [x[0] for x in sorted(in_found, key=lambda x: x[1])[:4]]
        best_out = [x[0] for x in sorted(out_found, key=lambda x: x[1])[:4]]
        combos = list(product(best_in, best_out))
        results = []
        
        for i, (h_in, h_out) in enumerate(combos):
            progress_bar.progress(40 + int(((i+1)/len(combos))*60), text=f"🔥 深度精算 100% 真實價：{h_in} ➔ {h_out}...")
            res = fetch_exact_4_legs(h_in, h_out, out_dest, in_origin, d1_date, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), d4_date, cabin_choice, adults, children, infants)
            
            if res["status"] == "✅":
                # 只有成功抓到結果才加入清單
                diff = base_long_price - res["total"] if base_long_price > 0 else 0
                results.append({
                    "title": f"【{h_in} 進 / {h_out} 出】",
                    "total": res["total"],
                    "diff": diff,
                    "legs": res["legs"]
                })
                
        progress_bar.empty()
        
        if results:
            if base_long_price > 0:
                st.success(f"🎉 掃描完成！長程直飛基準價為 NT$ {base_long_price:,}")
            else:
                st.warning("⚠️ 長程基準價抓取失敗，僅顯示四段總價排名。")
                
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} 總價：NT$ {r['total']:,}"):
                    if r['diff'] > 0:
                        st.write(f"🤑 四段開法比「直接長程來回」省下：**NT$ {r['diff']:,}**")
                    elif r['diff'] < 0:
                        st.write(f"ℹ️ 此組合比直飛貴 NT$ {abs(r['diff']):,}")
                    st.write("---")
                    st.write(f"**✈️ 實際航班明細 (保證華航 {cabin_choice})：**")
                    st.write(f"1️⃣ {d1_date} | {r['legs'][0]}")
                    st.write(f"2️⃣ {date_out} | {r['legs'][1]}")
                    st.write(f"3️⃣ {date_in} | {r['legs'][2]}")
                    st.write(f"4️⃣ {d4_date} | {r['legs'][3]}")
        else:
            st.error("❌ 深度精算失敗：16 個組合都無法抓到純華航機位。這通常是因為該日期機位已售罄。")
