import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面隱藏 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🌟 核心引擎：100% 真實打包精算 (含深度艙等字母解析)
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
        time.sleep(1.0) 
        res = requests.post(url, json=payload, headers=HEADERS, timeout=30).json()
        itins = res.get('data', {}).get('itineraries', [])
        
        for itin in itins:
            # 驗證：四段皆為華航 (CI)
            if all(leg.get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI' for leg in itin.get('legs', [])):
                leg_infos = []
                for leg in itin.get('legs', []):
                    # 🚀 強化艙等代碼抓取 (嘗試所有可能的 API 欄位)
                    seg = leg.get('segments', [{}])[0]
                    b_code = seg.get('bookingCode') or seg.get('segmentClass') or seg.get('fareCode') or "N/A"
                    leg_infos.append(f"CI {seg.get('flightNumber', '')} ({b_code}) | {leg.get('departure', '').split('T')[1][:5]}")
                
                return {"title": f"{hub_in} ➔ {hub_out}", "total": int(itin['price']['raw']), "legs": leg_infos}
    except: pass
    return None

# 🌟 雷達掃描與基準價查詢
def task_radar_scan(origin, dest, date, cabin_class):
    url = f"{BASE_URL}/flights/search-one-way"
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", 
              "cabinClass": "business" if cabin_class=="商務艙" else ("premiumeconomy" if cabin_class=="豪經艙" else "economy")}
    try:
        res = requests.get(url, headers=HEADERS, params=params, timeout=15).json()
        itins = res.get('data', {}).get('itineraries', [])
        for itin in itins:
            if itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [{}])[0].get('alternateId', '') == 'CI':
                return itin['price']['raw']
    except: pass
    return 999999

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
st.title("✈️ 華航外站獵殺器 (專業玩家修正版)")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("去程終點 (PRG)", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("回程起點 (FRA)", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=1)
with c2: children = st.number_input("兒童", value=0)
with c3: infants = st.number_input("嬰兒", value=0)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動極速獵殺模式", use_container_width=True):
    d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
    d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
    
    msg = st.empty()
    msg.info("📡 第一階段：掃描全亞洲 22 站雷達資料...")
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        in_futures = {executor.submit(task_radar_scan, hub, "TPE", d1_date, cabin_choice): hub for hub in all_hubs}
        out_futures = {executor.submit(task_radar_scan, "TPE", hub, d4_date, cabin_choice): hub for hub in all_hubs}
        base_future = executor.submit(task_long_haul_base, out_dest, in_origin, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), cabin_choice, adults, children, infants)
        
        in_found = [(in_futures[f], f.result()) for f in as_completed(in_futures) if f.result() < 999999]
        out_found = [(out_futures[f], f.result()) for f in as_completed(out_futures) if f.result() < 999999]
        base_long_price = base_future.result()

    if not in_found or not out_found:
        st.error("樣本不足，請更換日期！")
    else:
        top_in = [x[0] for x in sorted(in_found, key=lambda x: x[1])[:4]]
        top_out = [x[0] for x in sorted(out_found, key=lambda x: x[1])[:4]]
        
        msg.warning(f"🔥 第二階段：雷達鎖定！正在精算 16 組【{cabin_choice}】真實總價與艙等代碼...")
        
        results = []
        combos = list(product(top_in, top_out))
        with ThreadPoolExecutor(max_workers=5) as executor:
            精算任務 = [executor.submit(task_fetch_exact_price, h_in, h_out, out_dest, in_origin, d1_date, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), d4_date, cabin_choice, adults, children, infants) for h_in, h_out in combos]
            for f in as_completed(精算任務):
                res = f.result()
                if res:
                    # 🎯 邏輯修正：計算組合技是否真的省錢
                    diff = base_long_price - res["total"]
                    res["diff"] = diff
                    results.append(res)
        
        msg.empty()
        if results:
            st.success(f"🎉 獵殺完成！長程直飛原價：NT$ {base_long_price:,}")
            
            # 分成「省錢組合」與「加錢組合」
            sorted_res = sorted(results, key=lambda x: x['total'])
            
            for r in sorted_res:
                if r['diff'] > 0:
                    with st.expander(f"✅ 值得開票：{r['title']} ➔ 總價 NT$ {r['total']:,}"):
                        st.markdown(f"**🤑 此組合比直飛省下：<span style='color:green; font-size:20px'>NT$ {r['diff']:,}</span>**", unsafe_allow_html=True)
                        st.write("---")
                        st.write(f"1️⃣ {d1_date} | {r['legs'][0]}")
                        st.write(f"2️⃣ {date_out} | {r['legs'][1]}")
                        st.write(f"3️⃣ {date_in} | {r['legs'][2]}")
                        st.write(f"4️⃣ {d4_date} | {r['legs'][3]}")
                else:
                    with st.expander(f"❌ 不建議開票：{r['title']} ➔ 總價 NT$ {r['total']:,}"):
                        st.markdown(f"**⚠️ 此組合比直飛【貴了】：<span style='color:red; font-size:20px'>NT$ {abs(r['diff']):,}</span>**", unsafe_allow_html=True)
                        st.write("💡 建議：直接買台北直飛機票，或換個日期/外站再試。")
                        st.write("---")
                        st.write(f"1️⃣ {d1_date} | {r['legs'][0]}")
                        st.write(f"2️⃣ {date_out} | {r['legs'][1]}")
                        st.write(f"3️⃣ {date_in} | {r['legs'][2]}")
                        st.write(f"4️⃣ {d4_date} | {r['legs'][3]}")
        else:
            st.error("❌ 深度精算失敗，建議微調日期再試。")
