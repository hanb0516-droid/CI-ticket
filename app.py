import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- 介面美化與隱藏 ---
st.set_page_config(page_title="華航外站獵殺器 v3.2", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛡️ 硬核限速器：每秒請求數壓低，保證 API 穩定
rate_limiter = threading.Semaphore(4)

def stable_request(url, method="GET", params=None, json=None):
    with rate_limiter:
        for i in range(3):
            try:
                if method == "GET":
                    res = requests.get(url, headers=HEADERS, params=params, timeout=15)
                else:
                    res = requests.post(url, headers=HEADERS, json=json, timeout=25)
                
                if res.status_code == 200: return res.json()
                elif res.status_code == 429: time.sleep(2 ** i) # 429 就多等一下
                else: time.sleep(0.5)
            except: time.sleep(0.5)
        return None

# 🌟 引擎 A：價格日曆雷達 (增加詳細偵錯)
def task_calendar_scan(origin, dest, month_str, cabin, s_date, e_date):
    url = f"{BASE_URL}/flights/price-calendar"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": cabin_map[cabin]}
    
    data = stable_request(url, params=params)
    results = []
    log_msg = f"{origin} ➔ {dest} ({month_str}): "

    if data and isinstance(data, dict) and data.get('data'):
        days = data['data'].get('days', [])
        if not days:
            return results, log_msg + "空資料"
        for day in days:
            try:
                d_obj = datetime.strptime(day['day'], "%Y-%m-%d").date()
                if s_date <= d_obj <= e_date and day.get('price', 0) > 0:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": day['price']})
            except: continue
        return results, log_msg + f"找到 {len(results)} 天"
    return results, log_msg + "API 連線失敗"

# 🌟 引擎 B：100% 真實打包精算
def task_final_check(h_in, d1, h_out, d4, d2_from, d2_to, d2_date, d3_from, d3_to, d3_date, cabin, adults):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
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
        legs_data = itin.get('legs', [])
        if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in legs_data):
            details = []
            for l in legs_data:
                seg = l.get('segments', [{}])[0]
                b_code = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                details.append(f"CI {seg.get('flightNumber')} ({b_code}) | {l.get('departure','').split('T')[1][:5]}")
            return {"title": f"{h_in}({d1}) ➔ {h_out}({d4})", "total": int(itin['price']['raw']), "legs": details}
    return None

# --- UI 介面 ---
st.title("✈️ 華航外站全境獵殺器 v3.2 (戰地救援版)")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市", value="TPE")
    d2_dst = st.text_input("D2 抵達城市", value="PRG")
    d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市", value="FRA")
    d3_dst = st.text_input("D3 抵達城市", value="TPE")
    d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

# 動態區間
def get_range(d2, d3):
    m1 = d2.month - 2
    y1 = d2.year
    if m1 <= 0: m1 += 12; y1 -= 1
    d1_s = date(y1, m1, 1)
    m4 = d3.month + 2
    y4 = d3.year
    if m4 > 12: m4 -= 12; y4 += 1
    _, last = calendar.monthrange(y4, m4)
    return d1_s, d2, d3, date(y4, m4, last)

d1_s, d1_e, d4_s, d4_e = get_range(d2_date, d3_date)
st.success(f"📡 獵殺範圍：D1 ({d1_s} ~ {d1_e}) | D4 ({d4_s} ~ {d4_e})")

cabin = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)

# 讓用戶選航點，避免 API 全部跑一次太慢
all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]
selected_hubs = st.multiselect("📍 選擇要掃描的外站 (建議 5-8 個最穩)：", all_hubs, default=["KIX", "NRT", "BKK", "MNL", "HKG", "ICN", "PUS"])

if st.button("🚀 啟動全亞洲區間深度獵殺", use_container_width=True):
    msg = st.empty()
    debug_area = st.expander("🛠️ 掃描日誌 (若無結果請查看此處)", expanded=True)
    
    def get_months_list(s, e):
        months = []
        curr = s.replace(day=1)
        while curr <= e:
            months.append(curr.strftime("%Y-%m"))
            curr = (curr + timedelta(days=32)).replace(day=1)
        return sorted(list(set(months)))

    d1_m = get_months_list(d1_s, d1_e)
    d4_m = get_months_list(d4_s, d4_e)

    d1_cands, d4_cands = [], []

    msg.info(f"⚡ 階段一：正在對 {len(selected_hubs)} 個航點進行區間快掃...")
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        f_in = [executor.submit(task_calendar_scan, h, d2_org, m, cabin, d1_s, d1_e) for h, m in product(selected_hubs, d1_m)]
        f_out = [executor.submit(task_calendar_scan, d3_dst, h, m, cabin, d4_s, d4_e) for h, m in product(selected_hubs, d4_m)]
        
        for f in as_completed(f_in):
            res, log = f.result()
            d1_cands.extend(res)
            debug_area.write(f"去程 - {log}")
            
        for f in as_completed(f_out):
            res, log = f.result()
            d4_cands.extend(res)
            debug_area.write(f"回程 - {log}")

    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足！上方日誌顯示 API 未回傳有效票價。請稍候再按一次，或縮小外站範圍。")
    else:
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:4]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:4]
        
        msg.warning(f"🎯 階段二：精算 {len(top_d1) * len(top_d4)} 組真實報價...")
        
        final_results = []
        with ThreadPoolExecutor(max_workers=4) as executor:
            tasks = [executor.submit(task_final_check, d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults) for d1, d4 in product(top_d1, top_d4)]
            for f in as_completed(tasks):
                res = f.result()
                if res: final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success("🎉 獵殺完畢！")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} ➔ 總價 NT$ {r['total']:,}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 深度精算無結果，請微調外站日期再試。")
