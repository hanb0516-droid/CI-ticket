import streamlit as st
from datetime import datetime, timedelta
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 核心資料抓取：支援全亞洲航點掃描 + 抓取航班資訊
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_base_flight_data(origin, dest, date, cabin_class):
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
        # 付費版可稍微縮短延遲
        time.sleep(0.3) 
        response = requests.get(url, headers=headers, params=params, timeout=12)
        response.raise_for_status() 
        data = response.json()
        
        # 🎯 提取價格
        itinerary = data['data']['itineraries'][0]
        real_price = itinerary['price']['raw']
        
        # 🎯 提取航班資訊 (航空公司、編號、出發時間)
        try:
            leg = itinerary['legs'][0]
            carriers = leg.get('carriers', {}).get('marketing', [])
            carrier_name = carriers[0].get('name', '中華航空') if carriers else '中華航空'
            flight_number = leg.get('segments', [{}])[0].get('flightNumber', '')
            dep_time = leg.get('departure', '')
            if 'T' in dep_time:
                dep_time = dep_time.split('T')[1][:5]
            else:
                dep_time = ""
            flight_info = f" ({carrier_name} {flight_number} | {dep_time} 出發)" if dep_time else f" ({carrier_name} {flight_number})"
        except:
            flight_info = " (華航直飛/天合聯盟)"
            
        miles = 4500 if "PRG" in [origin, dest] or "FRA" in [origin, dest] or "ZRH" in [origin, dest] else 1000
        return {"base_price": int(real_price), "status": "✅ API即時報價", "info": flight_info, "miles": miles}
    except:
        return {"base_price": 999999, "status": "❌ 查無航班", "info": " (無航班資訊)", "miles": 0}

def calculate_family_price(base_price, adults, children, infants):
    total = (base_price * adults) + (int(base_price * 0.75) * children) + (int(base_price * 0.10) * infants)
    return total

# --- App 介面 ---
st.title("✈️ 華航全亞洲外站掃描器 (Pro 完整明細版)")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

# 🌏 全亞洲主要樞紐清單
asia_hubs = [
    "NRT", "KIX", "NGO", "FUK", "CTS", "OKA",  
    "ICN", "PVG", "SHA", "PEK", "HKG", "MFM",  
    "BKK", "SIN", "KUL", "MNL", "SGN", "HAN",  
    "CGK", "DPS", "PEN", "CNX"                 
]

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=2)
with c2: children = st.number_input("兒童", value=1)
with c3: infants = st.number_input("嬰兒", value=1)

if st.button("🚀 執行全亞洲最低價精算", use_container_width=True):
    with st.spinner('正在分析全亞洲所有可能的起訖點組合，並抓取航班時間...'):
        results = []
        
        # 先抓取固定不變的第二段(長程去)與第三段(長程回)
        # 放在迴圈外可以省下大量的 API 呼叫次數跟等待時間！
        s2 = fetch_base_flight_data("TPE", out_dest, date_out.strftime("%Y-%m-%d"), cabin_choice)
        s3 = fetch_base_flight_data(in_origin, "TPE", date_in.strftime("%Y-%m-%d"), cabin_choice)
        
        # 如果長程段查不到，直接報錯停止
        if s2['status'] == "❌ 查無航班" or s3['status'] == "❌ 查無航班":
            st.error(f"⚠️ 指定的日期 ({date_out.strftime('%m/%d')} 或 {date_in.strftime('%m/%d')}) 查不到飛往歐洲的機票，請換個日期試試！")
        else:
            # 只針對第一段與第四段進行全亞洲交叉掃描
            for hub in asia_hubs:
                d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
                d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
                
                s1 = fetch_base_flight_data(hub, "TPE", d1_date, cabin_choice)
                s4 = fetch_base_flight_data("TPE", hub, d4_date, cabin_choice)
                
                # 只有當前後兩段都成功抓到航班時才計算
                if "✅" in s1['status'] and "✅" in s4['status']:
                    f1 = calculate_family_price(s1['base_price'], adults, children, infants)
                    f2 = calculate_family_price(s2['base_price'], adults, children, infants)
                    f3 = calculate_family_price(s3['base_price'], adults, children, infants)
                    f4 = calculate_family_price(s4['base_price'], adults, children, infants)
                    
                    separate_total = f1 + f2 + f3 + f4
                    together_total = int((f2 + f3) * 0.85 + (f1 + f4) * 0.15)
                    savings = separate_total - together_total
                    total_miles = (s1['miles'] + s2['miles'] + s3['miles'] + s4['miles']) * adults

                    # 🎯 將四段完整資訊組合起來
                    details_text = [
                        f"第一段 **{d1_date}** | {hub} ✈️ TPE {s1['info']} | 單買原價 NT$ {f1:,}",
                        f"第二段 **{date_out.strftime('%Y-%m-%d')}** | TPE ✈️ {out_dest} {s2['info']} | 單買原價 NT$ {f2:,}",
                        f"第三段 **{date_in.strftime('%Y-%m-%d')}** | {in_origin} ✈️ TPE {s3['info']} | 單買原價 NT$ {f3:,}",
                        f"第四段 **{d4_date}** | TPE ✈️ {hub} {s4['info']} | 單買原價 NT$ {f4:,}"
                    ]

                    results.append({
                        "hub": hub, 
                        "together": together_total, 
                        "separate": separate_total, 
                        "savings": savings,
                        "miles": total_miles,
                        "details": details_text
                    })

            # 如果有找到結果，就進行排名並顯示
            if results:
                top_5 = sorted(results, key=lambda x: x['together'])[:5]
                st.success(f"🎉 掃描完成！找到全亞洲前 5 名最便宜的外站組合：")
                
                for i, res in enumerate(top_5, 1):
                    with st.expander(f"🏆 第 {i} 名：{res['hub']} 起降 ➔ 四段合買預估 NT$ {res['together']:,}"):
                        st.markdown(f"**🔥 四段合買預估價：<span style='color:red; font-size:20px'>NT$ {res['together']:,}</span>**", unsafe_allow_html=True)
                        st.write(f"🛑 傳統分開單買總價：NT$ {res['separate']:,}")
                        st.write(f"🤑 總共為您省下：**NT$ {res['savings']:,}**")
                        st.write(f"📈 預估累積華夏哩程：{res['miles']:,} 哩")
                        st.markdown("---")
                        st.markdown("**各段單買原價與航班明細：**")
                        for info in res['details']:
                            st.write(f"• {info}")
            else:
                st.warning("⚠️ 掃描完畢，但在您指定的時間區間內，沒有找到完美的四段票組合。")
