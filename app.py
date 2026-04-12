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
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com"}

# 🛠️ 穩定型 API 請求函數 (具備自動重試邏輯)
def stable_request(url, method="GET", params=None, json=None):
    for i in range(3): # 最多重試 3 次
        try:
            if method == "GET":
                res = requests.get(url, headers=HEADERS, params=params, timeout=15)
            else:
                res = requests.post(url, headers=HEADERS, json=json, timeout=25)
            
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429: # 流量限制
                time.sleep(2 ** i) # 指數退避延遲
            else:
                time.sleep(1)
        except:
            time.sleep(1)
    return None

# 🌟 引擎 A：價格日曆雷達 (大幅縮短掃描區間的時間)
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

# 🌟 引擎 B：最後精算 (100% 真實打包價)
def task_final_check(h_in, d1, h_out, d4, out_dest, d2, in_origin, d3, cabin, adults, kids, inf):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(kids), "infants": int(inf),
        "cabinClass": cabin_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": "TPE", "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2.strftime("%Y-%m-%d")},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3.strftime("%Y-%m-%d")},
            {"fromEntityId": "TPE", "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(url, method="POST", json=payload)
    if not data: return None
    
    itins = data.get('data', {}).get('itineraries', [])
    for itin in itins:
        # 嚴格過濾純華航
        if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
            legs = [f"CI {l['segments'][0]['flightNumber']} ({l['segments'][0].get('bookingCode','N/A')})" for l in itin['legs']]
            return {"title": f"{h_in}({d1}) ➔ {h_out}({d4})", "total": int(itin['price']['raw']), "legs": legs}
    return None

# --- UI 介面 ---
st.title("✈️ 華航獵殺器 3.0：全區間高速盲掃版")

# 日期邏輯自動推算
c_d2, c_d3 = st.columns(2)
with c_d2: d2_val = st.date_input("去程 D2", value=date(2026, 6, 11))
with c_d3: d3_val = st.date_input("回程 D3", value=date(2026, 6, 25))

# 動態設定區間
d1_start = date(2026, 4, 1)
d1_end = d2_val
d4_start = d3_val
d4_end = date(2026, 8, 31)

st.success(f"📡 獵殺範圍：D1 ({d1_start} ~ {d1_end}) | D4 ({d4_start} ~ {d4_end})")

cabin_choice = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動全亞洲區間盲掃", use_container_width=True):
    msg = st.empty()
    msg.info("⚡ 第一階段：正在並行掃描全亞洲 22 航點價格日曆...")
    
    # 找出區間內所有月份
    def get_months(s, e):
        res = []
        curr = s.replace(day=1)
        while curr <= e:
            res.append(curr.strftime("%Y-%m"))
            curr = (curr + timedelta(days=32)).replace(day=1)
        return res

    d1_m = get_months(d1_start, d1_end)
    d4_m = get_months(d4_start, d4_end)

    d1_candidates = []
    d4_candidates = []

    # 並行執行雷達掃描
    with ThreadPoolExecutor(max_workers=5) as executor: # 限制線程數避免 API 崩潰
        f_in = [executor.submit(task_calendar_scan, h, "TPE", m, cabin_choice, d1_start, d1_end) for h, m in product(all_hubs, d1_m)]
        f_out = [executor.submit(task_calendar_scan, "TPE", h, m, cabin_choice, d4_start, d4_end) for h, m in product(all_hubs, d4_m)]
        
        for f in as_completed(f_in): d1_candidates.extend(f.result())
        for f in as_completed(f_out): d4_candidates.extend(f.result())

    if not d1_candidates or not d4_candidates:
        st.error("🚨 找不到任何有效票價，請確認日期區間或 API 狀態。")
    else:
        # 篩選最便宜的起訖點 (前 4 名)
        best_d1 = sorted(d1_candidates, key=lambda x: x['price'])[:4]
        best_d4 = sorted(d4_candidates, key=lambda x: x['price'])[:4]
        
        msg.warning(f"🎯 雷達鎖定最優日期組合！正在精算真實總價...")
        
        final_results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            tasks = [executor.submit(task_final_check, d1['hub'], d1['day'], d4['hub'], d4['day'], "PRG", d2_val, "FRA", d3_val, cabin_choice, adults, 0, 0) for d1, d4 in product(best_d1, best_d4)]
            for f in as_completed(tasks):
                res = f.result()
                if res: final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success("🎉 獵殺完畢！以下是全區間絕對低價 Top 10：")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} ➔ NT$ {r['total']:,}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
