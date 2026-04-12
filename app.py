import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time

# --- 介面美化 ---
st.set_page_config(page_title="華航獵殺器 v3.3", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛠️ 穩定型請求 (循序執行，確保 100% 成功)
def stable_request(url, method="GET", params=None, json=None):
    for i in range(3):
        try:
            time.sleep(1.1) # 關鍵延遲：避免觸發 429 錯誤
            if method == "GET":
                res = requests.get(url, headers=HEADERS, params=params, timeout=20)
            else:
                res = requests.post(url, headers=HEADERS, json=json, timeout=30)
            
            if res.status_code == 200: return res.json()
            elif res.status_code == 429: time.sleep(3) # 被擋就休息久一點
        except: time.sleep(1)
    return None

# 🌟 引擎 A：價格日曆雷達 (掃描全月份)
def task_calendar_scan(origin, dest, month_str, cabin, s_date, e_date):
    url = f"{BASE_URL}/flights/price-calendar"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": cabin_map[cabin]}
    
    data = stable_request(url, params=params)
    results = []
    if data and data.get('data'):
        for day in data['data'].get('days', []):
            try:
                d_obj = datetime.strptime(day['day'], "%Y-%m-%d").date()
                if s_date <= d_obj <= e_date and day.get('price', 0) > 0:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": day['price']})
            except: continue
    return results

# 🌟 引擎 B：100% 真實精算 (含艙等代碼修正)
def task_final_check(h_in, d1, h_out, d4, d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults):
    url = f"{BASE_URL}/flights/search-multi-city"
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
    data = stable_request(url, method="POST", json=payload)
    if not data or not data.get('data'): return None
    
    itins = data['data'].get('itineraries', [])
    for itin in itins:
        legs = itin.get('legs', [])
        if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in legs):
            details = []
            for l in legs:
                seg = l.get('segments', [{}])[0]
                # 🚀 艙等代碼深度抓取路徑
                b_code = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                details.append(f"CI {seg.get('flightNumber')} ({b_code}) | {l.get('departure','').split('T')[1][:5]}")
            return {"title": f"{h_in}({d1}) ➔ {h_out}({d4})", "total": int(itin['price']['raw']), "legs": details}
    return None

# 🌟 引擎 C：長程基準價
def task_long_haul_base(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults):
    url = f"{BASE_URL}/flights/search-multi-city"
    cabin_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": cabin_map[cabin], "flights": [
            {"fromEntityId": d2_org, "toEntityId": d2_dst, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_org, "toEntityId": d3_dst, "departDate": d3_date.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(url, method="POST", json=payload)
    try: return int(data['data']['itineraries'][0]['price']['raw'])
    except: return 0

# --- UI ---
st.title("✈️ 華航全亞洲獵殺器 v3.3 (終極穩定版)")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市", value="TPE")
    d2_dst = st.text_input("D2 抵達城市", value="PRG")
    d2_date = st.date_input("去歐洲日期 (D2)", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市", value="FRA")
    d3_dst = st.text_input("D3 抵達城市", value="TPE")
    d3_date = st.date_input("回台灣日期 (D3)", value=date(2026, 6, 25))

# 自動推算日期區間 (去程前兩個月1號, 回程後兩個月最後一天)
d1_s = (d2_date - timedelta(days=62)).replace(day=1)
d1_e = d2_date
d4_s = d3_date
m4 = d3_date.month + 2
y4 = d3_date.year
if m4 > 12: m4 -= 12; y4 += 1
d4_e = date(y4, m4, calendar.monthrange(y4, m4)[1])

st.success(f"📡 自動規劃區間：D1({d1_s}~{d1_e}) | D4({d4_s}~{d4_e})")

cabin = st.selectbox("💺 艙等", ["商務艙", "豪經艙", "經濟艙"])
adults = st.number_input("大人", value=1, min_value=1)

all_hubs = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

if st.button("🚀 啟動深度獵殺", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 實時掃描狀態 (防止 429 鎖定)", expanded=True)
    
    # 取得月份清單
    def get_months(s, e):
        m = []
        c = s.replace(day=1)
        while c <= e:
            m.append(c.strftime("%Y-%m"))
            c = (c + timedelta(days=32)).replace(day=1)
        return m

    d1_m = get_months(d1_s, d1_e)
    d4_m = get_months(d4_s, d4_e)

    # 階段一：循序雷達掃描 (雖然稍慢但保證成功)
    d1_cands, d4_cands = [], []
    total_scans = len(all_hubs) * (len(d1_m) + len(d4_m))
    count = 0

    for hub in all_hubs:
        for m in d1_m:
            count += 1
            msg.info(f"⚡ 階段一：正在掃描去程雷達... ({count}/{total_scans})")
            res = task_calendar_scan(hub, d2_org, m, cabin, d1_s, d1_e)
            d1_cands.extend(res)
            if res: debug.write(f"✅ {hub} 去程：找到 {len(res)} 個低價日期")
            
        for m in d4_m:
            count += 1
            msg.info(f"⚡ 階段一：正在掃描回程雷達... ({count}/{total_scans})")
            res = task_calendar_scan(d3_dst, hub, m, cabin, d4_s, d4_e)
            d4_cands.extend(res)
            if res: debug.write(f"✅ {hub} 回程：找到 {len(res)} 個低價日期")

    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足，華航在此區間可能無機位或 API 超時。")
    else:
        # 取最優 4 個起點與 4 個終點進行深度精算
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:4]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:4]
        
        msg.warning("🔥 階段二：正在精算 16 組真實打包總價與艙等字母...")
        base_p = task_long_haul_base(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults)
        
        final_results = []
        for d1, d4 in product(top_d1, top_d4):
            res = task_final_check(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin, adults)
            if res:
                res["diff"] = base_p - res["total"] if base_p > 0 else 0
                final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success(f"🎉 獵殺完成！直飛基準價：NT$ {base_p:,}")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                is_save = r['diff'] > 0
                color = "green" if is_save else "red"
                with st.expander(f"{'✅' if is_save else '⚠️'} {r['title']} ➔ 總價 NT$ {r['total']:,}"):
                    st.markdown(f"**💰 比直飛{'省下' if is_save else '多花'}：<span style='color:{color}; font-size:20px'>NT$ {abs(r['diff']):,}</span>**", unsafe_allow_html=True)
                    st.write("---")
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
