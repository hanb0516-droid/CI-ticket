import streamlit as st
from datetime import datetime, timedelta, date
import calendar
from itertools import product
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- 介面設定 ---
st.set_page_config(page_title="華航外站全境獵殺器 vMax", layout="wide")
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

API_KEY = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
BASE_URL = "https://flights-sky.p.rapidapi.com"
ALL_HUBS = ["FUK", "KIX", "NRT", "NGO", "CTS", "OKA", "ICN", "PUS", "HKG", "MFM", "BKK", "CNX", "SIN", "KUL", "PEN", "MNL", "CEB", "SGN", "HAN", "DAD", "CGK", "DPS"]

# 🛡️ 穩壓器：全局線程鎖 (保證無論開多少 Thread，API 請求絕對間隔 1.2 秒)
api_lock = threading.Lock()

def stable_request(url, method="GET", params=None, json=None):
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "flights-sky.p.rapidapi.com", "Content-Type": "application/json"}
    for i in range(3):
        try:
            with api_lock:
                time.sleep(1.2) # 絕對物理間隔
                if method == "GET":
                    res = requests.get(url, headers=headers, params=params, timeout=25)
                else:
                    res = requests.post(url, headers=headers, json=json, timeout=35)
            
            if res.status_code == 200:
                data = res.json()
                if data and data.get('data'): return data
            elif res.status_code == 429:
                time.sleep(5)
        except:
            time.sleep(1)
    return None

# 🌟 引擎 A：安全月份字串提取
def get_safe_months(s_date, e_date):
    ms = []
    curr = s_date.replace(day=1)
    while curr <= e_date:
        ms.append(curr.strftime("%Y-%m"))
        if curr.month == 12: curr = curr.replace(year=curr.year+1, month=1)
        else: curr = curr.replace(month=curr.month+1)
    return sorted(list(set(ms)))

# 🌟 引擎 B：日曆探路 (動態掃描)
def scan_calendar(origin, dest, month_str, cabin, s_limit, e_limit):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    params = {"fromEntityId": origin, "toEntityId": dest, "departDate": month_str, "currency": "TWD", "cabinClass": c_map[cabin], "market": "US"}
    data = stable_request(f"{BASE_URL}/flights/price-calendar", params=params)
    results = []
    today = date.today()
    if data and data.get('data'):
        days = data['data'].get('days', [])
        for d in days:
            try:
                d_obj = datetime.strptime(d['day'], "%Y-%m-%d").date()
                if d_obj >= today and s_limit <= d_obj <= e_limit:
                    results.append({"hub": origin if origin != "TPE" else dest, "day": d_obj, "price": d.get('price', 999999)})
            except: continue
    return results

# 🌟 引擎 C：直飛基準價
def fetch_base_price(d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": c_map[cabin],
        "flights": [
            {"fromEntityId": d2_o, "toEntityId": d2_d, "departDate": d2_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_o, "toEntityId": d3_d, "departDate": d3_dt.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if data and data.get('data'):
        try: return int(data['data']['itineraries'][0]['price']['raw'])
        except: return 0
    return 0

# 🌟 引擎 D：真實聯程精算
def fetch_bundle_price(h_in, d1, h_out, d4, d2_o, d2_d, d2_dt, d3_o, d3_d, d3_dt, cabin, adults):
    c_map = {"商務艙": "business", "豪經艙": "premiumeconomy", "經濟艙": "economy"}
    payload = {
        "market": "TW", "locale": "zh-TW", "currency": "TWD", "adults": int(adults),
        "cabinClass": c_map[cabin], "sort": "cheapest_first",
        "flights": [
            {"fromEntityId": h_in, "toEntityId": d2_o, "departDate": d1.strftime("%Y-%m-%d")},
            {"fromEntityId": d2_o, "toEntityId": d2_d, "departDate": d2_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_o, "toEntityId": d3_d, "departDate": d3_dt.strftime("%Y-%m-%d")},
            {"fromEntityId": d3_d, "toEntityId": h_out, "departDate": d4.strftime("%Y-%m-%d")}
        ]
    }
    data = stable_request(f"{BASE_URL}/flights/search-multi-city", method="POST", json=payload)
    if data and data.get('data'):
        itins = data['data'].get('itineraries', [])
        for itin in itins:
            if all(l.get('carriers', {}).get('marketing', [{}])[0].get('alternateId') == 'CI' for l in itin.get('legs', [])):
                legs_info = [f"CI {l['segments'][0]['flightNumber']} ({l['segments'][0].get('bookingCode','N/A')}) | {l['departure'].split('T')[1][:5]}" for l in itin['legs']]
                return {"title": f"{h_in} ➔ {h_out}", "total": int(itin['price']['raw']), "legs": legs_info, "d1": d1, "d4": d4}
    return None

# --- UI 面板構建 ---
st.title("✈️ 華航外站全境獵殺器 (高階自訂版)")

# 1. 核心行程 (D2 & D3)
st.subheader("📌 核心行程 (D2 / D3)")
c_d2, c_d3 = st.columns(2)
with c_d2:
    d2_org = st.text_input("D2 出發 (TPE)", value="TPE")
    d2_dst = st.text_input("D2 抵達 (如 PRG)", value="PRG")
    d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
with c_d3:
    d3_org = st.text_input("D3 出發 (如 FRA)", value="FRA")
    d3_dst = st.text_input("D3 抵達 (TPE)", value="TPE")
    d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

# 2. 自動推算 D1/D4 預設極限值
today = date.today()
default_d1_start = max(today + timedelta(days=1), (d2_date - timedelta(days=60)))
default_d1_end = d2_date
default_d4_start = d3_date
default_d4_end = d3_date + timedelta(days=60)

# 3. 外站接駁 (D1 & D4)
st.subheader("🌍 外站接駁設定 (D1 / D4)")
c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_hub_sel = st.selectbox("D1 出發城市", ["全部 (22個站點)"] + ALL_HUBS, index=5) # 預設 MNL 附近
    d1_date_input = st.date_input("D1 日期區間 (不選則自動推算前2個月)", value=(default_d1_start, default_d1_end))
    st.info("💡 D1 抵達城市固定為 TPE")

with c_d4:
    d4_hub_sel = st.selectbox("D4 抵達城市", ["全部 (22個站點)"] + ALL_HUBS, index=5)
    d4_date_input = st.date_input("D4 日期區間 (不選則自動推算後2個月)", value=(default_d4_start, default_d4_end))
    st.info("💡 D4 出發城市固定為 TPE")

# 4. 艙等與人數
st.subheader("💺 艙等與人數")
c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("大人人數", value=1, min_value=1)

# --- 處理日期解析 ---
def extract_dates(date_val, def_s, def_e):
    if not date_val: return def_s, def_e
    if isinstance(date_val, tuple):
        s = date_val[0]
        e = date_val[1] if len(date_val) > 1 else date_val[0]
        return s, e
    return date_val, date_val

d1_s, d1_e = extract_dates(d1_date_input, default_d1_start, default_d1_end)
d4_s, d4_e = extract_dates(d4_date_input, default_d4_start, default_d4_end)
d1_hubs = ALL_HUBS if d1_hub_sel == "全部 (22個站點)" else [d1_hub_sel]
d4_hubs = ALL_HUBS if d4_hub_sel == "全部 (22個站點)" else [d4_hub_sel]

# --- 啟動獵殺 ---
if st.button("🚀 啟動全境聯程獵殺", use_container_width=True):
    msg = st.empty()
    debug = st.expander("🛠️ 即時掃描日誌 (全程防超時防跳電)", expanded=True)
    
    d1_m, d4_m = get_safe_months(d1_s, d1_e), get_safe_months(d4_s, d4_e)
    d1_cands, d4_cands = [], []

    # 1. 雷達階段 (多線程 + 全局鎖)
    msg.info("⚡ 階段一：正在掃描日曆低價窗口 (如果選了『全部』可能需時 1-2 分鐘，請稍候)...")
    
    def scan_d1(h):
        local_cands = []
        for m in d1_m: local_cands.extend(scan_calendar(h, "TPE", m, cabin_choice, d1_s, d1_e))
        return h, local_cands

    def scan_d4(h):
        local_cands = []
        for m in d4_m: local_cands.extend(scan_calendar("TPE", h, m, cabin_choice, d4_s, d4_e))
        return h, local_cands

    with ThreadPoolExecutor(max_workers=5) as exe:
        fut_d1 = {exe.submit(scan_d1, h): h for h in d1_hubs}
        fut_d4 = {exe.submit(scan_d4, h): h for h in d4_hubs}
        
        for f in as_completed(fut_d1):
            h, res = f.result()
            d1_cands.extend(res)
            debug.write(f"✅ D1 ({h})：找到 {len(res)} 個潛力日期")
            
        for f in as_completed(fut_d4):
            h, res = f.result()
            d4_cands.extend(res)
            debug.write(f"✅ D4 ({h})：找到 {len(res)} 個潛力日期")

    # 🛡️ 保底容錯：若完全無資料，強制寫入所選的第一個站點進行盲測
    if not d1_cands: d1_cands.append({"hub": d1_hubs[0], "day": d1_s, "price": 999999})
    if not d4_cands: d4_cands.append({"hub": d4_hubs[0], "day": d4_s, "price": 999999})

    # 2. 精算階段
    msg.warning("🔥 階段二：正在獲取直飛基準價與最優組合真實聯程價...")
    base_p = fetch_base_price(d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count)

    # 全局取前 4 個最低價進行交叉配對 (確保組合多樣性)
    top_d1 = sorted(d1_cands, key=lambda x: x['price'])[:4]
    top_d4 = sorted(d4_cands, key=lambda x: x['price'])[:4]
    combos = list(product(top_d1, top_d4))
    
    results = []
    pb = st.progress(0)
    
    def calc_bundle(combo):
        d1, d4 = combo
        return fetch_bundle_price(d1['hub'], d1['day'], d4['hub'], d4['day'], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count)

    with ThreadPoolExecutor(max_workers=5) as exe:
        futs = {exe.submit(calc_bundle, c): c for c in combos}
        for idx, f in enumerate(as_completed(futs)):
            c = futs[f]
            pb.progress((idx + 1) / len(combos), text=f"精算中：{c[0]['hub']} ➔ {c[1]['hub']} ({idx+1}/{len(combos)})")
            res = f.result()
            if res:
                res["diff"] = base_p - res["total"] if base_p > 0 else 0
                results.append(res)

    pb.empty()
    msg.empty()

    if results:
        st.success(f"🎉 獵殺完畢！【長程直飛基準價：NT$ {base_p:,}】")
        st.info("💡 下方為所有配對結果，包含比直飛貴的組合，供您全盤考量。")
        for r in sorted(results, key=lambda x: x['total']):
            is_save = r['diff'] > 0
            # 🔴 無論正負價差，一律強制顯示
            color = "green" if is_save else "red"
            diff_text = f"省下 NT$ {abs(r['diff']):,}" if is_save else f"多花 NT$ {abs(r['diff']):,}"
            
            with st.expander(f"{'✅' if is_save else '⚠️'} {r['title']} | D1:{r['d1']} D4:{r['d4']} ➔ 總價 NT$ {r['total']:,}"):
                if base_p > 0:
                    st.markdown(f"**💰 比直飛{diff_text}**", unsafe_allow_html=True)
                st.write("---")
                for i, leg in enumerate(r['legs'], 1): st.write(f"{i}️⃣ {leg}")
    else:
        st.error("❌ 聯程精算失敗。可能華航在這些組合下已無位子。")
