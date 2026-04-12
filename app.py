import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面美化 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛠️ 自動推算月份邏輯
def get_suggested_dates(d2, d3):
    # D1: D2 前兩個月 1 號
    d1_year, d1_month = (d2.year, d2.month - 2) if d2.month > 2 else (d2.year - 1, d2.month + 10)
    d1 = date(d1_year, d1_month, 1)
    # D4: D3 後兩個月最後一天
    d4_year, d4_month = (d3.year, d3.month + 2) if d3.month <= 10 else (d3.year + 1, d3.month - 10)
    last_day = calendar.monthrange(d4_year, d4_month)[1]
    d4 = date(d4_year, d4_month, last_day)
    return d1, d4

# 🌟 核心：100% 真實精算
def task_fetch_exact_price(h_in, h_out, out_dest, in_origin, d1, d2, d3, d4, cabin_class, adults, children, infants):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_map[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": "TPE", "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2.strftime("%Y-%m-%d")},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3.strftime("%Y-%m-%d")},
            {"fromEntityId": "TPE", "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    try:
        time.sleep(1.2)
        res = requests.post(url, json=payload, headers=HEADERS, timeout=30).json()
        itins = res.get('data', {}).get('itineraries', [])
        for itin in itins:
            if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
                leg_infos = [f"CI {l.get('segments', [{}])[0].get('flightNumber')} ({l.get('segments', [{}])[0].get('bookingCode') or 'N/A'}) | {l.get('departure','').split('T')[1][:5]}" for l in itin.get('legs', [])]
                return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": leg_infos}
    except: pass
    return None

# 🌟 雷達快掃
def task_radar_scan(origin, dest, date_obj, cabin_class):
    url = f"{BASE_URL}/flights/search-one-way"
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date_obj.strftime("%Y-%m-%d"), "adults": "1", "currency": "TWD", 
              "cabinClass": "business" if cabin_class=="商務艙" else ("premiumeconomy" if cabin_class=="豪經艙" else "economy")}
    try:
        time.sleep(0.5)
        res = requests.get(url, headers=HEADERS, params=params, timeout=15).json()
        itins = res.get('data', {}).get('itineraries', [])
        for itin in itins:
            if itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI':
                return itin['price']['raw']
    except: pass
    return 999999

# 🌟 基準價
def task_long_haul_base(out_dest, in_origin, d2, d3, cabin_class, adults, children, infants):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_map[cabin_class], "flights": [
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2.strftime("%Y-%m-%d")},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3.strftime("%Y-%m-%d")}
        ]
    }
    try:
        res = requests.post(url, json=payload, headers=HEADERS, timeout=25).json()
        itins = res.get('data', {}).get('itineraries', [])
        for itin in itins:
            if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
                return int(itin['price']['raw'])
    except: pass
    return 0

# --- App 介面 ---
st.title("✈️ 華航全亞洲獵殺器 (3.0 專業版)")

st.subheader("🗓️ 核心行程與日期邏輯")
c_d2, c_d3 = st.columns(2)
with c_d2:
    out_dest = st.text_input("歐洲去程終點", value="PRG")
    d2_val = st.date_input("去歐洲日期 (D2)", value=datetime(2026, 6, 11))
with c_d3:
    in_origin = st.text_input("歐洲回程起點", value="FRA")
    d3_val = st.date_input("回台灣日期 (D3)", value=datetime(2026, 6, 25))

# 執行自動月份建議
s_d1, s_d4 = get_suggested_dates(d2_val, d3_val)

st.markdown("---")
st.write("💡 **外站日期建議 (可手動調整以利雷達搜尋)：**")
c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_val = st.date_input("第一段外站出發 (D1)", value=s_d1)
with c_d4:
    d4_val = st.date_input("第四段飛回外站 (D4)", value=s_d4)

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=1)
with c2: children = st.number_input("兒童", value=0)
with c3: infants = st.number_input("嬰兒", value=0)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動深度獵殺模式", use_container_width=True):
    msg = st.empty()
    msg.info(f"📡 階段一：正在掃描 {d1_val} 與 {d4_val} 的 22 站雷達資料...")
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        in_futures = {executor.submit(task_radar_scan, hub, "TPE", d1_val, cabin_choice): hub for hub in all_hubs}
        out_futures = {executor.submit(task_radar_scan, "TPE", hub, d4_val, cabin_choice): hub for hub in all_hubs}
        base_future = executor.submit(task_long_haul_base, out_dest, in_origin, d2_val, d3_val, cabin_choice, adults, children, infants)
        
        in_found = [(in_futures[f], f.result()) for f in as_completed(in_futures) if f.result() < 999999]
        out_found = [(out_futures[f], f.result()) for f in as_completed(out_futures) if f.result() < 999999]
        base_price = base_future.result()

    # 📊 診斷報告
    st.write(f"📈 雷達報告：{d1_val} 找到 {len(in_found)} 站 | {d4_val} 找到 {len(out_found)} 站")
    
    if not in_found or not out_found:
        st.error(f"🚨 樣本不足！華航在 **{d1_val if not in_found else d4_val}** 當天可能無機位。建議：手動將上方日期微調 +/- 1 天再試！")
    else:
        top_in = [x[0] for x in sorted(in_found, key=lambda x: x[1])[:4]]
        top_out = [x[0] for x in sorted(out_found, key=lambda x: x[1])[:4]]
        
        msg.warning("🔥 階段二：雷達鎖定！正在為您精算 100% 真實報價與艙等字母...")
        
        results = []
        combos = list(product(top_in, top_out))
        with ThreadPoolExecutor(max_workers=5) as executor:
            tasks = [executor.submit(task_fetch_exact_price, hi, ho, out_dest, in_origin, d1_val, d2_val, d3_val, d4_val, cabin_choice, adults, children, infants) for hi, ho in combos]
            for f in as_completed(tasks):
                res = f.result()
                if res:
                    res["diff"] = base_price - res["total"]
                    results.append(res)
        
        msg.empty()
        if results:
            st.success(f"🎉 獵殺完成！直飛基準價：NT$ {base_price:,}")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                is_save = r['diff'] > 0
                icon = "✅ 值得開票" if is_save else "❌ 不建議"
                with st.expander(f"{icon} | {r['title']} ➔ 總價 NT$ {r['total']:,}"):
                    st.write(f"{'🤑 省下' if is_save else '⚠️ 多花'}：NT$ {abs(r['diff']):,}")
                    st.write("---")
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 深度精算失敗，該組合可能已售罄。")
