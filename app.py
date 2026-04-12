import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 引擎 A：多點搜尋 (用於最後的 100% 真實總價精算)
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
        time.sleep(0.8) # 精算需要放慢避免被擋
        response = requests.post(url, json=payload, headers=headers, timeout=25)
        if response.status_code == 429: return {"status": "❌ API額度耗盡", "total_price": 0, "legs": []}
            
        data = response.json()
        itineraries = data.get('data', {}).get('itineraries', [])
        if not itineraries: return {"status": "❌ 查無航班", "total_price": 0, "legs": []}

        ci_itinerary = None
        for itin in itineraries:
            is_all_ci = True
            for leg in itin.get('legs', []):
                carriers = leg.get('carriers', {}).get('marketing', [])
                if not carriers: is_all_ci = False; break
                c_name = carriers[0].get('name', '').lower()
                c_code = carriers[0].get('alternateId', '')
                if '中華' not in c_name and 'china airlines' not in c_name and c_code != 'CI':
                    is_all_ci = False; break
            if is_all_ci: ci_itinerary = itin; break

        if not ci_itinerary: return {"status": "❌ 查無純華航", "total_price": 0, "legs": []}

        real_total_price = ci_itinerary['price']['raw']
        flight_details = []
        for i in range(4):
            try:
                leg = ci_itinerary['legs'][i]
                c_name = leg.get('carriers', {}).get('marketing', [{}])[0].get('name', '華航')
                f_num = leg.get('segments', [{}])[0].get('flightNumber', '')
                dep = leg.get('departure', '')
                if 'T' in dep: dep = dep.split('T')[1][:5]
                flight_details.append(f"{c_name} {f_num} | {dep} 出發")
            except:
                flight_details.append("無航班資訊")
                
        return {"status": "✅", "total_price": int(real_total_price), "legs": flight_details}
    except Exception as e:
        return {"status": f"❌ 系統錯誤", "total_price": 0, "legs": []}

# 🌟 引擎 B：單程快掃 (用於第一階段雷達篩選，極速找出最便宜的外站)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asia_radar(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", "cabinClass": cabin_mapping[cabin_class]}
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com"}

    try:
        time.sleep(0.3) # 雷達掃描可以快一點
        response = requests.get(url, headers=headers, params=params, timeout=10)
        data = response.json()
        itineraries = data.get('data', {}).get('itineraries', [])
        
        ci_price = 9999999
        for itin in itineraries:
            carriers = itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [])
            if carriers:
                c_name = carriers[0].get('name', '').lower()
                c_code = carriers[0].get('alternateId', '')
                if '中華' in c_name or 'china airlines' in c_name or c_code == 'CI':
                    ci_price = itin['price']['raw']
                    break # 找到該航線最便宜的華航機票就停止
                    
        return ci_price
    except:
        return 9999999

# --- App 介面 ---
st.title("✈️ 華航外站全境盲掃神器 (兩階段漏斗版)")
st.markdown("⚠️ **一鍵自動掃描全亞洲 22 站，並為您精算出 100% 真實結帳價！**")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=2)
with c2: children = st.number_input("兒童", value=1)
with c3: infants = st.number_input("嬰兒", value=1)

# 全亞洲 22 大樞紐
all_asia_hubs = [
    "FUK", "KIX", "NRT", "NGO", "CTS", "OKA",  
    "ICN", "PUS", "HKG", "MFM",                
    "BKK", "CNX", "SIN", "KUL", "PEN",         
    "MNL", "CEB", "SGN", "HAN", "DAD",         
    "CGK", "DPS"                               
]

if st.button("🚀 啟動一鍵全境掃描 (約需 40 秒)", use_container_width=True):
    d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
    d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
    
    # 🎯 第一階段：廣域雷達快掃
    progress_bar = st.progress(0, text="📡 第一階段：正在利用雷達快掃 22 大外站去程價格...")
    
    # 掃描去程 (Hub -> TPE)
    inbound_prices = []
    for i, hub in enumerate(all_asia_hubs):
        progress_bar.progress(int((i / 22) * 20), text=f"📡 雷達掃描去程：{hub} ({i+1}/22)...")
        price = fetch_asia_radar(hub, "TPE", d1_date, cabin_choice)
        if price < 9999999:
            inbound_prices.append((hub, price))
            
    # 掃描回程 (TPE -> Hub)
    outbound_prices = []
    for i, hub in enumerate(all_asia_hubs):
        progress_bar.progress(20 + int((i / 22) * 20), text=f"📡 雷達掃描回程：{hub} ({i+1}/22)...")
        price = fetch_asia_radar("TPE", hub, d4_date, cabin_choice)
        if price < 9999999:
            outbound_prices.append((hub, price))
            
    if not inbound_prices or not outbound_prices:
        progress_bar.empty()
        st.error("🚨 尋找不到任何有飛的亞洲站點，可能是該日期未放票。")
    else:
        # 篩選出最便宜的前 4 名起點與終點
        top_4_in
