import streamlit as st
import random
from datetime import datetime, timedelta
from itertools import product
import requests

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# --- 核心資料抓取與計算 (升級照妖鏡版) ---
def fetch_base_flight_data(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://skyscanner-flights-travel-api.p.rapidapi.com/searchFlights"
    
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    # 加入 carrier: CI 嘗試過濾華航
    params = {
        "origin": origin, "destination": dest, "date": date, 
        "adults": "1", "currency": "TWD", "cabinClass": cabin_mapping[cabin_class],
        "carrier": "CI" 
    }
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "skyscanner-flights-travel-api.p.rapidapi.com"}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status() # 檢查是否被 API 伺服器阻擋 (如 429 頻率過高)
        data = response.json()
        
        real_price = data['data']['flights'][0]['price']
        miles = 4500 if "PRG" in [origin, dest] or "FRA" in [origin, dest] or "ZRH" in [origin, dest] else 1000
        return {"base_price": int(real_price), "miles": miles, "status": "✅ API 即時報價"}
        
    except Exception as e:
        # 照妖鏡機制：捕捉確切的錯誤原因
        err_msg = str(e)
        if "429" in err_msg:
            reason = "API免費額度限制"
        elif "400" in err_msg or "KeyError" in str(type(e)) or "IndexError" in str(type(e)):
            reason = "無華航直飛或格式異常"
        else:
            reason = "連線超時"

        # 模擬備案
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
st.title("✈️ 華航外站四段票神器")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    # 預設去程日期改為 2026/06/11
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    # 預設回程起點改為 FRA
    in_origin = st.text_input("長程回程起點", value="FRA")
    # 預設回程日期改為 2026/06/25
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["經濟艙", "豪經艙", "商務艙"])

# 標題改為「旅行成員」
st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=2, min_value=1)
with c2: children = st.number_input("兒童", value=1, min_value=0)
with c3: infants = st.number_input("嬰兒", value=1, min_value=0)

if st.button("🔍 開始即時票價精算", use_container_width=True):
    with st.spinner(f'正在連線 Skyscanner 抓取【{cabin_choice}】真實票價...'):
        outstations = ["FUK", "KUL", "BKK", "MNL"]
        results = []
        strategies = [{"name": "完美中轉", "d1": -1, "d4": 1}, {"name": "前後拆分旅行", "d1": -45, "d4": 45}]

        for start, end in product(outstations, repeat=2):
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

        top_5 = sorted(results, key=lambda x: x['together'])[:5]
        st.success(f"🎉 計算完成！({adults}大{children}小{infants}嬰 - {cabin_choice})")
        
        for i, t in enumerate(top_5, 1):
            with st.expander(f"🏆 Top {i}: {t['title']} ➔ 四段合買 NT$ {t['together']:,}"):
                st.markdown(f"**🔥 四段合買預估價：<span style='color:red; font-size:20px'>NT$ {t['together']:,}</span>**", unsafe_allow_html=True)
                st.write(f"🛑 分開單買總價：NT$ {t['separate']:,}")
                st.write(f"🤑 總共省下：**NT$ {t['savings']:,}**")
                st.write(f"📈 預估累積華夏哩程：{t['miles']:,} 哩")
                st.markdown("---")
                st.markdown("**各段單買原價明細 (資料來源分析)：**")
                for info in t['details']:
                    st.write(f"• {info}")

st.info("💡 提示：若顯示「系統模擬」，代表 API 免費額度耗盡或該日無直飛航班，系統將自動套用預估模型。")
