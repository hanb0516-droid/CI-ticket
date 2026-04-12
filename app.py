import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 核心資料抓取：支援全亞洲航點掃描
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_base_flight_data(origin, dest, date, cabin_class):
    # 建議使用您升級後的 API Key
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    params = {
        "fromEntityId": origin, 
        "toEntityId": dest, 
        "departDate": date, 
        "adults": "1", 
        "currency": "TWD", 
        "cabinClass": cabin_mapping[cabin_class]
    }
    
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "flights-sky.p.rapidapi.com"
    }

    try:
        # 付費版可稍微縮短延遲以加快速度
        time.sleep(0.3) 
        response = requests.get(url, headers=headers, params=params, timeout=12)
        response.raise_for_status() 
        data = response.json()
        real_price = data['data']['itineraries'][0]['price']['raw']
        return {"base_price": int(real_price), "status": "✅"}
    except:
        return {"base_price": 999999, "status": "❌"} # 查不到則給予高價以排除

def calculate_family_price(base_price, adults, children, infants):
    total = (base_price * adults) + (int(base_price * 0.75) * children) + (int(base_price * 0.10) * infants)
    return total

# --- App 介面 ---
st.title("✈️ 華航全亞洲外站掃描器 (Pro)")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

# 🌏 全亞洲主要樞紐清單 (取消手動限制，自動掃描)
asia_hubs = [
    "NRT", "KIX", "NGO", "FUK", "CTS", "OKA",  # 日本
    "ICN", "PVG", "SHA", "PEK", "HKG", "MFM",  # 韓、中、港澳
    "BKK", "SIN", "KUL", "MNL", "SGN", "HAN",  # 東南亞
    "CGK", "DPS", "PEN", "CNX"                 # 其他熱門點
]

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=2)
with c2: children = st.number_input("兒童 (如 Hayden)", value=1)
with c3: infants = st.number_input("嬰兒", value=1)

if st.button("🚀 執行全球/全亞洲最低價精算", use_container_width=True):
    with st.spinner('正在分析全亞洲所有可能的起訖點組合...'):
        results = []
        # 固定長程主航段價錢 (先查一次省額度)
        s2 = fetch_base_flight_data("TPE", out_dest, date_out.strftime("%Y-%m-%d"), cabin_choice)
        s3 = fetch_base_flight_data(in_origin, "TPE", date_in.strftime("%Y-%m-%d"), cabin_choice)
        
        # 只針對第一段與第四段進行全亞洲交叉掃描
        for hub in asia_hubs:
            d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
            d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
            
            s1 = fetch_base_flight_data(hub, "TPE", d1_date, cabin_choice)
            s4 = fetch_base_flight_data("TPE", hub, d4_date, cabin_choice)
            
            if s1['status'] == "✅" and s4['status'] == "✅":
                f1 = calculate_family_price(s1['base_price'], adults, children, infants)
                f2 = calculate_family_price(s2['base_price'], adults, children, infants)
                f3 = calculate_family_price(s3['base_price'], adults, children, infants)
                f4 = calculate_family_price(s4['base_price'], adults, children, infants)
                
                together_total = int((f2 + f3) * 0.85 + (f1 + f4) * 0.15)
                results.append({"hub": hub, "total": together_total, "p1": f1, "p4": f4})

        top_5 = sorted(results, key=lambda x: x['total'])[:5]
        
        st.success(f"🎉 掃描完成！找到全亞洲前 5 名最便宜的外站組合：")
        for i, res in enumerate(top_5, 1):
            with st.expander(f"🏆 第 {i} 名：{res['hub']} 起降 ➔ 總價 NT$ {res['total']:,}"):
                st.write(f"第一段 {res['hub']} ✈️ TPE: NT$ {res['p1']:,}")
                st.write(f"第四段 TPE ✈️ {res['hub']}: NT$ {res['p4']:,}")
                st.write("長程段 (PRG/FRA) 票價已包含於總價中。")

st.info("💡 專業提示：全亞洲掃描會產生約 50-80 次 API 呼叫，適合 Pro 訂閱用戶使用。")
