import streamlit as st
import random
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 快取記憶：查過的機票會記住 1 小時，幫你狂省 API 免費額度！
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_base_flight_data(origin, dest, date, cabin_class):
    time.sleep(1) # 煞車機制
    
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    # 使用新 API 專屬的參數名稱
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
        response = requests.get(url, headers=headers, params=params, timeout=12)
        response.raise_for_status() 
        data = response.json()
        
        # 🎯 根據剛剛診斷工具抓到的精準路徑來提取價格
        real_price = data['data']['itineraries'][0]['price']['raw']
        
        miles = 4500 if "PRG" in [origin, dest] or "FRA" in [origin, dest] or "ZRH" in [origin, dest] else 1000
        return {"base_price": int(real_price), "miles": miles, "status": "✅ API 即時報價"}
        
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg:
            reason = "本月免費額度用盡"
        elif "IndexError" in str(type(e)) or "TypeError" in str(type(e)):
            reason = "該日無航班或售罄"
        else:
            reason = "連線異常"

        # 備案模擬價格
        multiplier = 1 if cabin_class == "經濟艙" else (1.8 if cabin_class == "豪經艙" else 3.5)
        long_haul_price = random.randint(18000, 25000) * multiplier
        short_haul_price = random.randint(3500, 7000) * multiplier
        base = int(long_haul_price if len(origin+dest)>6 else short_haul_price)
        
        return {"base_price": base, "miles": 1000, "status": f"⚠️ 系統模擬 ({reason})"}

def calculate_family_price(base_price, adults, children, infants):
    child_price = int(base_price * 0.75)  
    infant_price = int(base_price * 0.10) 
    total = (base_price * adults) + (child_price * children) + (infant_price * infants)
    return total

# --- App 介面 ---
st.title("✈️ 華航外站四段票神器 (終極版)")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["經濟艙", "豪經艙", "商務艙"])

# 🛡️ 新增外站選擇器，保護 API 額度
st.subheader("🌏 外站起降點選擇 (省額度必備)")
selected_outstations = st.multiselect(
    "選擇你想測試的外站 (選越多算越久，越耗額度)：",
    ["FUK", "KUL", "BKK", "MNL", "NRT", "KIX"],
    default=["FUK"] # 預設只跑福岡，省額度
)

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=2, min_value=1)
with c2: children = st.number_input("兒童", value=1, min_value=0)
with c3: infants = st.number_input("嬰兒", value=1, min_value=0)

if st.button("🔍 開始即時票價精算", use_container_width=True):
    if not selected_outstations:
        st.warning("請至少選擇一個外站喔！")
    else:
        with st.spinner(f'正在連線 Skyscanner 抓取真實票價... (預計消耗 {len(selected_outstations)*len(selected_outstations)*4} 次 API 額度)'):
            results = []
            strategies = [{"name": "前後拆分旅行", "d1": -45, "d4": 45}]

            for start, end in product(selected_outstations, repeat=2):
                for s in strategies:
                    d1_s = (date_out + timedelta(days=s['d1'])).strftime("%Y-%m-%d")
                    d4_s = (date_in + timedelta(days=s['d4'])).strftime("%Y-%m-%d")
                    
                    s1 = fetch_base_flight_data(start, "TPE", d1_s, cabin_choice)
                    s2 = fetch_base_flight_data("TPE", out_dest, date_out.strftime("%Y-%m-%d"), cabin_choice)
                    s3 = fetch_base_flight_data(in_origin, "TPE", date_in.strftime("%Y-%m-%d"), cabin_choice)
                    s4 = fetch_base_flight_data("TPE", end, d4_s, cabin_choice)
                    
                    f1 = calculate_family_price(s1['base_price'], adults, children, infants)
                    f2 = calculate_family_price(s2['base_price'], adults, children, infants)
                    f3 = calculate_family_price(s3['base_price'], adults, children, infants)
                    f4 = calculate_family_price(s4['base_price'], adults, children, infants)
                    
                    separate_total = f1 + f2 + f3 + f4
                    together_total = int((f2 + f3) * 0.85 + (f1 + f4) * 0.15)
                    savings = separate_total - together_total

                    details_text = [
                        f"第一段 {start} ✈️ TPE | NT$ {f1:,}  {s1['status']}",
                        f"第二段 TPE ✈️ {out_dest} | NT$ {f2:,}  {s2['status']}",
                        f"第三段 {in_origin} ✈️ TPE | NT$ {f3:,}  {s3['status']}",
                        f"第四段 TPE ✈️ {end} | NT$ {f4:,}  {s4['status']}"
                    ]

                    results.append({
                        "title": f"【{s['name']}】{start} 進 / {end} 出",
                        "together": together_total,
                        "separate": separate_total,
                        "savings": savings,
                        "miles": (s1['miles']+s2['miles']+s3['miles']+s4['miles']) * adults,
                        "details": details_text
                    })

            top_results = sorted(results, key=lambda x: x['together'])[:5]
            st.success(f"🎉 計算完成！({adults}大{children}小{infants}嬰 - {cabin_choice})")
            
            for i, t in enumerate(top_results, 1):
                with st.expander(f"🏆 Top {i}: {t['title']} ➔ 四段合買 NT$ {t['together']:,}"):
                    st.markdown(f"**🔥 四段合買預估價：<span style='color:red; font-size:20px'>NT$ {t['together']:,}</span>**", unsafe_allow_html=True)
                    st.write(f"🛑 分開單買總價：NT$ {t['separate']:,}")
                    st.write(f"🤑 總共省下：**NT$ {t['savings']:,}**")
                    st.write(f"📈 預估累積華夏哩程：{t['miles']:,} 哩")
                    st.markdown("---")
                    st.markdown("**各段單買原價明細 (資料來源分析)：**")
                    for info in t['details']:
                        st.write(f"• {info}")
