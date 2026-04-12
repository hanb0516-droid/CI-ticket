import streamlit as st
from datetime import datetime, timedelta
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 引擎 A：多點搜尋 (專門破解歐洲長程線 A進B出 真實票價)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_europe_main_legs(leg1_from, leg1_to, d1, leg2_from, leg2_to, d2, cabin_class, adults, children, infants):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-multi-city"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD",
        "adults": int(adults), "children": int(children), "infants": int(infants),
        "cabinClass": cabin_mapping[cabin_class], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": leg1_from, "toEntityId": leg1_to, "departDate": d1},
            {"fromEntityId": leg2_from, "toEntityId": leg2_to, "departDate": d2}
        ]
    }
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

    try:
        time.sleep(0.5)
        response = requests.post(url, json=payload, headers=headers, timeout=25)
        response.raise_for_status() 
        data = response.json()
        
        if not data.get('data') or not data['data'].get('itineraries'):
             return {"status": "❌ 查無航班", "total_price": 0, "legs": []}

        itinerary = data['data']['itineraries'][0]
        real_total_price = itinerary['price']['raw']
        
        flight_details = []
        for i in range(2):
            try:
                leg = itinerary['legs'][i]
                carriers = leg.get('carriers', {}).get('marketing', [])
                c_name = carriers[0].get('name', '華航') if carriers else '華航'
                f_num = leg.get('segments', [{}])[0].get('flightNumber', '')
                dep = leg.get('departure', '')
                if 'T' in dep: dep = dep.split('T')[1][:5]
                flight_details.append(f"{c_name} {f_num} | {dep} 出發")
            except:
                flight_details.append("無航班資訊")
                
        return {"status": "✅", "total_price": int(real_total_price), "legs": flight_details}
    except Exception as e:
        return {"status": f"❌ 錯誤", "total_price": 0, "legs": []}

# 🌟 引擎 B：單程搜尋 (專門探測亞洲外站的稅金與基礎票價)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asia_outer_legs(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", "cabinClass": cabin_mapping[cabin_class]}
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com"}

    try:
        time.sleep(0.5)
        response = requests.get(url, headers=headers, params=params, timeout=12)
        data = response.json()
        real_price = data['data']['itineraries'][0]['price']['raw']
        
        try:
            leg = data['data']['itineraries'][0]['legs'][0]
            c_name = leg.get('carriers', {}).get('marketing', [{}])[0].get('name', '華航')
            f_num = leg.get('segments', [{}])[0].get('flightNumber', '')
            dep = leg.get('departure', '')
            if 'T' in dep: dep = dep.split('T')[1][:5]
            f_info = f"{c_name} {f_num} | {dep} 出發"
        except:
            f_info = "無資訊"
            
        return {"base_price": int(real_price), "status": "✅", "info": f_info}
    except:
        return {"base_price": 0, "status": "❌", "info": ""}

def calc_family(base_price, adults, children, infants):
    return (base_price * adults) + (int(base_price * 0.75) * children) + (int(base_price * 0.10) * infants)

# --- App 介面 ---
st.title("✈️ 華航外站四段票神器 (混血雙引擎版)")

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
with c1: adults = st.number_input("大人", value=2)
with c2: children = st.number_input("兒童", value=1)
with c3: infants = st.number_input("嬰兒", value=1)

asia_hubs = ["FUK", "KUL", "BKK", "MNL", "NRT"]

if st.button("🚀 執行混血精算 (準確度最高)", use_container_width=True):
    with st.spinner('正在與華航系統核對 A進B出 真實價格，並掃描亞洲外站...'):
        results = []
        
        # 1. 先抓最難的：歐洲長程主段 (A進B出 真實全家總價)
        europe_main = fetch_europe_main_legs("TPE", out_dest, date_out.strftime("%Y-%m-%d"), in_origin, "TPE", date_in.strftime("%Y-%m-%d"), cabin_choice, adults, children, infants)
        
        if "❌" in europe_main['status']:
            st.error(f"⚠️ 歐洲長程段查無機票！這通常代表該日期的商務艙已售罄。")
        else:
            europe_total_price = europe_main['total_price']
            st.info(f"💶 已成功抓取歐洲長程 A進B出 真實全家總價：**NT$ {europe_total_price:,}**")
            
            # 2. 開始掃描外站短程線
            for hub in asia_hubs:
                d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
                d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
                
                s1 = fetch_asia_outer_legs(hub, "TPE", d1_date, cabin_choice)
                s4 = fetch_asia_outer_legs("TPE", hub, d4_date, cabin_choice)
                
                if "✅" in s1['status'] and "✅" in s4['status']:
                    f1_family = calc_family(s1['base_price'], adults, children, infants)
                    f4_family = calc_family(s4['base_price'], adults, children, infants)
                    
                    # 💡 四段合買演算法：長程票打 9 折優惠 + 短程票只收 15% 稅金
                    together_total = int(europe_total_price * 0.90 + (f1_family + f4_family) * 0.15)
                    separate_total = europe_total_price + f1_family + f4_family

                    details_text = [
                        f"第一段 **{d1_date}** | {hub} ✈️ TPE ({s1['info']})",
                        f"第二段 **{date_out.strftime('%Y-%m-%d')}** | TPE ✈️ {out_dest} ({europe_main['legs'][0]})",
                        f"第三段 **{date_in.strftime('%Y-%m-%d')}** | {in_origin} ✈️ TPE ({europe_main['legs'][1]})",
                        f"第四段 **{d4_date}** | TPE ✈️ {hub} ({s4['info']})"
                    ]

                    results.append({
                        "hub": hub, 
                        "together": together_total, 
                        "separate": separate_total, 
                        "savings": separate_total - together_total,
                        "miles": (4500 * 2 + 1000 * 2) * adults,
                        "details": details_text
                    })

            if results:
                top_results = sorted(results, key=lambda x: x['together'])
                st.success("🎉 精算完成！")
                
                for i, res in enumerate(top_results, 1):
                    with st.expander(f"🏆 第 {i} 名：{res['hub']} 起降 ➔ 四段合買預估 NT$ {res['together']:,}"):
                        st.markdown(f"**🔥 四段合買預估價：<span style='color:red; font-size:20px'>NT$ {res['together']:,}</span>**", unsafe_allow_html=True)
                        st.write(f"🛑 如果分開單買總價：NT$ {res['separate']:,}")
                        st.write(f"🤑 四段合買為您省下：**NT$ {res['savings']:,}**")
                        st.markdown("---")
                        st.markdown("**✈️ 實際航班明細：**")
                        for info in res['details']:
                            st.write(f"• {info}")
