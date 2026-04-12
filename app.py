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

# 🛠️ 工具函數：計算動態日期
def calculate_target_dates(d2, d3):
    # D1 邏輯：D2 往前推兩個整數月，抓 1 號
    d1_year = d2.year
    d1_month = d2.month - 2
    if d1_month <= 0:
        d1_month += 12
        d1_year -= 1
    d1 = date(d1_year, d1_month, 1)

    # D4 邏輯：D3 往後推兩個整數月，抓該月最後一天
    d4_year = d3.year
    d4_month = d3.month + 2
    if d4_month > 12:
        d4_month -= 12
        d4_year += 1
    last_day = calendar.monthrange(d4_year, d4_month)[1]
    d4 = date(d4_year, d4_month, last_day)
    
    return d1, d4

# 🌟 核心引擎：100% 真實打包精算
def task_fetch_exact_price(hub_in, hub_out, out_dest, in_origin, d1, d2, d3, d4, cabin_class, adults, children, infants):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_map[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": hub_in, "toEntityId": "TPE", "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2.strftime("%Y-%m-%d")},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3.strftime("%Y-%m-%d")},
            {"fromEntityId": "TPE", "toEntityId": hub_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    try:
        time.sleep(1.2) 
        res = requests.post(url, json=payload, headers=HEADERS, timeout=30).json()
        itins = res.get('data', {}).get('itineraries', [])
        for itin in itins:
            if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
                leg_infos = []
                for leg in itin.get('legs', []):
                    seg = leg.get('segments', [{}])[0]
                    b_code = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                    leg_infos.append(f"CI {seg.get('flightNumber', '')} ({b_code}) | {leg.get('departure', '').split('T')[1][:5]}")
                return {"title": f"{hub_in} ➔ {hub_out}", "total": int(itin['price']['raw']), "legs": leg_infos}
    except: pass
    return None

# 🌟 第一階段：穩定雷達
def task_radar_scan(origin, dest, date_obj, cabin_class):
    url = f"{BASE_URL}/flights/search-one-way"
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date_obj.strftime("%Y-%m-%d"), "adults": "1", "currency": "TWD", 
              "cabinClass": "business" if cabin_class=="商務艙" else ("premiumeconomy" if cabin_class=="豪經艙" else "economy")}
    try:
        time.sleep(0.5)
        res = requests.get(url, headers=HEADERS, params=params, timeout=18).json()
        itins = res.get('data', {}).get('itineraries', [])
        for itin in itins:
            if itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI':
                return itin['price']['raw']
    except: pass
    return 999999

# 🌟 基準價查詢
def task_long_haul_base(out_dest, in_origin, d2, d3, cabin_class, adults, children, infants):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_map[cabin_choice], "flights": [
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
st.title("✈️ 華航全亞洲獵殺器 (動態日期版)")

st.subheader("🗓️ 長程行程設定 (去程日期決定外站月份)")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期 (D2)", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期 (D3)", value=datetime(2026, 6, 25))

# 自動計算 D1 與 D4
d1_target, d4_target = calculate_target_dates(date_out, date_in)

st.success(f"📅 系統自動規劃：第一段 (D1) 鎖定 **{d1_target}** | 第四段 (D4) 鎖定 **{d4_target}**")

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=1)
with c2: children = st.number_input("兒童", value=0)
with c3: infants = st.number_input("嬰兒", value=0)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動深度獵殺模式", use_container_width=True):
    msg = st.empty()
    msg.info(f"📡 第一階段：正在針對 {d1_target} 與 {d4_target} 進行 22 站雷達掃描...")
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        in_futures = {executor.submit(task_radar_scan, hub, "TPE", d1_target, cabin_choice): hub for hub in all_hubs}
        out_futures = {executor.submit(task_radar_scan, "TPE", hub, d4_target, cabin_choice): hub for hub in all_hubs}
        base_future = executor.submit(task_long_haul_base, out_dest, in_origin, date_out, date_in, cabin_choice, adults, children, infants)
        
        in_found = [(in_futures[f], f.result()) for f in as_completed(in_futures) if f.result() < 999999]
        out_found = [(out_futures[f], f.result()) for f in as_completed(out_futures) if f.result() < 999999]
        base_long_price = base_future.result()

    if not in_found or not out_found:
        st.error(f"🚨 樣本不足！華航在 {d1_target.month}月 或 {d4_target.month}月 可能尚未放票或已售罄。")
    else:
        top_in = [x[0] for x in sorted(in_found, key=lambda x: x[1])[:4]]
        top_out = [x[0] for x in sorted(out_found, key=lambda x: x[1])[:4]]
        
        msg.warning(f"🔥 第二階段：雷達已鎖定！正在為您精算 16 組【{cabin_choice}】真實總價與艙等字母...")
        
        results = []
        combos = list(product(top_in, top_out))
        with ThreadPoolExecutor(max_workers=5) as executor:
            精算任務 = [executor.submit(task_fetch_exact_price, h_in, h_out, out_dest, in_origin, d1_target, date_out, date_in, d4_target, cabin_choice, adults, children, infants) for h_in, h_out in combos]
            for f in as_completed(精算任務):
                res = f.result()
                if res:
                    res["diff"] = base_long_price - res["total"]
                    results.append(res)
        
        msg.empty()
        if results:
            st.success(f"🎉 獵殺完成！直飛基準價：NT$ {base_long_price:,}")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                is_saving = r['diff'] > 0
                color = "green" if is_saving else "red"
                with st.expander(f"{r['title']} ➔ 總價 NT$ {r['total']:,}"):
                    st.markdown(f"**💰 比直飛{'省下' if is_saving else '多花'}：<span style='color:{color}; font-size:20px'>NT$ {abs(r['diff']):,}</span>**", unsafe_allow_html=True)
                    st.write("---")
                    for i, leg in enumerate(r['legs'], 1):
                        st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 深度精算失敗。可能該日期艙位已售罄。")
