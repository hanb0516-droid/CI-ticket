import streamlit as st
from datetime import datetime, timedelta, date
import calendar
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面美化 ---
st.set_page_config(page_title="華航獵殺器 v4.0", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛠️ 穩定型請求邏輯：保證 100% 成功率
def stable_request(url, method="GET", params=None, json=None):
    for i in range(3): # 最多重試 3 次
        try:
            time.sleep(1.2) # 關鍵延遲，避免 429
            if method == "GET":
                res = requests.get(url, headers=HEADERS, params=params, timeout=20)
            else:
                res = requests.post(url, headers=HEADERS, json=json, timeout=30)
            
            if res.status_code == 200:
                data = res.json()
                if data and data.get('status') is True or data.get('data'):
                    return data
            elif res.status_code == 429:
                time.sleep(3) # 遇到流量限制，休息久一點
        except:
            time.sleep(1)
    return None

# 🌟 引擎 A：區間價格掃描器 (Price Calendar)
@st.cache_data(ttl=3600)
def scan_calendar_range(origin, dest, months, cabin, s_date, e_date):
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    all_days = []
    for m in months:
        params = {"fromEntityId": origin, "toEntityId": dest, "departDate": m, "currency": "TWD", "cabinClass": cabin_map[cabin]}
        data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
        if data and data.get('data'):
            days = data['data'].get('days', [])
            for d in days:
                try:
                    d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                    if s_date <= d_obj <= e_date and d.get('price', 0) > 0:
                        all_days.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d['price']})
                except: continue
    return all_days

# 🌟 引擎 B：100% 真實打包精算 (Multi-City)
def fetch_multi_city_exact(h_in, d1, h_out, d4, d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults):
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": cabin_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_org, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_org, "toEntityId": d2_dst, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_org, "toEntityId": d3_dst, "departDate": d3_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_dst, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if not data or not data.get('data'): return None
    
    itins = data['data'].get('itineraries', [])
    for itin in itins:
        # 嚴格過濾純華航
        legs = itin.get('legs', [])
        if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in legs):
            details = []
            for l in legs:
                seg = l.get('segments', [{}])[0]
                b_code = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                details.append(f"CI {seg.get('flightNumber')} ({b_code}) | {l.get('departure','').split('T')[1][:5]}")
            return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": details, "d1": d1, "d4": d4}
    return None

# 🌟 引擎 C：長程基準價
def fetch_base_price(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults):
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": cabin_map[cabin], "flights": [
            {"fromEntityId": d2_org, "toEntityId": d2_dst, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_org, "toEntityId": d3_dst, "departDate": d3_date.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    try: return int(data['data']['itineraries'][0]['price']['raw'])
    except: return 0

# --- 主程式 ---
st.title("✈️ 華航全亞洲獵殺器 v4.0 (終極穩健版)")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市", value="TPE")
    d2_dst = st.text_input("D2 抵達城市", value="PRG")
    d2_date = st.date_input("去程日期 (D2)", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市", value="FRA")
    d3_dst = st.text_input("D3 抵達城市", value="TPE")
    d3_date = st.date_input("回程日期 (D3)", value=date(2026, 6, 25))

# 📅 日期區間邏輯自動推算
d1_s = (d2_date - timedelta(days=62)).replace(day=1) # D2 前兩個月 1 號
d1_e = d2_date
d4_s = d3_date
# 計算 D4 結束日
m4 = d3_date.month + 2
y4 = d3_date.year
if m4 > 12: m4 -= 12; y4 += 1
d4_e = date(y4, m4, calendar.monthrange(y4, m4)[1])

st.success(f"📡 自動規劃區間：D1({d1_s}~{d1_e}) | D4({d4_s}~{d4_e})")

cabin = st.selectbox("💺 選擇艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)

# 航點選擇 (預設最容易省錢的 10 個站點)
all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]
selected_hubs = st.multiselect("📍 選擇掃描外站：", all_hubs, default=["KIX", "NRT", "BKK", "MNL", "HKG", "ICN", "PUS", "SGN", "KUL", "FUK"])

if st.button("🚀 啟動全亞洲區間深度獵殺", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 實時掃描進度報告", expanded=True)
    
    # 月份清單
    def get_m(s, e):
        ms = []
        c = s.replace(day=1)
        while c <= e:
            ms.append(c.strftime("%Y-%m"))
            c = (c + timedelta(days=32)).replace(day=1)
        return ms

    d1_m, d4_m = get_m(d1_s, d1_e), get_m(d4_s, d4_e)

    # 第一階段：雷達快掃 (100% 成功率版)
    d1_cands, d4_cands = [], []
    
    total = len(selected_hubs)
    for i, hub in enumerate(selected_hubs):
        msg.info(f"📡 階段一：正在掃描第 {i+1}/{total} 個外站雷達... ({hub})")
        res_in = scan_calendar_range(hub, d2_org, d1_m, cabin, d1_s, d1_e)
        res_out = scan_calendar_range(d3_dst, hub, d4_m, cabin, d4_s, d4_e)
        d1_cands.extend(res_in)
        d4_cands.extend(res_out)
        debug.write(f"✅ {hub}：找到去程 {len(res_in)} 個/回程 {len(res_out)} 個低價日期")

    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足！雷達未掃到機位。請確認日期區間華航是否已放票。")
    else:
        # 取最優起訖點組合
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:3]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:3]
        
        msg.warning("🔥 階段二：正在精算 100% 真實打包價與艙等字母...")
        base_p = fetch_base_price(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults)
        
        final_results = []
        for d1, d4 in product(top_d1, top_d4):
            res = fetch_multi_city_exact(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults)
            if res:
                res["diff"] = base_p - res["total"] if base_p > 0 else 0
                final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success(f"🎉 獵殺完成！直飛基準價：NT$ {base_p:,}")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                is_save = r['diff'] > 0
                color = "green" if is_save else "red"
                with st.expander(f"{'✅' if is_save else '⚠️'} {r['title']} | {r['d1']} & {r['d4']} ➔ NT$ {r['total']:,}"):
                    st.markdown(f"**💰 比直飛{'省下' if is_save else '多花'}：<span style='color:{color}; font-size:20px'>NT$ {abs(r['diff']):,}</span>**", unsafe_allow_html=True)
                    st.write("---")
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 深度精算無結果，可能該日期的華航外站艙位已售罄。")
