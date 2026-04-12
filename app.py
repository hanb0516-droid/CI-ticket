import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面設定與隱藏 ---
st.set_page_config(page_title="華航外站獵殺器", layout="wide")
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

# 🌟 引擎 A：價格日曆雷達
def task_calendar_scan(origin, dest, month_str, cabin, s_date, e_date):
    url = f"{BASE_URL}/flights/price-calendar"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": cabin_map[cabin]}
    
    data = stable_request(url, params=params)
    if not data: return []
    
    results = []
    days = data.get('data', {}).get('days', [])
    for day in days:
        try:
            d_obj = datetime.strptime(day['day'], "%Y-%m-%d").date()
            if s_date <= d_obj <= e_date and day['price'] > 0:
                results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": day['price']})
        except: continue
    return results

# 🌟 引擎 B：100% 真實精算 (已修正 SyntaxError)
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

# --- UI 介面 ---
st.title("✈️ 華航外站全境獵殺器：動態區間版")

# 1. 核心行程設定
st.subheader("🗓️ 行程日期設定")
col1, col2 = st.columns(2)
with col1:
    d2_origin = st.text_input("去程出發 (D2)", value="TPE")
    d2_dest = st.text_input("去程終點 (D2)", value="PRG")
    d2_date = st.date_input("去程日期 (D2)", value=date(2026, 6, 11))
with col2:
    d3_origin = st.text_input("回程出發 (D3)", value="FRA")
    d3_dest = st.text_input("回程終點 (D3)", value="TPE")
    d3_date = st.date_input("回程日期 (D3)", value=date(2026, 6, 25))

# 2. 自動推算 D1 & D4 區間 (動態月份邏輯)
def get_range_dates(d2, d3):
    # D1 區間：D2 前兩個月的 1 號到 D2
    d1_m = d2.month - 2
    d1_y = d2.year
    if d1_m <= 0: d1_m += 12; d1_y -= 1
    d1_start = date(d1_y, d1_m, 1)
    d1_end = d2

    # D4 區間：D3 到 D3 後兩個月的最後一天
    d4_m = d3.month + 2
    d4_y = d3.year
    if d4_m > 12: d4_m -= 12; d4_y += 1
    _, last_day = calendar.monthrange(d4_y, d4_m)
    d4_start = d3
    d4_end = date(d4_y, d4_m, last_day) # 修正語法錯誤
    
    return d1_start, d1_end, d4_start, d4_end

d1_s, d1_e, d4_s, d4_e = get_range_dates(d2_date, d3_date)

st.info(f"📡 獵殺區間設定：\n- 第一段 (D1): {d1_s} ~ {d1_e}\n- 第四段 (D4): {d4_s} ~ {d4_e}")

# 3. 艙等與成員
cabin_choice = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動全亞洲區間盲掃", use_container_width=True):
    msg = st.empty()
    msg.warning("⚡ 階段一：正在全速掃描 22 站價格日曆趨勢...")
    
    def get_months(s, e):
        res = []
        curr = s.replace(day=1)
        while curr <= e:
            res.append(curr.strftime("%Y-%m"))
            if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
            else: curr = curr.replace(month=curr.month+1)
        return res

    d1_months = get_months(d1_s, d1_e)
    d4_months = get_months(d4_s, d4_e)

    d1_cands, d4_cands = [], []

    # 並行快掃日曆
    with ThreadPoolExecutor(max_workers=8) as executor:
        f_in = [executor.submit(task_calendar_scan, h, d2_origin, m, cabin_choice, d1_s, d1_e) for h, m in product(all_hubs, d1_months)]
        f_out = [executor.submit(task_calendar_scan, d3_dest, h, m, cabin_choice, d4_s, d4_e) for h, m in product(all_hubs, d4_months)]
        
        for f in as_completed(f_in): d1_cands.extend(f.result())
        for f in as_completed(f_out): d4_cands.extend(f.result())

    if not d1_cands or not d4_cands:
        st.error("🚨 雷達掃描無結果，可能華航在該區間尚未放票。")
    else:
        # 取潛力點 (前 4 名日期組合)
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:4]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:4]
        
        msg.warning(f"🎯 雷達鎖定最優日期！正在精算 16 組【{cabin_choice}】真實總價...")
        
        final_results = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            tasks = [executor.submit(task_final_check, d1['hub'], d1['day'], d4['hub'], d4['day'], d2_origin, d2_dest, d2_date, d3_origin, d3_dest, d3_date, cabin_choice, adults, 0, 0) for d1, d4 in product(top_d1, top_d4)]
            for f in as_completed(tasks):
                res = f.result()
                if res: final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success("🎉 獵殺完畢！以下是區間內絕對低價組合：")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} ➔ 總價 NT$ {r['total']:,}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 精算失敗，可能該區間艙位已售罄。")
