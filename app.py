import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面隱藏 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛠️ 穩定型 API 請求函數
def stable_request(url, method="GET", params=None, json=None):
    for i in range(3):
        try:
            if method == "GET":
                res = requests.get(url, headers=HEADERS, params=params, timeout=15)
            else:
                res = requests.post(url, headers=HEADERS, json=json, timeout=25)
            
            if res.status_code == 200: return res.json()
            elif res.status_code == 429: time.sleep(2 ** i)
            else: time.sleep(1)
        except: time.sleep(1)
    return None

# 🌟 引擎 A：價格日曆雷達 (抓取整個月趨勢)
def task_calendar_scan(origin, dest, month_str, cabin, s_date, e_date):
    url = f"{BASE_URL}/flights/price-calendar"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": cabin_map[cabin]}
    
    data = stable_request(url, params=params)
    if not data: return []
    
    results = []
    for day in data.get('data', {}).get('days', []):
        d_obj = datetime.strptime(day['day'], "%Y-%m-%d").date()
        if s_date <= d_obj <= e_date and day['price'] > 0:
            results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": day['price']})
    return results

# 🌟 引擎 B：100% 真實打包精算 (專業玩家版細節)
def task_final_check(h_in, d1, h_out, d4, d2_from, d2_to, d2_date, d3_from, d3_to, d3_date, cabin, adults, kids, inf):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(kids), "infants": int(inf),
        "cabinClass": cabin_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_from, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_from, "toEntityId": d2_to, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_from, "toEntityId": d3_to, "departDate": d3_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_to, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(url, method="POST", json=payload)
    if not data: return None
    
    itins = data.get('data', {}).get('itineraries', [])
    for itin in itins:
        if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
            legs = [f"CI {l['segments'][0]['flightNumber']} ({l['segments'][0].get('bookingCode','N/A')}) | {l['departure'].split('T')[1][:5]}" for l in itin['legs']]
            return {"title": f"{h_in}({d1}) ➔ {h_out}({d4})", "total": int(itin['price']['raw']), "legs": legs}
    return None

# 🌟 引擎 C：長程基準價
def task_long_haul_base(d2_from, d2_to, d2_date, d3_from, d3_to, d3_date, cabin, adults, kids, inf):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults), "children": int(kids), "infants": int(inf),
        "cabinClass": cabin_map[cabin], "flights": [
            {"fromEntityId": d2_from, "toEntityId": d2_to, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_from, "toEntityId": d3_to, "departDate": d3_date.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(url, method="POST", json=payload)
    try: return int(data['data']['itineraries'][0]['price']['raw'])
    except: return 0

# --- UI 介面 ---
st.title("✈️ 華航外站獵殺器：全區間並行版")

st.subheader("🗓️ 核心行程設定")
col1, col2 = st.columns(2)
with col1:
    st.write("**去程主段 (D2)**")
    d2_origin = st.text_input("D2 出發城市", value="TPE")
    d2_dest = st.text_input("D2 抵達城市", value="PRG")
    d2_date = st.date_input("D2 日期", value=date(2026, 6, 11))
with col2:
    st.write("**回程主段 (D3)**")
    d3_origin = st.text_input("D3 出發城市", value="FRA")
    d3_dest = st.text_input("D3 抵達城市", value="TPE")
    d3_date = st.date_input("D3 日期", value=date(2026, 6, 25))

# 動態計算區間
d1_start = (d2_date - timedelta(days=75)).replace(day=1)
d1_end = d2_date
d4_start = d3_date
d4_future = d3_date + timedelta(days=75)
d4_end = date(
