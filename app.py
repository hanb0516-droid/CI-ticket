import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面美化 ---
st.set_page_config(page_title="華航聯程獵殺器 v6.0", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛡️ 穩定型請求邏輯 (內建 1.5 秒硬性冷卻)
def stable_request(url, method="GET", params=None, json=None):
    for i in range(3):
        try:
            time.sleep(1.5) # 這是保護你的 API 不被封鎖的關鍵保險
            if method == "GET":
                res = requests.get(url, headers=HEADERS, params=params, timeout=20)
            else:
                res = requests.post(url, headers=HEADERS, json=json, timeout=30)
            
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                time.sleep(5) # 觸發流量限制就休息
        except:
            time.sleep(1)
    return None

# 🌟 引擎 A：日曆雷達 (防呆：自動過濾過期日期)
def scan_calendar(origin, dest, month_str, cabin, s_date, e_date):
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": cabin_map[cabin]}
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    
    results = []
    today = date.today()
    if data and data.get('data'):
        days = data['data'].get('days', [])
        for d in days:
            try:
                d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                # 🛡️ 只搜尋「今天以後」且在「使用者要求區間內」的日期
                if d_obj >= today and s_date <= d_obj <= e_date and d.get('price', 0) > 0:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d['price']})
            except: continue
    return results

# 🌟 引擎 B：真實四段聯程精算 (Married Segment 報價)
def fetch_bundle_price(h_in, d1, h_out, d4, d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults):
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
        # 確保全段皆為華航 (CI)
        if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in itin.get('legs', [])):
            details = []
            for l in itin['legs']:
                seg = l.get('segments', [{}])[0]
                b_code = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                details.append(f"CI {seg.get('flightNumber')} ({b_code}) | {l.get('departure','').split('T')[1][:5]}")
            return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": details, "d1": d1, "d4": d4}
    return None

# 🌟 引擎 C：長程基準價
def fetch_base_price(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults):
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = { "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults), "cabinClass": cabin_map[cabin], "flights": [
        {"fromEntityId": d2_org, "toEntityId": d2_dst, "departDate": d2_date.strftime("%Y-%m-%d")},
        {"fromEntityId": d3_org, "toEntityId": d3_dst, "departDate": d3_date.strftime("%Y-%m-%d")}
    ]}
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    try: return int(data['data']['itineraries'][0]['price']['raw'])
    except: return 0

# --- UI 介面 ---
st.title("✈️ 華航全亞洲獵殺器 v6.0 (最終穩定版)")

st.subheader("🗓️ 行程日期與區間設定")
col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市 (TPE)", value="TPE")
    d2_dst = st.text_input("D2 抵達城市 (PRG)", value="PRG")
    d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市 (FRA)", value="FRA")
    d3_dst = st.text_input("D3 抵達城市 (TPE)", value="TPE")
    d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

# 📅 自動推算區間 (D1 = D2前兩個月至D2 | D4 = D3至D3後兩個月)
today = date.today()
d1_s_raw = (d2_date - timedelta(days=62)).replace(day=1)
d1_s = max(d1_s_raw, today) # 🛡️ 關鍵修復：不搜尋過去日期
d1_e = d2_date

d4_s = d3_date
m4, y4 = (d3_date.month + 2, d3_date.year)
if m4 > 12: m4 -= 12; y4 += 1
d4_e = date(y4, m4, calendar.monthrange(y4, m4)[1])

st.success(f"📡 獵殺區間：D1({d1_s}~{d1_e}) | D4({d4_s}~{d4_e})")

cabin = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)
selected_hubs = st.multiselect("📍 選擇掃描外站：", ["MNL", "BKK", "HKG", "KIX", "NRT", "ICN", "PUS", "SGN", "KUL", "FUK"], default=["MNL", "BKK", "HKG", "KIX"])

if st.button("🚀 啟動深度獵殺模式", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 實時搜尋日誌", expanded=True)
    
    # 月份清單
    def get_ms(s, e):
        ms = []
        curr = s.replace(day=1)
        while curr <= e:
            ms.append(curr.strftime("%Y-%m"))
            if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
            else: curr = curr.replace(month=curr.month+1)
        return sorted(list(set(ms)))

    d1_m, d4_m = get_ms(d1_s, d1_e), get_ms(d4_s, d4_e)
    d1_cands, d4_cands = [], []

    # 1. 循序雷達掃描 (雖然稍慢，但保證 API 成功率)
    for hub in selected_hubs:
        for m in d1_m:
            msg.info(f"📡 正在定位去程低價窗口... ({hub} {m})")
            res = scan_calendar(hub, d2_org, m, cabin, d1_s, d1_e)
            d1_cands.extend(res)
            if res: debug.write(f"✅ {hub} 去程：找到 {len(res)} 個低價日期")
        for m in d4_m:
            msg.info(f"📡 正在定位回程低價窗口... ({hub} {m})")
            res = scan_calendar(d3_dst, hub, m, cabin, d4_s, d4_e)
            d4_cands.extend(res)
            if res: debug.write(f"✅ {hub} 回程：找到 {len(res)} 個低價日期")

    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足！原因可能是華航在該區間已無位子，或是 API 暫時限制。請稍後再試。")
    else:
        # 2. 獲取直飛基準
        base_p = fetch_base_price(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults)
        
        # 3. 聯程打包精算 (取前 3 名配對)
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:3]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:3]
        
        msg.warning(f"🔥 正在對準 {len(top_d1)*len(top_d4)} 組日期進行 Married Segment 真實報價...")
        results = []
        for d1, d4 in product(top_d1, top_d4):
            res = fetch_exact_bundle(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults)
            if res:
                res["diff"] = base_p - res["total"] if base_p > 0 else 0
                results.append(res)
        
        msg.empty()
        if results:
            st.success(f"🎉 獵殺完成！直飛基準價：NT$ {base_p:,}")
            for r in sorted(results, key=lambda x: x['total'])[:10]:
                is_save = r['diff'] > 0
                color = "green" if is_save else "red"
                with st.expander(f"{'✅' if is_save else '⚠️'} {r['title']} | D1:{r['d1']} D4:{r['d4']} ➔ NT$ {r['total']:,}"):
                    st.markdown(f"**💰 比直飛{'省下' if is_save else '多花'}：<span style='color:{color}; font-size:20px'>NT$ {abs(r['diff']):,}</span>**", unsafe_allow_html=True)
                    st.write("---")
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
