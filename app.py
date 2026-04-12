import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time

# --- 介面隱藏 ---
st.set_page_config(page_title="華航聯程獵殺器 vFinal", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"

# 🛡️ 穩定型請求 (加入 2.2 秒強效冷卻)
def stable_request(url, method="GET", params=None, json=None):
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}
    for i in range(3):
        try:
            time.sleep(2.2) # 絕對安全閾值，防止 API 斷電
            if method == "GET":
                res = requests.get(url, headers=headers, params=params, timeout=25)
            else:
                res = requests.post(url, headers=headers, json=json, timeout=35)

            if res.status_code == 200:
                data = res.json()
                if data and data.get('data'): return data
            elif res.status_code == 429:
                time.sleep(10)
        except:
            time.sleep(2)
    return None

# 🌟 引擎 A：日期處理
def get_safe_months(s_date, e_date):
    ms = []
    curr = s_date.replace(day=1)
    while curr <= e_date:
        ms.append(curr.strftime("%Y-%m"))
        if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
        else: curr = curr.replace(month=curr.month+1)
    return sorted(list(set(ms)))

# 🌟 引擎 B：日曆探路
def scan_calendar(origin, dest, month_str, cabin, s_limit, e_limit):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": c_map[cabin], "market": "US"}
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    results = []
    today = date.today()
    if data and data.get('data'):
        days = data['data'].get('days', [])
        for d in days:
            try:
                d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                if d_obj >= today and s_limit <= d_obj <= e_limit:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d.get('price', 999999)})
            except: continue
    return results

# 🌟 引擎 C：直飛基準價 (已加回)
def fetch_base_price(d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": c_map[cabin],
        "flights": [
            {"fromEntityId": d2_o, "toEntityId": d2_d, "departDate": d2_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_o, "toEntityId": d3_d, "departDate": d3_dt.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if data and data.get('data'):
        try: return int(data['data']['itineraries'][0]['price']['raw'])
        except: return 0
    return 0

# 🌟 引擎 D：打包精算
def fetch_bundle_price(h_in, d1, h_out, d4, d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": c_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_o, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_o, "toEntityId": d2_d, "departDate": d2_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_o, "toEntityId": d3_d, "departDate": d3_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_d, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if data and data.get('data'):
        itins = data['data'].get('itineraries', [])
        for itin in itins:
            if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in itin.get('legs', [])):
                legs_info = [f"CI {l['segments'][0]['flightNumber']} ({l['segments'][0].get('bookingCode','N/A')}) | {l['departure'].split('T')[1][:5]}" for l in itin['legs']]
                return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": legs_info, "d1": d1, "d4": d4}
    return None

# --- UI ---
st.title("✈️ 華航外站聯程獵殺器 (最終無火花版)")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市 (TPE)", value="TPE")
    d2_dst = st.text_input("D2 抵達城市 (PRG)", value="PRG")
    d2_date = st.date_input("D2 日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市 (FRA)", value="FRA")
    d3_dst = st.text_input("D3 抵達城市 (TPE)", value="TPE")
    d3_date = st.date_input("D3 日期", value=date(2026, 6, 25))

# 📅 自動校正日期
today = date.today()
d1_start = max(today + timedelta(days=1), (d2_date - timedelta(days=62)).replace(day=1))
d4_end = date(d3_date.year + (1 if d3_date.month > 10 else 0), (d3_date.month + 2) % 12 or 12, 1)
_, last_d = calendar.monthrange(d4_end.year, d4_end.month)
d4_end = d4_end.replace(day=last_d)

st.success(f"📡 獵殺區間：D1({d1_start}~{d2_date}) | D4({d3_date}~{d4_end})")

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])
adult_count = st.number_input("大人人數", value=1, min_value=1)
selected_hubs = st.multiselect("📍 選擇掃描外站：", ["PUS", "ICN", "KUL", "BKK", "MNL", "HKG", "NRT", "FUK"], default=["PUS", "ICN", "KUL"])

if st.button("🚀 啟動聯程獵殺", use_container_width=True):
    if not selected_hubs:
        st.error("請至少選擇一個外站！")
    else:
        msg = st.empty()
        debug = st.expander("🛠️ 診斷日誌", expanded=True)

        d1_m = get_safe_months(d1_start, d2_date)
        d4_m = get_safe_months(d3_date, d4_end)
        d1_cands, d4_cands = [], []

        for hub in selected_hubs:
            msg.info(f"⚡ 正在探測 {hub}...")
            for m in d1_m: d1_cands.extend(scan_calendar(hub, d2_org, m, cabin_choice, d1_start, d2_date))
            for m in d4_m: d4_cands.extend(scan_calendar(d3_dst, hub, m, cabin_choice, d3_date, d4_end))

        # 🛡️ 容錯保底機制 (使用選擇清單的第一個城市，不再強插 MNL)
        fallback_hub = selected_hubs[0]
        if not d1_cands: d1_cands.append({"hub": fallback_hub, "day": d1_start, "price": 999999})
        if not d4_cands: d4_cands.append({"hub": fallback_hub, "day": d4_end - timedelta(days=5), "price": 999999})

        msg.warning("🔥 正在獲取直飛基準價與真實聯程價...")
        
        # 抓基準價
        base_p = fetch_base_price(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count)

        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:2]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:2]

        results = []
        combos = list(product(top_d1, top_d4))
        
        # 循序執行，附帶進度條
        progress_bar = st.progress(0)
        for idx, (d1, d4) in enumerate(combos):
            progress_bar.progress((idx + 1) / len(combos), text=f"精算中：{d1['hub']} ➔ {d4['hub']} ({idx+1}/{len(combos)})")
            res = fetch_bundle_price(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count)
            if res:
                res["diff"] = base_p - res["total"] if base_p > 0 else 0
                results.append(res)
        
        progress_bar.empty()
        msg.empty()
        
        if results:
            st.success(f"🎉 獵殺成功！長程直飛基準價為：NT$ {base_p:,}")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                is_save = r['diff'] > 0
                color = "green" if is_save else "red"
                with st.expander(f"{'✅' if is_save else '⚠️'} {r['title']} | {r['d1']} & {r['d4']} ➔ NT$ {r['total']:,}"):
                    if base_p > 0:
                        st.markdown(f"**💰 比直飛{'省下' if is_save else '多花'}：<span style='color:{color}; font-size:20px'>NT$ {abs(r['diff']):,}</span>**", unsafe_allow_html=True)
                    st.write("---")
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 聯程精算失敗。這代表華航不給這組日期的聯程優惠，或位子已售罄。")
