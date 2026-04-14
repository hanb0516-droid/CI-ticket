import streamlit as st
import httpx
import asyncio
import json
import time
import random
import uuid
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date
from itertools import product

# ==========================================
# 0. 初始化與靜態快取 (v38.4 核心)
# ==========================================
st.set_page_config(page_title="Flight Actuary | v38.4 STABLE+", page_icon="✈️", layout="wide")

@st.cache_data
def get_hubs():
    h = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
        "港澳": {"HKG": "香港", "MFM": "澳門"},
        "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
        "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
    }
    all_c = [f"{code} ({name})" for r, cities in h.items() for code, name in cities.items()]
    flat_map = {code: name for r in h.values() for code, name in r.items()}
    def f_idx(target):
        for i, s in enumerate(all_c):
            if s.startswith(target): return i
        return 0
    return h, all_c, flat_map, f_idx("TPE"), f_idx("PRG"), f_idx("FRA")

CI_HUBS, ALL_CITIES, AIRPORT_MAP, IDX_TPE, IDX_PRG, IDX_FRA = get_hubs()

if "debug_info" not in st.session_state: st.session_state.debug_info = []

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 缺少 API KEY"); st.stop()

S_SENDER, S_PWD, S_RECEIVER = st.secrets.get("EMAIL_SENDER", ""), st.secrets.get("EMAIL_PASSWORD", ""), st.secrets.get("EMAIL_RECEIVER", "")

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "run_id" not in st.session_state: st.session_state.run_id = None
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000

# ==========================================
# 1. 工具函數
# ==========================================
def get_safe_dates(d_input):
    if isinstance(d_input, (list, tuple)):
        if len(d_input) >= 2: return d_input[0], d_input[1]
        if len(d_input) == 1: return d_input[0], d_input[0]
    return d_input, d_input

def get_name(code):
    return f"{code} ({AIRPORT_MAP.get(code, '未知')})"

def send_detailed_email(res, ref, target_str, version="v38.4+"):
    if not S_SENDER or not S_PWD or not S_RECEIVER: return
    now_str = datetime.now().strftime("%H:%M:%S")
    msg = MIMEMultipart()
    msg['Subject'] = f"✈️ [{version}] {target_str} (最低 {res[0]['total']:,} TWD)"
    rows = "".join([f"<tr><td>{r['total']:,}</td><td>{ref-r['total']:,}</td><td>{get_name(r['h1'])}➔{get_name(r['h4'])}</td><td>{r['d1']}/{r['d4']}</td></tr>" for r in res[:30]])
    body = f"<h2>{version} 報告 ({now_str})</h2><table border='1'>{rows}</table>"
    msg.attach(MIMEText(f"<html><body>{body}</body></html>", 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(S_SENDER, S_PWD); s.send_message(msg)
    except: pass

# ==========================================
# 2. 異步引擎 (強化防禦版)
# ==========================================
async def fetch_api(client, sem, task_data, rid):
    if st.session_state.run_id != rid: return None
    legs, cabin, h1, h4, d1, d4 = task_data
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    
    async with sem:
        for attempt in range(3): # 增加重試韌性
            if st.session_state.run_id != rid: return None
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=40.0)
                if res.status_code == 200:
                    raw = res.json()
                    offers = raw.get('data', {}).get('flightOffers', [])
                    if not offers:
                        if attempt == 2: st.session_state.debug_info.append(f"⚠️ {h1}-{h4} API回傳成功但無票")
                        continue
                    
                    valid = []
                    for o in offers:
                        l_sum = []
                        for seg in o.get('segments', []):
                            for leg in seg.get('legs', []):
                                f = leg.get('flightInfo', {})
                                l_sum.append(f"CI{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        valid.append({"total": p, "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429:
                    await asyncio.sleep(2.0 * (attempt + 1)) # 指數退避
                else:
                    st.session_state.debug_info.append(f"❌ {h1}-{h4} 錯誤: {res.status_code}")
            except Exception as e:
                st.session_state.debug_info.append(f"💥 {h1}-{h4} 異常: {type(e).__name__}")
                await asyncio.sleep(1.0)
        return None

# ==========================================
# 3. UI
# ==========================================
st.sidebar.header(f"⚙️ 控制台 (v38.4+)")
workers = st.sidebar.slider("併發數", 20, 100, 50)
email_on = st.sidebar.checkbox("寄送 Email", value=True)
if st.sidebar.button("🛑 停止並清空"): 
    st.session_state.run_id = None; st.session_state.valid_offers = []; st.session_state.debug_info = []; st.rerun()

trip_mode = st.radio("模式", ["來回", "多點"], horizontal=True)
c1, c2 = st.columns(2)
if trip_mode == "來回":
    b_org = c1.selectbox("起點", ALL_CITIES, index=IDX_TPE)
    d2_dt = c1.date_input("去程", value=date(2026, 6, 11))
    b_dst = c2.selectbox("終點", ALL_CITIES, index=IDX_PRG)
    d3_dt = c2.date_input("回程", value=date(2026, 6, 25))
    d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
else:
    d2os = c1.selectbox("D2 出發", ALL_CITIES, index=IDX_TPE); d2_dt = c1.date_input("D2 日期", value=date(2026, 6, 11))
    d2ds = c1.selectbox("D2 目的", ALL_CITIES, index=IDX_PRG)
    d3os = c2.selectbox("D3 出發", ALL_CITIES, index=IDX_FRA); d3_dt = c2.date_input("D3 日期", value=date(2026, 6, 25))
    d3ds = c2.selectbox("D3 目的", ALL_CITIES, index=IDX_TPE)
    d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

st.markdown("---")
cr1, cr4 = st.columns(2)
regs = cr1.multiselect("區域過濾", list(CI_HUBS.keys()))
flt = [f"{c} ({n})" for r in regs for c, n in CI_HUBS[r].items()] if regs else ALL_CITIES
d1_h = cr1.multiselect(f"📍 D1 起點 ({len(flt)})", options=flt, default=flt if regs else None)
d1_r = cr1.date_input("D1 日期", value=(date(2026, 6, 10),))
d4_h = cr4.multiselect("📍 D4 終點", options=flt, default=flt if regs else None)
d4_r = cr4.date_input("D4 日期", value=(date(2026, 6, 26),))

async def start_hunt():
    rid = str(uuid.uuid4()); st.session_state.run_id = rid
    st.session_state.debug_info = []
    d1_s, d1_e = get_safe_dates(d1_r); d4_s, d4_e = get_safe_dates(d4_r)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]
    tasks = []
    for h1r, h4r, d1, d4 in product(d1_h, d4_h, d1_list, d4_list):
        if d1 <= d2_dt and d4 >= d3_dt:
            l = [{"fromId": f"{h1r[:3]}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                 {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                 {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                 {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4r[:3]}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
            tasks.append((l, "BUSINESS", h1r[:3], h4r[:3], d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks: return
    bar = st.progress(0); status = st.empty(); final_res = []
    async with httpx.AsyncClient(timeout=45.0) as client:
        sem = asyncio.Semaphore(workers)
        coros = [fetch_api(client, sem, t, rid) for t in tasks]
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != rid: return
            r = await coro
            if r: final_res.append(r)
            bar.progress((i+1)/len(tasks), text=f"⚡ 獵殺中: {i+1}/{len(tasks)} | 尋獲: {len(final_res)}")

    st.session_state.valid_offers = sorted(final_res, key=lambda x: x['total'])
    if email_on and st.session_state.valid_offers: send_detailed_email(st.session_state.valid_offers, 200000)
    st.session_state.run_id = None; st.rerun()

if st.button("🚀 啟動極速獵殺 (v38.4+)", use_container_width=True):
    st.session_state.valid_offers = []; asyncio.run(start_hunt())

if st.session_state.valid_offers:
    st.markdown("---")
    st.dataframe(pd.DataFrame([{ "總價": f"{r['total']:,}", "路線": f"{get_name(r['h1'])}➔{get_name(r['h4'])}", "日期": f"{r['d1']}~{r['d4']}", "航班": "|".join(r['legs'])} for r in st.session_state.valid_offers]), use_container_width=True)

# 🛡️ 開發者偵錯面板 (如果跑不出票，看這裡)
if st.session_state.debug_info:
    with st.expander("🔍 偵錯日誌 (若搜尋不到票請點開查看)"):
        for log in st.session_state.debug_info[-20:]: st.write(log)
