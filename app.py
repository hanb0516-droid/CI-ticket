import streamlit as st
from datetime import datetime, timedelta, date
import calendar
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 介面隱藏與設定 ---
st.set_page_config(page_title="華航獵殺器 v7.0", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
HEADERS = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}

# 🛡️ 穩定型請求 (加入 1.8 秒強制間隔，確保 API 100% 成功率)
def stable_request(url, method="GET", params=None, json=None):
    for i in range(3):
        try:
            time.sleep(1.8) # 這是保護電路的「保險絲」，請勿縮短
            if method == "GET":
                res = requests.get(url, headers=HEADERS, params=params, timeout=20)
            else:
                res = requests.post(url, headers=HEADERS, json=json, timeout=30)
            
            if res.status_code == 200:
                return res.json()
            elif res.status_code == 429:
                time.sleep(5)
        except:
            time.sleep(1)
    return None

# 🌟 引擎 A：日曆掃描 (具備深度容錯功能)
def scan_calendar(origin, dest, month_str, cabin, s_date, e_date):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": c_map[cabin]}
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    
    results = []
    today = date.today()
    # 🛡️ 強化檢查：確保 data 不為 None 且具備正確結構
    if data and isinstance(data, dict) and data.get('data'):
        days = data['data'].get('days', [])
        if days:
            for d in days:
                try:
                    d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                    if d_obj >= today and s_date <= d_obj <= e_date and d.get('price', 0) > 0:
                        results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d['price']})
                except: continue
    return results

# 🌟 引擎 B：100% 真實聯程打包價 ($2+4=5 的核心)
def fetch_exact_bundle(h_in, d1, h_out, d4, d2_o, d2_d, d2_date, d3_o, d3_d, d3_date, cabin, adults):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": c_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_o, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_o, "toEntityId": d2_d, "departDate": d2_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_o, "toEntityId": d3_d, "departDate": d3_date.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_d, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if data and data.get('data'):
        itins = data['data'].get('itineraries', [])
        for itin in itins:
            # 驗證純華航 CI 執飛
            if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in itin.get('legs', [])):
                legs_info = []
                for l in itin['legs']:
                    seg = l.get('segments', [{}])[0]
                    bc = seg.get('bookingCode') or seg.get('segmentClass') or "N/A"
                    legs_info.append(f"CI {seg.get('flightNumber')} ({bc}) | {l.get('departure','').split('T')[1][:5]}")
                return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": legs_info, "d1": d1, "d4": d4}
    return None

# --- UI ---
st.title("✈️ 華航外站獵殺器 v7.0 (最終穩定版)")

with st.sidebar:
    st.header("⚙️ 搜尋設定")
    cabin_choice = st.selectbox("選擇艙等", ["商務艙", "豪經艙", "經濟艙"])
    adults = st.number_input("大人人數", value=1, min_value=1)
    st.markdown("---")
    st.info("💡 貼心提醒：若雷達失敗，請縮小外站範圍，給 API 一點喘息空間。")

col1, col2 = st.columns(2)
with col1:
    d2_org = st.text_input("D2 出發城市 (TPE)", value="TPE")
    d2_dst = st.text_input("D2 抵達城市 (PRG)", value="PRG")
    d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
with col2:
    d3_org = st.text_input("D3 出發城市 (FRA)", value="FRA")
    d3_dst = st.text_input("D3 抵達城市 (TPE)", value="TPE")
    d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

# --- 日期邏輯自動對齊 ---
today = date.today()
d1_start = max(today, (d2_date - timedelta(days=62)).replace(day=1))
d1_end = d2_date
d4_start = d3_date
m4, y4 = (d3_date.month + 2, d3_date.year) if d3_date.month <= 10 else (d3_date.month - 10, d3_date.year + 1)
_, last_d = calendar.monthrange(y4, m4)
d4_end = date(y4, m4, last_d)

st.success(f"📡 獵殺區間：D1({d1_start}~{d1_end}) | D4({d4_start}~{d4_end})")

# 航點清單
all_hubs = ["KIX", "MNL", "BKK", "HKG", "NRT", "ICN", "PUS", "SGN", "KUL", "FUK"]
selected_hubs = st.multiselect("📍 選擇掃描外站：", all_hubs, default=["KIX", "MNL", "BKK", "HKG"])

if st.button("🚀 啟動獵殺", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 診斷日誌 (施工中，請勿關閉)", expanded=True)
    
    # 取得月份
    def get_months(s, e):
        ms = []
        curr = s.replace(day=1)
        while curr <= e:
            ms.append(curr.strftime("%Y-%m"))
            curr = (curr + timedelta(days=32)).replace(day=1)
        return list(set(ms))

    d1_m, d4_m = get_months(d1_start, d1_end), get_months(d4_start, d4_end)
    d1_cands, d4_cands = [], []

    # 階段一：分批雷達
    for hub in selected_hubs:
        msg.info(f"⚡ 正在掃描外站：{hub}...")
        for m in d1_m:
            res = scan_calendar(hub, d2_org, m, cabin_choice, d1_start, d1_end)
            d1_cands.extend(res)
        for m in d4_m:
            res = scan_calendar(d3_dst, hub, m, cabin_choice, d4_start, d4_end)
            d4_cands.extend(res)
        debug.write(f"✅ {hub} 已完成掃描")

    if not d1_cands or not d4_cands:
        st.error("🚨 樣本不足！原因：華航在該區間無機位，或 API 連線過載。建議手動微調日期後再按一次。")
    else:
        # 階段二：聯程精算
        top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:3]
        top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:3]
        
        msg.warning("🔥 正在獲取『四段聯程』打包報價...")
        final_results = []
        
        # 為了絕對穩定，這裡不使用並行，改用一個一個問
        for d1, d4 in product(top_d1, top_d4):
            res = fetch_exact_bundle(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adults)
            if res: final_results.append(res)
        
        msg.empty()
        if final_results:
            st.success("🎉 獵殺完成！以下為全區間最低組合：")
            for r in sorted(final_results, key=lambda x: x['total'])[:10]:
                with st.expander(f"🏆 {r['title']} | D1:{r['d1']} D4:{r['d4']} ➔ NT$ {r['total']:,}"):
                    for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
        else:
            st.error("❌ 聯程精算失敗，該日期組合無機位。")
