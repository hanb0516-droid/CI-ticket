import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 引擎 A：多點搜尋 (專門破解歐洲長程線 A進B出 真實票價)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_europe_main_legs(leg1_from, leg1_to, d1, leg2_from, leg2_to, d2, cabin_class, adults, children, infants):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-multi-city"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_mapping[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": leg1_from, "toEntityId": leg1_to, "departDate": d1},
            {"fromEntityId": leg2_from, "toEntityId": leg2_to, "departDate": d2}
        ]
    }
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        data = response.json()
        
        itineraries = data.get('data', {}).get('itineraries', [])
        if not itineraries: return {"status": "❌ 查無航班", "total_price": 0, "legs": []}

        ci_itinerary = None
        for itin in itineraries:
            is_all_ci = True
            for leg in itin.get('legs', []):
                carriers = leg.get('carriers', {}).get('marketing', [])
                if not carriers:
                    is_all_ci = False
                    break
                c_name = carriers[0].get('name', '').lower()
                c_code = carriers[0].get('alternateId', '')
                if '中華' not in c_name and 'china airlines' not in c_name and c_code != 'CI':
                    is_all_ci = False
                    break
            if is_all_ci:
                ci_itinerary = itin
                break

        if not ci_itinerary: return {"status": "❌ 查無純華航", "total_price": 0, "legs": []}

        real_total_price = ci_itinerary['price']['raw']
        flight_details = []
        for i in range(2):
            try:
                leg = ci_itinerary['legs'][i]
                carriers = leg.get('carriers', {}).get('marketing', [])
                c_name = carriers[0].get('name', '華航') if carriers else '華航'
                f_num = leg.get('segments', [{}])[0].get('flightNumber', '')
                dep = leg.get('departure', '')
                if 'T' in dep: dep = dep.split('T')[1][:5]
                flight_details.append(f"{c_name} {f_num} | {dep} 出發")
            except:
                flight_details.append("無航班資訊")
                
        return {"status": "✅", "total_price": int(real_total_price), "legs": flight_details}
    except:
        return {"status": f"❌ 系統錯誤", "total_price": 0, "legs": []}

# 🌟 引擎 B：單程搜尋 (嚴格過濾華航)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asia_outer_legs(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", "cabinClass": cabin_mapping[cabin_class]}
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com"}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=12)
        data = response.json()
        
        itineraries = data.get('data', {}).get('itineraries', [])
        ci_itinerary = None
        for itin in itineraries:
            leg = itin.get('legs', [{}])[0]
            carriers = leg.get('carriers', {}).get('marketing', [])
            if carriers:
                c_name = carriers[0].get('name', '').lower()
                c_code = carriers[0].get('alternateId', '')
                if '中華' in c_name or 'china airlines' in c_name or c_code == 'CI':
                    ci_itinerary = itin
                    break
                    
        if not ci_itinerary: return {"base_price": 0, "status": "❌ 查無華航", "info": ""}

        real_price = ci_itinerary['price']['raw']
        try:
            leg = ci_itinerary['legs'][0]
            c_name = leg.get('carriers', {}).get('marketing', [{}])[0].get('name', '華航')
            f_num = leg.get('segments', [{}])[0].get('flightNumber', '')
            dep = leg.get('departure', '')
            if 'T' in dep: dep = dep.split('T')[1][:5]
            f_info = f"{c_name} {f_num} | {dep} 出發"
        except:
            f_info = "無資訊"
            
        return {"base_price": int(real_price), "status": "✅", "info": f_info}
    except:
        return {"base_price": 0, "status": "❌ 異常", "info": ""}

def calc_family(base_price, adults, children, infants):
    return (base_price * adults) + (int(base_price * 0.75) * children) + (int(base_price * 0.10) * infants)

# --- App 介面 ---
st.title("✈️ 華航外站全境盲掃神器")
st.write("🌍 **拔掉選單限制！一鍵地毯式搜蕩亞洲 22 大樞紐，為您捕捉絕對最低價！**")

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

# 🌍 隱藏在引擎深處的華航亞洲 22 大主力航點 (不再讓用戶手選)
all_asia_hubs = [
    "FUK", "KIX", "NRT", "NGO", "CTS", "OKA",  # 日本
    "ICN", "PUS", "HKG", "MFM",                # 韓港澳
    "BKK", "CNX", "SIN", "KUL", "PEN",         # 東南亞(新馬泰)
    "MNL", "CEB", "SGN", "HAN", "DAD",         # 菲律賓、越南
    "CGK", "DPS"                               # 印尼
]

if st.button("🚀 啟動全境盲掃 (尋找絕對最低價)", use_container_width=True):
    # 建立一個進度條，讓等待過程不枯燥
    progress_bar = st.progress(0, text="📡 正在啟動華航票務主機連線...")
    
    results = []
    
    # 1. 抓歐洲長程主幹
    progress_bar.progress(5, text="🌍 正在獲取長程主段 (歐洲線) 基準票價...")
    europe_main = fetch_europe_main_legs("TPE", out_dest, date_out.strftime("%Y-%m-%d"), in_origin, "TPE", date_in.strftime("%Y-%m-%d"), cabin_choice, adults, children, infants)
    
    if "❌" in europe_main['status']:
        progress_bar.empty()
        st.error(f"⚠️ 歐洲主幹段查無純華航機票！(可能該日商務艙已售罄)")
    else:
        europe_total_price = europe_main['total_price']
        st.info(f"🌸 已鎖定華航歐洲長程真實總價：**NT$ {europe_total_price:,}**。接下來開始掃描外站稀釋成本！")
        
        # 2. 地毯式掃描 22 個外站的單程票價
        d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
        d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
        
        s1_cache = {}
        s4_cache = {}
        total_hubs = len(all_asia_hubs)
        
        for i, hub in enumerate(all_asia_hubs):
            # 更新進度條
            percent = int(((i + 1) / total_hubs) * 80) + 5 # 留 15% 給最後運算
            progress_bar.progress(percent, text=f"🛫 正在雷達掃描航點：{hub} ({i+1}/{total_hubs})...")
            
            # 溫和發送 API 請求以避免被伺服器封鎖
            time.sleep(0.4) 
            s1_cache[hub] = fetch_asia_outer_legs(hub, "TPE", d1_date, cabin_choice)
            time.sleep(0.4)
            s4_cache[hub] = fetch_asia_outer_legs("TPE", hub, d4_date, cabin_choice)
        
        # 3. 進行 22 x 22 = 484 種組合交叉運
