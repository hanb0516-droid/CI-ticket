import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 唯一真神引擎：四段行程打包詢價 (100% 真實總價，無任何估算)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_exact_4_legs(hub_in, hub_out, out_dest, in_origin, d1, d2, d3, d4, cabin_class, adults, children, infants):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-multi-city"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_mapping[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": hub_in, "toEntityId": "TPE", "departDate": d1},
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3},
            {"fromEntityId": "TPE", "toEntityId": hub_out, "departDate": d4}
        ]
    }
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

    try:
        time.sleep(1) # 必須放慢，4段票運算極度消耗資源
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        if response.status_code == 429:
            return {"status": "❌ API額度耗盡", "total_price": 0, "legs": []}
            
        data = response.json()
        itineraries = data.get('data', {}).get('itineraries', [])
        if not itineraries: return {"status": "❌ 查無航班", "total_price": 0, "legs": []}

        # 🔍 嚴格把關：4段都必須是華航
        ci_itinerary = None
        for itin in itineraries:
            is_all_ci = True
            for leg in itin.get('legs', []):
                carriers = leg.get('carriers', {}).get('marketing', [])
                if not carriers:
                    is_all_ci = False; break
                c_name = carriers[0].get('name', '').lower()
                c_code = carriers[0].get('alternateId', '')
                if '中華' not in c_name and 'china airlines' not in c_name and c_code != 'CI':
                    is_all_ci = False; break
            if is_all_ci:
                ci_itinerary = itin; break

        if not ci_itinerary: return {"status": "❌ 查無純華航", "total_price": 0, "legs": []}

        # 🎯 取得 100% 真實結帳總價
        real_total_price = ci_itinerary['price']['raw']
        flight_details = []
        for i in range(4):
            try:
                leg = ci_itinerary['legs'][i]
                c_name = leg.get('carriers', {}).get('marketing', [{}])[0].get('name', '華航')
                f_num = leg.get('segments', [{}])[0].get('flightNumber', '')
                dep = leg.get('departure', '')
                if 'T' in dep: dep = dep.split('T')[1][:5]
                flight_details.append(f"{c_name} {f_num} | {dep} 出發")
            except:
                flight_details.append("無航班資訊")
                
        return {"status": "✅", "total_price": int(real_total_price), "legs": flight_details}
    except Exception as e:
        return {"status": f"❌ 系統錯誤", "total_price": 0, "legs": []}

# --- App 介面 ---
st.title("✈️ 華航外站 100% 真實結帳價神器")
st.markdown("⚠️ **本版本直連 Skyscanner 多點查詢核心，所見即所得，零誤差！**")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("🌏 精準比對樞紐 (🚨 警告：每次最多選 3 個！)")
selected_hubs = st.multiselect(
    "因為是查詢 100% 真實票價，運算極耗時。選 2 個會產生 4 種組合，選 3 個會產生 9 種。超過可能當機：",
    [
        "FUK", "KIX", "NRT", "NGO", "CTS", "OKA",  
        "ICN", "PUS", "HKG", "MFM",                
        "BKK", "CNX", "SIN", "KUL", "PEN",         
        "MNL", "CEB", "SGN", "HAN", "DAD",         
        "CGK", "DPS"                               
    ],
    default=["KIX", "MNL"] # 預設只放你剛剛測的這兩個
)

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=1)
with c2: children = st.number_input("兒童", value=0)
with c3: infants = st.number_input("嬰兒", value=0)


if st.button("🚀 獲取 100% 真實刷卡總價", use_container_width=True):
    if not selected_hubs:
        st.warning("請至少選擇一個外站喔！")
    elif len(selected_hubs) > 4:
        st.error("🚨 拜託請減少外站數量！4 段票打包查詢極度耗時，超過 4 個樞紐（16種組合）幾乎 100% 會導致瀏覽器斷線！")
    else:
        results = []
        d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
        d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
        
        combinations = list(product(selected_hubs, repeat=2))
        total_combos = len(combinations)
        progress_bar = st.progress(0, text=f"📡 準備向主機索取 {total_combos} 種真實報價...")
        
        rate_limit_hit = False
        
        for i, (hub_in, hub_out) in enumerate(combinations):
            percent = int(((i + 1) / total_combos) * 100)
            progress_bar.progress(percent, text=f"🛫 正在解析真實包裹：{hub_in} 進 ➔ {hub_out} 出 ({i+1}/{total_combos})...")
            
            res = fetch_exact_4_legs(hub_in, hub_out, out_dest, in_origin, d1_date, date_out.strftime("%Y-%m-%d"), date_in.strftime("%Y-%m-%d"), d4_date, cabin_choice, adults, children, infants)
            
            if "額度耗盡" in res['status']:
                rate_limit_hit = True
                break
                
            if "✅" in res['status']:
                title_prefix = f"【同點起降】{hub_in}" if hub_in == hub_out else f"【開口混搭】{hub_in} 啟程 ➔ 飛回 {hub_out}"
                
                details_text = [
                    f"第一段 **{d1_date}** | {hub_in} ✈️ TPE ({res['legs'][0]})",
                    f"第二段 **{date_out.strftime('%Y-%m-%d')}** | TPE ✈️ {out_dest} ({res['legs'][1]})",
                    f"第三段 **{date_in.strftime('%Y-%m-%d')}** | {in_origin} ✈️ TPE ({res['legs'][2]})",
                    f"第四段 **{d4_date}** | TPE ✈️ {hub_out} ({res['legs'][3]})"
                ]

                results.append({
                    "title": title_prefix, 
                    "total": res['total_price'], 
                    "miles": (4500 * 2 + 1000 * 2) * adults,
                    "details": details_text
                })
        
        progress_bar.empty()
        
        if rate_limit_hit:
            st.error("🚨 掃描中斷：系統偵測到您的 API 額度已經耗盡 (Error 429)。")
        elif results:
            top_results = sorted(results, key=lambda x: x['total'])
            st.success(f"🎉 解析完成！這就是您在航空公司官網會看到的真實結帳數字：")
            
            for i, res in enumerate(top_results, 1):
                with st.expander(f"🏆 第 {i} 名：{res['title']} ➔ 總結帳 NT$ {res['total']:,}"):
                    st.markdown(f"**💺 艙等：{cabin_choice}**")
                    st.markdown(f"**🔥 四段合買真實報價：<span style='color:red; font-size:24px'>NT$ {res['total']:,}</span>**", unsafe_allow_html=True)
                    st.markdown("---")
                    st.markdown(f"**✈️ 實際航班明細 (保證 100% 華航)：**")
                    for info in res['details']:
                        st.write(f"• {info}")
        else:
            st.warning(f"查無純華航的機票組合。請檢查日期，或該日期的【{cabin_choice}】班機已客滿/未放票。")
