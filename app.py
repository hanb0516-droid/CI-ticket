import streamlit as st
from datetime import datetime, timedelta, date
import calendar
import requests
import time

# --- 介面隱藏與設定 ---
st.set_page_config(page_title="華航獵殺器 v8.0", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"

# 🛡️ 穩定型請求 (加入 2.0 秒硬性冷卻，保證 API 成功率)
def stable_request(url, method="GET", params=None, json=None):
    headers = {
        "x-rapidapi-key": API_KEY,
        "x-rapidapi-host": "flights-sky.p.rapidapi.com",
        "Content-Type": "application/json"
    }
    for i in range(3):
        try:
            time.sleep(2.0) # 電工級保險：2秒延遲
            if method == "GET":
                res = requests.get(url, headers=headers, params=params, timeout=25)
            else:
                res = requests.post(url, headers=headers, json=json, timeout=35)
            
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                time.sleep(10) # 被擋了，休息久一點再回場
        except:
            time.sleep(2)
    return None

# 🌟 引擎 A：日曆雷達 (優化：使用全球市場代碼 US 以獲得最高權限)
def scan_calendar(origin, dest, month_str, cabin, s_date, e_date):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {
        "fromEntityId": origin,
        "toEntityId": dest,
        "departDate": month_str,
        "market": "US", # ⚡ 改用全球市場，避免被地區限制
        "currency": "TWD",
        "cabinClass": c_map[cabin]
    }
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    
    results = []
    today = date.today()
    if data and isinstance(data, dict) and data.get('data'):
        days = data['data'].get('days', [])
        for d in days:
            try:
                d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                if d_obj >= today and s_date <= d_obj <= e_date and d.get('price', 0) > 0:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d['price']})
            except: continue
    return results

# 🌟 引擎 B：100% 真實打包價精算
def fetch_exact_bundle(h_in, d1, h_out, d4, d2_o, d2_d, d2_date, d3_o, d3_d, d3_date, cabin, adults):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": c_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_o, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_o, "toEntityId": d2_d, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_o, "toEntityId": d3_d, "departDate": d3_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_d, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if data and data.get('data'):
        itins = data['data'].get('itineraries', [])
        for itin in itins:
            if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in itin.get('legs', [])):
                legs_info = []
                for l in itin['legs']:
                    seg = l.get('segments', [{}])[0]
                    bc = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                    legs_info.append(f"CI {seg.get('flightNumber')} ({bc}) | {l.get('departure','').split('T')[1][:5]}")
                return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": legs_info, "d1": d1, "d4": d4}
    return None

# --- UI ---
st.title("✈️ 華航外站獵殺器 v8.0 (終極保險版)")

with st.sidebar:
    st.header("⚙️ 設定")
    cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
    adults = st.number_input("大人", value=1, min_value=1)
    st.markdown("---")
    st.warning("如果一直樣本不足，請嘗試切換到『經濟艙』測試 API 是否正常。")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發 (TPE)", value="TPE")
    d2_dst = st.text_input("D2 抵達 (PRG)", value="PRG")
    d2_date = st.date_input("D2 去歐日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發 (FRA)", value="FRA")
    d3_dst = st.text_input("D3 抵達 (TPE)", value="TPE")
    d3_date = st.date_input("D3 回台日期", value=date(2026, 6, 25))

# --- 日期推算 ---
today = date.today()
d1_start = max(today, (d2_date - timedelta(days=62)).replace(day=1))
d1_end = d2_date
d4_start = d3_date
m4, y4 = (d3_date.month + 2, d3_date.year) if d3_date.month <= 10 else (d3_date.month - 10, d3_date.year + 1)
_, last_d = calendar.monthrange(y4, m4)
d4_end = date(y4, m4, last_d)

st.success(f"📅 獵殺區間：D1({d1_start}~{d1_end}) | D4({d4_start}~{d4_end})")

selected_hubs = st.multiselect("📍 選擇狙擊外站：", ["MNL", "BKK", "HKG", "KIX", "NRT", "ICN", "PUS", "SGN", "KUL", "FUK"], default=["MNL", "BKK", "KIX"])

if st.button("🚀 啟動獵殺", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 診斷日誌", expanded=True)
    
    def get_ms(s, e):
        ms = []
        curr = s.replace(day=1)
        while curr <= e:
            ms.append(curr.strftime("%Y-%m"))
            curr = (curr + timedelta(days=32)).replace(day=1)
        return list(set(ms))

    d1_m, d4_m = get_ms(d1_start, d1_end), get_months(d4_start, d4_end) # 這裡修正名稱
    d1_cands, d4_cands = [], []

    # 1. 雷達階段
    for hub in selected_hubs:
        msg.info(f"⚡ 正在探測 {hub}...")
        for m in d1_m:
            res = scan_calendar(hub, d2_org, m, cabin_choice, d1_start, d1_end)
            d1_cands.extend(res)
        for m in d4_m:
            res = scan_calendar(d3_dst, hub, m, cabin_choice, d4_start, d4_end)
            d4_cands.extend(res)
        debug.write(f"✅ {hub} 探測結束：去程找到 {len(d1_cands)} 點，回程找到 {len(d4_cands)} 點")

    if not d1_cands or not d4_cands:
        st.error("🚨 依舊樣本不足。這代表華航在此區間的『商務艙』暫無 API 報價，或您的 API 請求已被封鎖。")
    else:
        # 2. 精算階段
        msg.warning("🔥 正在獲取真實打包價...")
        final_results = []
        # 為了穩定，只取最便宜的各 2 個點
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:2]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:2]
        
        for d1, d4 in product(top_d1, top_d4):
            res = fetch_exact_bundle(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adults)
            if res: final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success("🎉 獵殺成功！")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} ➔ NT$ {r['total']:,}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 精算無結果。")
