import streamlit as st
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 引擎 A：多點搜尋 (歐洲主幹，A進B出，嚴格過濾華航)
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
        response = requests.post(url, json=payload, headers=headers, timeout=25)
        if response.status_code == 429:
            return {"status": "❌ API額度耗盡", "total_price": 0, "legs": []}
            
        data = response.json()
        itineraries = data.get('data', {}).get('itineraries', [])
        if not itineraries: return {"status": "❌ 查無航班", "total_price": 0, "legs": []}

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

        real_total_price = ci_itinerary['price']['raw']
        flight_details = []
        for i in range(2):
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

# 🌟 引擎 B：單程搜尋 (外站掃描，嚴格過濾華航)
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_asia_outer_legs(origin, dest, date, cabin_class):
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": date, "adults": "1", "currency": "TWD", "cabinClass": cabin_mapping[cabin_class]}
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "flights-sky.p.rapidapi.com"}

    try:
        time.sleep(0.5) # 放慢腳步避免被擋
        response = requests.get(url, headers=headers, params=params, timeout=12)
        if response.status_code == 429:
            return {"base_price": 0, "status": "❌ API額度耗盡", "info": ""}
            
        data = response.json()
        itineraries = data.get('data', {}).get('itineraries', [])
        ci_itinerary = None
        for itin in itineraries:
            carriers = itin.get('legs', [{}])[0].get('carriers', {}).get('marketing', [])
            if carriers:
                c_name = carriers[0].get('name', '').lower()
                c_code = carriers[0].get('alternateId', '')
                if '中華' in c_name or 'china airlines' in c_name or c_code == 'CI':
                    ci_itinerary = itin; break
                    
        if not ci_itinerary: return {"base_price": 0, "status": "❌ 查無華航", "info": ""}

        real_price = ci_itinerary['price']['raw']
        try:
            leg = ci_itinerary['legs'][0]
            c_name = leg.get('carriers', {}).get('marketing', [{}])[0].get('name', '華航')
            f_num = leg.get('segments', [{}])[0].get('flightNumber', '')
            dep = leg.get('departure', '')
            if 'T' in dep: dep = dep.split('T')[1][:5]
            f_info = f"{c_name} {f_num} | {dep} 出發"
        except:
            f_info = "無資訊"
            
        return {"base_price": int(real_price), "status": "✅", "info": f_info}
    except:
        return {"base_price": 0, "status": "❌ 異常", "info": ""}

def calc_family(base_price, adults, children, infants):
    return (base_price * adults) + (int(base_price * 0.75) * children) + (int(base_price * 0.10) * infants)

# --- App 介面 ---
st.title("✈️ 華航外站全境盲掃神器")

st.subheader("🗓️ 行程與艙等設定")
c_dest1, c_dest2 = st.columns(2)
with c_dest1:
    out_dest = st.text_input("長程去程終點", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 11))
with c_dest2:
    in_origin = st.text_input("長程回程起點", value="FRA")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 25))

cabin_choice = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])

st.subheader("🌏 選擇交叉掃描的樞紐 (建議每次勾選 8-10 個以內運算)")
selected_hubs = st.multiselect(
    "華航全亞洲 22 大航點完整收錄！(包含釜山 PUS)：",
    [
        "FUK", "KIX", "NRT", "NGO", "CTS", "OKA",  # 日本
        "ICN", "PUS", "HKG", "MFM",                # 韓港澳
        "BKK", "CNX", "SIN", "KUL", "PEN",         # 東南亞(新馬泰)
        "MNL", "CEB", "SGN", "HAN", "DAD",         # 菲律賓、越南
        "CGK", "DPS"                               # 印尼
    ],
    default=["FUK", "KIX", "NRT", "PUS", "BKK", "KUL", "MNL", "SGN"]
)

st.subheader("👥 旅行成員")
c1, c2, c3 = st.columns(3)
with c1: adults = st.number_input("大人", value=2)
with c2: children = st.number_input("兒童", value=1)
with c3: infants = st.number_input("嬰兒", value=1)


if st.button("🚀 啟動黃金樞紐交叉比對", use_container_width=True):
    if not selected_hubs:
        st.warning("請至少選擇一個外站喔！")
    else:
        progress_bar = st.progress(0, text="📡 正在獲取歐洲長程主段基準票價...")
        results = []
        
        europe_main = fetch_europe_main_legs("TPE", out_dest, date_out.strftime("%Y-%m-%d"), in_origin, "TPE", date_in.strftime("%Y-%m-%d"), cabin_choice, adults, children, infants)
        
        if "❌" in europe_main['status']:
            progress_bar.empty()
            if "額度耗盡" in europe_main['status']:
                st.error("🚨 警告：您的 API 呼叫額度可能已經用盡，請至 RapidAPI 確認您的訂閱狀態！")
            else:
                st.error(f"⚠️ 歐洲主幹段查無純華航機票！(可能是商務艙該日已售罄)")
        else:
            europe_total_price = europe_main['total_price']
            st.info(f"🌸 已鎖定華航歐洲長程真實總價：**NT$ {europe_total_price:,}**。")
            
            d1_date = (date_out - timedelta(days=45)).strftime("%Y-%m-%d")
            d4_date = (date_in + timedelta(days=45)).strftime("%Y-%m-%d")
            
            s1_cache = {}
            s4_cache = {}
            total_hubs = len(selected_hubs)
            rate_limit_hit = False
            
            for i, hub in enumerate(selected_hubs):
                percent = int(((i + 1) / total_hubs) * 80) + 5
                progress_bar.progress(percent, text=f"🛫 正在雷達掃描航點：{hub} ({i+1}/{total_hubs})...")
                
                s1_res = fetch_asia_outer_legs(hub, "TPE", d1_date, cabin_choice)
                s4_res = fetch_asia_outer_legs("TPE", hub, d4_date, cabin_choice)
                
                if "額度耗盡" in s1_res['status'] or "額度耗盡" in s4_res['status']:
                    rate_limit_hit = True
                    break
                    
                s1_cache[hub] = s1_res
                s4_cache[hub] = s4_res
            
            progress_bar.empty()
            
            if rate_limit_hit:
                st.error("🚨 掃描中斷：系統偵測到您的 API 額度已經耗盡 (Error 429)。請至 RapidAPI 升級您的方案。")
            else:
                with st.spinner("🧠 正在腦內進行開口交叉配對..."):
                    for hub_in, hub_out in product(selected_hubs, repeat=2):
                        s1 = s1_cache[hub_in]
                        s4 = s4_cache[hub_out]
                        
                        if "✅" in s1['status'] and "✅" in s4['status']:
                            f1_family = calc_family(s1['base_price'], adults, children, infants)
                            f4_family = calc_family(s4['base_price'], adults, children, infants)
                            
                            together_total = int(europe_total_price * 0.90 + (f1_family + f4_family) * 0.15)
                            separate_total = europe_total_price + f1_family + f4_family

                            details_text = [
                                f"第一段 **{d1_date}** | {hub_in} ✈️ TPE ({s1['info']})",
                                f"第二段 **{date_out.strftime('%Y-%m-%d')}** | TPE ✈️ {out_dest} ({europe_main['legs'][0]})",
                                f"第三段 **{date_in.strftime('%Y-%m-%d')}** | {in_origin} ✈️ TPE ({europe_main['legs'][1]})",
                                f"第四段 **{d4_date}** | TPE ✈️ {hub_out} ({s4['info']})"
                            ]

                            title_prefix = f"【同點起降】{hub_in}" if hub_in == hub_out else f"【開口混搭】{hub_in} 啟程 ➔ 飛回 {hub_out}"

                            results.append({
                                "title": title_prefix, 
                                "together": together_total, 
                                "separate": separate_total, 
                                "savings": separate_total - together_total,
                                "miles": (4500 * 2 + 1000 * 2) * adults,
                                "details": details_text
                            })

                if results:
                    top_results = sorted(results, key=lambda x: x['together'])[:10]
                    st.success(f"🎉 交叉配對完成！為您淬鍊出絕對最便宜的前 10 種買法：")
                    
                    for i, res in enumerate(top_results, 1):
                        with st.expander(f"🏆 第 {i} 名：{res['title']} ➔ 總結帳 NT$ {res['together']:,}"):
                            st.markdown(f"**🔥 四段合買預估價：<span style='color:red; font-size:20px'>NT$ {res['together']:,}</span>**", unsafe_allow_html=True)
                            st.write(f"🛑 如果分開單買總價：NT$ {res['separate']:,}")
                            st.write(f"🤑 組合技為您省下：**NT$ {res['savings']:,}**")
                            st.markdown("---")
                            st.markdown("**✈️ 實際航班明細 (保證華航)：**")
                            for info in res['details']:
                                st.write(f"• {info}")
                else:
                    st.warning("查無合適的機票組合，可能該日期的班機已客滿。")
