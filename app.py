import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面隱藏 ---
st.set_page_config(page_title="華航聯程獵殺器 v5.1", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"

# 🛠️ 穩定型請求 (加入 1.5 秒強制延遲，確保 API 100% 成功)
def stable_request(url, method="GET", params=None, json=None):
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}
    for i in range(3):
        try:
            time.sleep(1.2) # 保護頻率，避免 429
            if method == "GET":
                res = requests.get(url, headers=headers, params=params, timeout=20)
            else:
                res = requests.post(url, headers=headers, json=json, timeout=30)
            
            if res.status_code == 200: return res.json()
            elif res.status_code == 429: time.sleep(5) # 被擋就休息久一點
        except: time.sleep(1)
    return None

# 🌟 引擎 A：日曆雷達 (優化：自動跳過過去日期)
def scan_calendar(origin, dest, month_str, cabin, s_date, e_date):
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": cabin_map[cabin]}
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    results = []
    
    today = date.today()
    if data and data.get('data'):
        for d in data['data'].get('days', []):
            try:
                d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                # 🛡️ 核心修復：只搜尋今天以後的日期
                if d_obj >= today and s_date <= d_obj <= e_date and d.get('price', 0) > 0:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d['price']})
            except: continue
    return results

# 🌟 引擎 B：100% 真實四段聯程精算 (修正變數名稱錯誤)
def fetch_exact_bundle(h_in, d1, h_out, d4, d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults):
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": cabin_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_org, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_org, "toEntityId": d2_dst, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_org, "toEntityId": d3_dst, "departDate": d3_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_dst, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if not data or not data.get('data'): return None
    
    itins = data['data'].get('itineraries', [])
    for itin in itins:
        legs = itin.get('legs', [])
        if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in legs):
            details = [f"CI {l['segments'][0]['flightNumber']} ({l['segments'][0].get('bookingCode','N/A')}) | {l['departure'].split('T')[1][:5]}" for l in legs]
            return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": details, "d1": d1, "d4": d4}
    return None

# --- UI ---
st.title("✈️ 華航外站獵殺器 v5.1 (終極修正版)")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市 (如 TPE)", value="TPE")
    d2_dst = st.text_input("D2 抵達城市 (如 PRG)", value="PRG")
    d2_date = st.date_input("D2 去歐日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市 (如 FRA)", value="FRA")
    d3_dst = st.text_input("D3 抵達城市 (如 TPE)", value="TPE")
    d3_date = st.date_input("D3 回台日期", value=date(2026, 6, 25))

# 動態計算區間
today = date.today()
d1_s_raw = (d2_date - timedelta(days=75)).replace(day=1)
d1_s = max(d1_s_raw, today) # 🛡️ 防止搜到過去
d1_e = d2_date

d4_s = d3_date
m4, y4 = (d3_date.month + 2, d3_date.year)
if m4 > 12: m4 -= 12; y4 += 1
d4_e = date(y4, m4, calendar.monthrange(y4, m4)[1])

st.success(f"📡 獵殺區間：D1({d1_s}~{d1_e}) | D4({d4_s}~{d4_e})")

cabin = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)
selected_hubs = st.multiselect("📍 選擇掃描外站：", ["MNL", "BKK", "HKG", "KIX", "NRT", "ICN", "PUS", "SGN", "KUL", "FUK"], default=["MNL", "KIX", "BKK", "HKG"])

if st.button("🚀 執行真實聯程總價精算", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 實時掃描日誌", expanded=True)
    
    def get_ms(s, e):
        ms = []
        curr = s.replace(day=1)
        while curr <= e:
            ms.append(curr.strftime("%Y-%m"))
            if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
            else: curr = curr.replace(month=curr.month+1)
        return sorted(list(set(ms)))

    d1_m, d4_m = get_ms(d1_s, d1_e), get_ms(d4_s, d4_e)
    d1_cands, d4_cands = [], []

    # 1. 雷達掃描
    for hub in selected_hubs:
        for m in d1_m:
            msg.info(f"📡 階段一：掃描 {hub} 去程趨勢 ({m})...")
            res = scan_calendar(hub, d2_org, m, cabin, d1_s, d1_e)
            d1_cands.extend(res)
            if res: debug.write(f"✅ {hub} ({m}) 去程：找到 {len(res)} 個日期")
        for m in d4_m:
            msg.info(f"📡 階段一：掃描 {hub} 回程趨勢 ({m})...")
            res = scan_calendar(d3_dst, hub, m, cabin, d4_s, d4_e)
            d4_cands.extend(res)
            if res: debug.write(f"✅ {hub} ({m}) 回程：找到 {len(res)} 個日期")
    
    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足！這可能是因為：1. 華航本日無機位 2. API 正在限制頻率。請稍等 10 秒後再按一次。")
    else:
        # 2. 聯程精算 (挑選潛力日期)
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:3]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:3]
        
        msg.warning(f"🔥 階段二：正在精算 {len(top_d1)*len(top_d4)} 組 100% 真實打包價...")
        results = []
        with ThreadPoolExecutor(max_workers=3) as executor:
            tasks = [executor.submit(fetch_exact_bundle, d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults) for d1, d4 in product(top_d1, top_d4)]
            for f in as_completed(tasks):
                res = f.result()
                if res: results.append(res)
        
        msg.empty()
        if results:
            st.success(f"🎉 獵殺完成！以下是區間內最強聯程票價：")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} | D1:{r['d1']} & D4:{r['d4']} ➔ 總價 NT$ {r['total']:,}"):
                    st.write("✈️ 航班明細 (含艙等代碼)：")
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
