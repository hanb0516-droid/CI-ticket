import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面美化 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🌟 核心：100% 真實打包精算 (含深度艙等代碼解析)
def task_fetch_exact_price(hub_in, hub_out, out_dest, in_origin, d1, d2, d3, d4, cabin_class, adults, children, infants):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_map[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": hub_in, "toEntityId": "TPE", "departDate": d1},
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3},
            {"fromEntityId": "TPE", "toEntityId": hub_out, "departDate": d4}
        ]
    }
    try:
        time.sleep(1.0) # 確保精算穩定性
        res = requests.post(url, json=payload, headers=HEADERS, timeout=30).json()
        itins = res.get('data', {}).get('itineraries', [])
        
        for itin in itins:
            # 嚴格驗證：四段皆為華航
            if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
                leg_infos = []
                for leg in itin.get('legs', []):
                    seg = leg.get('segments', [{}])[0]
                    # 🚀 深度解析艙等代碼 (Booking Code)
                    b_code = seg.get('bookingCode') or seg.get('booking_code') or seg.get('segmentClass') or seg.get('fareCode') or "N/A"
                    leg_infos.append(f"CI {seg.get('flightNumber', '')} ({b_code}) | {leg.get('departure', '').split('T')[1][:5]}")
                
                return {"title": f"【{hub_in} ➔ {hub_out}】", "total": int(itin['price']['raw']), "legs": leg_infos}
    except: pass
    return None

# 🌟 雷達掃描：增加穩定性與超時處理
def task_radar_scan(origin, dest, date, cabin_class):
    url = f"{BASE_URL}/flights/search-one-way"
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", 
              "cabinClass": "business" if cabin_class=="商務艙" else ("premiumeconomy" if cabin_class=="豪經艙" else "economy")}
    try:
        res = requests.get(url, headers=HEADERS, params=params, timeout=18).json()
        itins = res.get('data', {}).get('itineraries', [])
        for itin in itins:
            # 搜尋第一筆華航
            if itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI':
                return itin['price']['raw']
    except: pass
    return 999999

# 🌟 基準價：A進B出直飛價格
def task_long_haul_base(out_dest, in_origin, d2, d3, cabin_class, adults, children, infants):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_map[cabin_class], "flights": [
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3}
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

# --- 應用程式主介面 ---
st.title("✈️ 華航全亞洲獵殺器 (專業穩定版)")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=1)
with c2: children = st.number_input("兒童", value=0)
with c3: infants = st.number_input("嬰兒", value=0)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動深度獵殺模式", use_container_width=True):
    d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
    d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
    
    msg = st.empty()
    msg.info("📡 第一階段：正在穩定掃描亞洲 22 站雷達...")
    
    # 🎯 第一階段：穩定並行掃描 (適度控制連線數)
    with ThreadPoolExecutor(max_workers=8) as executor:
        in_futures = {executor.submit(task_radar_scan, hub, "TPE", d1_date, cabin_choice): hub for hub in all_hubs}
        out_futures = {executor.submit(task_radar_scan, "TPE", hub, d4_date, cabin_choice): hub for hub in all_hubs}
        base_future = executor.submit(task_long_haul_base, out_dest, in_origin, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), cabin_choice, adults, children, infants)
        
        in_found = [(in_futures[f], f.result()) for f in as_completed(in_futures) if f.result() < 999999]
        out_found = [(out_futures[f], f.result()) for f in as_completed(out_futures) if f.result() < 999999]
        base_long_price = base_future.result()

    st.write(f"📊 掃描報告：去程找到 {len(in_found)} 個起點，回程找到 {len(out_found)} 個終點。")

    if not in_found or not out_found:
        st.error("🚨 樣本不足！這代表雷達掃描時 API 全數超時或華航在這些日期暫無純位子。請稍後再按一次或微調日期。")
    else:
        # 篩選最有潛力的前 4 起點與前 4 終點
        top_in = [x[0] for x in sorted(in_found, key=lambda x: x[1])[:4]]
        top_out = [x[0] for x in sorted(out_found, key=lambda x: x[1])[:4]]
        
        msg.warning(f"🔥 第二階段：雷達已鎖定潛力點！正在精算 16 組【{cabin_choice}】真實總價與艙等代碼...")
        
        # 🎯 第二階段：精準並行精算
        results = []
        combos = list(product(top_in, top_out))
        with ThreadPoolExecutor(max_workers=6) as executor:
            精算任務 = [executor.submit(task_fetch_exact_price, h_in, h_out, out_dest, in_origin, d1_date, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), d4_date, cabin_choice, adults, children, infants) for h_in, h_out in combos]
            for f in as_completed(精算任務):
                res = f.result()
                if res:
                    diff = base_long_price - res["total"] if base_long_price > 0 else 0
                    res["diff"] = diff
                    results.append(res)
        
        msg.empty()
        if results:
            st.success(f"🎉 獵殺完成！長程直飛基準價 (A進B出)：NT$ {base_long_price:,}")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} ➔ 總價 NT$ {r['total']:,}"):
                    if r['diff'] > 0: st.write(f"🤑 組合技比直飛省下：**NT$ {r['diff']:,}**")
                    else: st.write(f"ℹ️ 組合技比直飛貴了 NT$ {abs(r['diff']):,}")
                    st.markdown("---")
                    st.write("**✈️ 實際航班與艙等代碼 (保證華航)：**")
                    st.write(f"1️⃣ {d1_date} | {r['legs'][0]}")
                    st.write(f"2️⃣ {date_out} | {r['legs'][1]}")
                    st.write(f"3️⃣ {date_in} | {r['legs'][2]}")
                    st.write(f"4️⃣ {d4_date} | {r['legs'][3]}")
        else:
            st.error("❌ 深度精算失敗。可能是華航官網在此日期的低價位子已被搶光。")
