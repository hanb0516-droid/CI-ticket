import streamlit as st
from datetime import datetime, timedelta
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 終極引擎：多個城市打包搜尋 (真實開票總價)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_multi_city_flights(hub, out_dest, in_origin, d1, d2, d3, d4, cabin_class, adults, children, infants):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-multi-city"
    
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    # 按照 API 規定的 JSON 格式打包 4 段票與所有乘客
    payload = {
        "market": "TW",
        "locale": "zh-TW",
        "currency": "TWD",
        "adults": int(adults),
        "children": int(children),
        "infants": int(infants),
        "cabinClass": cabin_mapping[cabin_class],
        "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": hub, "toEntityId": "TPE", "departDate": d1},
            {"fromEntityId": "TPE", "toEntityId": out_dest, "departDate": d2},
            {"fromEntityId": in_origin, "toEntityId": "TPE", "departDate": d3},
            {"fromEntityId": "TPE", "toEntityId": hub, "departDate": d4}
        ]
    }
    
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "flights-sky.p.rapidapi.com",
        "Content-Type": "application/json"
    }

    try:
        time.sleep(1) # 等待 1 秒避免被擋
        # 注意：這裡改用 requests.post，並設定 timeout 為 30 秒讓長程商務艙有時間跑
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status() 
        data = response.json()
        
        if not data.get('data') or not data['data'].get('itineraries'):
             return {"status": "❌ 查無航班或售罄", "total_price": 0, "legs": []}

        # 🎯 抓取真實的「全家總結帳金額」
        itinerary = data['data']['itineraries'][0]
        real_total_price = itinerary['price']['raw']
        
        # 🎯 依序抓取 4 段航班的明細
        flight_details = []
        for i in range(4):
            try:
                leg = itinerary['legs'][i]
                carriers = leg.get('carriers', {}).get('marketing', [])
                carrier_name = carriers[0].get('name', '中華航空') if carriers else '中華航空'
                flight_number = leg.get('segments', [{}])[0].get('flightNumber', '')
                dep_time = leg.get('departure', '')
                if 'T' in dep_time:
                    dep_time = dep_time.split('T')[1][:5]
                flight_details.append(f"{carrier_name} {flight_number} | {dep_time} 出發")
            except:
                flight_details.append("無詳細航班資訊")
                
        miles = (4500 * 2 + 1000 * 2) * adults # 預估 2長2短 的總里程
        return {"status": "✅ 成功", "total_price": int(real_total_price), "legs": flight_details, "miles": miles}
        
    except requests.exceptions.Timeout:
        return {"status": "❌ 連線超時", "total_price": 0, "legs": []}
    except Exception as e:
        return {"status": f"❌ 系統錯誤", "total_price": 0, "legs": []}


# --- App 介面 ---
st.title("✈️ 華航外站四段票神器 (終極完全體)")
st.markdown("🔥 **100% 抓取 Skyscanner 多點搜尋真實開票總價**")

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

# 🌏 預設測這 5 個亞洲最強樞紐
test_hubs = ["FUK", "KUL", "BKK", "MNL", "NRT"] 

if st.button("🚀 執行多點搜尋 (獲取真實家庭總價)", use_container_width=True):
    with st.spinner('正在打包 4 段航班向系統報價... (每個外站約需 15~20 秒)'):
        results = []
        
        for hub in test_hubs:
            d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
            d2_date = date_out.strftime("%Y-%m-%d")
            d3_date = date_in.strftime("%Y-%m-%d")
            d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
            
            # 發送多點搜尋請求
            res = fetch_multi_city_flights(
                hub, out_dest, in_origin, 
                d1_date, d2_date, d3_date, d4_date, 
                cabin_choice, adults, children, infants
            )
            
            if "✅" in res['status']:
                details_text = [
                    f"第一段 **{d1_date}** | {hub} ✈️ TPE ({res['legs'][0]})",
                    f"第二段 **{d2_date}** | TPE ✈️ {out_dest} ({res['legs'][1]})",
                    f"第三段 **{d3_date}** | {in_origin} ✈️ TPE ({res['legs'][2]})",
                    f"第四段 **{d4_date}** | TPE ✈️ {hub} ({res['legs'][3]})"
                ]

                results.append({
                    "hub": hub, 
                    "total": res['total_price'], 
                    "miles": res['miles'],
                    "details": details_text
                })

        if results:
            # 依照真實總價進行排序
            top_results = sorted(results, key=lambda x: x['total'])
            st.success(f"🎉 報價完成！這就是您 {adults}大{children}小{infants}嬰 的真實刷卡總價：")
            
            for i, res in enumerate(top_results, 1):
                with st.expander(f"🏆 第 {i} 名：{res['hub']} 起降 ➔ 總結帳 NT$ {res['total']:,}"):
                    st.markdown(f"**🔥 真實開票總價：<span style='color:red; font-size:20px'>NT$ {res['total']:,}</span>**", unsafe_allow_html=True)
                    st.write(f"📈 預估累積華夏哩程：{res['miles']:,} 哩")
                    st.markdown("---")
                    st.markdown("**✈️ 實際航班明細：**")
                    for info in res['details']:
                        st.write(f"• {info}")
        else:
            st.error("⚠️ 掃描完畢，所有外站都遇到查無機票或連線超時的狀況。這通常代表該日期商務艙已完全售罄，或 API 仍在維護中。")
