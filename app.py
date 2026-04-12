import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- 介面隱藏 ---
st.set_page_config(page_title="華航外站獵殺器", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛡️ 全域限速器 (每秒最多 5 個請求，防止被判斷為攻擊)
rate_limiter = threading.Semaphore(5)

def stable_request(url, method="GET", params=None, json=None):
    with rate_limiter:
        for i in range(3):
            try:
                if method == "GET":
                    res = requests.get(url, headers=HEADERS, params=params, timeout=15)
                else:
                    res = requests.post(url, headers=HEADERS, json=json, timeout=25)
                
                if res.status_code == 200: return res.json()
                elif res.status_code == 429: time.sleep(1.5 ** i)
                else: time.sleep(0.5)
            except: time.sleep(0.5)
        return None

# 🌟 引擎 A：價格日曆雷達 (修復 AttributeError)
def task_calendar_scan(origin, dest, month_str, cabin, s_date, e_date):
    url = f"{BASE_URL}/flights/price-calendar"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": cabin_map[cabin]}
    
    data = stable_request(url, params=params)
    results = []
    
    # 🛡️ 防禦性檢查：確保 data 和 data['data'] 都不是 None
    if data and isinstance(data, dict) and data.get('data'):
        days = data['data'].get('days', [])
        for day in days:
            try:
                d_obj = datetime.strptime(day['day'], "%Y-%m-%d").date()
                if s_date <= d_obj <= e_date and day.get('price', 0) > 0:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": day['price']})
            except: continue
    return results

# 🌟 引擎 B：100% 真實打包精算
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
    if not data or not data.get('data'): return None
    
    itins = data['data'].get('itineraries', [])
    for itin in itins:
        # 確保純華航
        legs_data = itin.get('legs', [])
        is_ci = all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in legs_data)
        if is_ci:
            details = []
            for l in legs_data:
                seg = l.get('segments', [{}])[0]
                b_code = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                details.append(f"CI {seg.get('flightNumber')} ({b_code}) | {l.get('departure','').split('T')[1][:5]}")
            return {"title": f"{h_in}({d1}) ➔ {h_out}({d4})", "total": int(itin['price']['raw']), "legs": details}
    return None

# --- UI 介面 ---
st.title("✈️ 華航外站全境獵殺器 3.1 (修復加速版)")

# 1. 行程設定
st.subheader("🗓️ 核心行程與區間定義")
col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市", value="TPE")
    d2_dst = st.text_input("D2 抵達城市", value="PRG")
    d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市", value="FRA")
    d3_dst = st.text_input("D3 抵達城市", value="TPE")
    d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

# 動態計算區間
def get_range(d2, d3):
    # D1: D2 前兩個月 1 號 ~ D2
    m1 = d2.month - 2
    y1 = d2.year
    if m1 <= 0: m1 += 12; y1 -= 1
    d1_s = date(y1, m1, 1)
    # D4: D3 ~ D3 後兩個月最後一天
    m4 = d3.month + 2
    y4 = d3.year
    if m4 > 12: m4 -= 12; y4 += 1
    _, last = calendar.monthrange(y4, m4)
    d4_e = date(y4, m4, last)
    return d1_s, d2, d3, d4_e

d1_s, d1_e, d4_s, d4_e = get_range(d2_date, d3_date)
st.success(f"📡 獵殺範圍：D1 ({d1_s} ~ {d1_e}) | D4 ({d4_s} ~ {d4_e})")

cabin = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動全亞洲區間深度獵殺", use_container_width=True):
    msg = st.empty()
    msg.info("⚡ 階段一：正在全速掃描 22 站價格日曆...")
    
    def get_months_list(s, e):
        months = []
        curr = s.replace(day=1)
        while curr <= e:
            months.append(curr.strftime("%Y-%m"))
            if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
            else: curr = curr.replace(month=curr.month+1)
        return months

    d1_m = get_months_list(d1_s, d1_e)
    d4_m = get_months_list(d4_s, d4_e)

    d1_cands, d4_cands = [], []

    # 並行快掃 (Thread 數量根據 Cloud 環境優化)
    with ThreadPoolExecutor(max_workers=10) as executor:
        f_in = [executor.submit(task_calendar_scan, h, d2_org, m, cabin, d1_s, d1_e) for h, m in product(all_hubs, d1_m)]
        f_out = [executor.submit(task_calendar_scan, d3_dst, h, m, cabin, d4_s, d4_e) for h, m in product(all_hubs, d4_m)]
        
        for f in as_completed(f_in): d1_cands.extend(f.result())
        for f in as_completed(f_out): d4_cands.extend(f.result())

    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足，這代表該區間華航暫無票價數據。")
    else:
        # 取潛力點 (前 4 名日期組合)
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:4]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:4]
        
        msg.warning(f"🎯 雷達鎖定最優日期！正在精算 16 組【{cabin}】真實打包價...")
        
        final_results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            tasks = [executor.submit(task_final_check, d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults, 0, 0) for d1, d4 in product(top_d1, top_d4)]
            for f in as_completed(tasks):
                res = f.result()
                if res: final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success("🎉 獵殺完畢！以下是全區間內的最強外站票排名：")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} ➔ 總價 NT$ {r['total']:,}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 精算失敗，可能該日期組合的艙位已售罄。")
