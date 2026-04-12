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
        time.sleep(1.0) # 精算放慢
        response = requests.post(url, json=payload, headers=headers, timeout=30)
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

        return {"status": "✅", "total_price": int(ci_itinerary['price']['raw']), "legs": [leg.get('departure', '').split('T')[1][:5] for leg in ci_itinerary.get('legs', [])]}
    except:
        return {"status": "❌ 系統錯誤", "total_price": 0, "legs": []}

# 🌟 引擎 B：單程快掃
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asia_radar(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", "cabinClass": cabin_mapping[cabin_class]}
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com"}

    try:
        time.sleep(0.5) 
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if response.status_code != 200: return 9999999
        
        data = response.json()
        itineraries = data.get('data', {}).get('itineraries', [])
        for itin in itineraries:
            carriers = itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [])
            if carriers:
                c_code = carriers[0].get('alternateId', '')
                if c_code == 'CI' or 'china airlines' in carriers[0].get('name', '').lower():
                    return itin['price']['raw']
        return 9999999
    except:
        return 9999999

# --- App 介面 ---
st.title("✈️ 華航外站全境盲掃神器 (修復版)")

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

all_asia_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動一鍵全境掃描 (約需 40 秒)", use_container_width=True):
    d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
    d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
    
    progress_bar = st.progress(0, text="📡 第一階段：正在初始化雷達掃描...")
    
    inbound_prices = []
    outbound_prices = []
    
    # 掃描
    for i, hub in enumerate(all_asia_hubs):
        progress_bar.progress(int((i / 22) * 40), text=f"📡 雷達掃描：{hub} ({i+1}/22)...")
        p_in = fetch_asia_radar(hub, "TPE", d1_date, cabin_choice)
        if p_in < 999999: inbound_prices.append((hub, p_in))
        
        p_out = fetch_asia_radar("TPE", hub, d4_date, cabin_choice)
        if p_out < 999999: outbound_prices.append((hub, p_out))

    if len(inbound_prices) < 2 or len(outbound_prices) < 2:
        progress_bar.empty()
        st.error("🚨 雷達掃描回傳樣本不足，請確認 API 額度或稍後再試。")
    else:
        top_in = [x[0] for x in sorted(inbound_prices, key=lambda x: x[1])[:4]]
        top_out = [x[0] for x in sorted(outbound_prices, key=lambda x: x[1])[:4]]
        
        st.info(f"🎯 雷達鎖定潛力點：\n起點：{', '.join(top_in)}\n終點：{', '.join(top_out)}")
        
        combos = list(product(top_in, top_out))
        results = []
        
        for i, (hub_in, hub_out) in enumerate(combos):
            percent = 40 + int(((i + 1) / len(combos)) * 60)
            progress_bar.progress(percent, text=f"🔥 第二階段精算：{hub_in} ➔ {hub_out} ({i+1}/{len(combos)})...")
            
            res = fetch_exact_4_legs(hub_in, hub_out, out_dest, in_origin, d1_date, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), d4_date, cabin_choice, adults, children, infants)
            
            if "✅" in res['status']:
                results.append({"title": f"{hub_in} 進 / {hub_out} 出", "total": res['total_price']})
                
        progress_bar.empty()
        if results:
            st.success("🎉 掃描完成！")
            for r in sorted(results, key=lambda x: x['total'])[:5]:
                st.write(f"🏆 {r['title']} ➔ 真實總價 NT$ {r['total']:,}")
