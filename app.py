import streamlit as st
import requests
import json
import time
import os
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. UI 初始化
# ==========================================
st.set_page_config(page_title="Flight Actuary | Ultra 獵殺器", page_icon="🚀", layout="wide")
BLACKBOX_FILE = "blackbox_log.jsonl"

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-image: linear-gradient(rgba(15, 20, 35, 0.2), rgba(15, 20, 35, 0.5)), 
        url("https://images.unsplash.com/photo-1436491865332-7a61a109cc05?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important; background-position: center !important; background-attachment: fixed !important;
    }
    .custom-title {
        background: linear-gradient(45deg, #ff4b4b, #ff8c00); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 3rem; margin-bottom: -5px; text-shadow: 0px 4px 15px rgba(255, 75, 75, 0.3);
    }
    .quota-box {
        padding: 12px; background: rgba(255, 75, 75, 0.1); border-radius: 8px; border: 1px solid #ff4b4b; margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

# 🌍 華航站點庫
CI_GLOBAL_HUBS = {
    "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "港澳大陸": {"HKG": "香港", "MFM": "澳門", "PEK": "北京", "PVG": "上海浦東", "CAN": "廣州", "SZX": "深圳"},
    "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
    "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
    "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
}
ALL_FORMATTED_CITIES = [f"{code} ({name})" for region, cities in CI_GLOBAL_HUBS.items() for code, name in cities.items()]

# --- 核心邏輯：自動連動函數 ---
def on_region_change_d1():
    if st.session_state.input_d1_reg:
        # 選了區域，自動帶入該區域所有站點
        new_hubs = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()]
        st.session_state.input_d1_hubs = new_hubs
    else:
        # 區域清空，起點庫也清空
        st.session_state.input_d1_hubs = []

def on_region_change_d4():
    if not st.session_state.input_sync_hubs:
        if st.session_state.input_d4_reg:
            new_hubs = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()]
            st.session_state.input_d4_hubs = new_hubs
        else:
            st.session_state.input_d4_hubs = []

# --- 初始化狀態 ---
if "input_d1_hubs" not in st.session_state: st.session_state.input_d1_hubs = []
if "input_d4_hubs" not in st.session_state: st.session_state.input_d4_hubs = []
if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "quota_remaining" not in st.session_state: st.session_state.quota_remaining = "12,000 (Ultra)"

# --- 密鑰讀取 ---
try:
    BOOKING_API_KEY = st.secrets["BOOKING_API_KEY"]
    SENDER = st.secrets.get("EMAIL_SENDER")
    PWD = st.secrets.get("EMAIL_PASSWORD")
    RECEIVER = st.secrets.get("EMAIL_RECEIVER")
except KeyError:
    st.error("🚨 找不到 Secrets 配置。"); st.stop()

# --- 工具函數 ---
def get_city_index(code):
    for i, city in enumerate(ALL_FORMATTED_CITIES):
        if city.startswith(code): return i
    return 0

def parse_date_range(date_val):
    if isinstance(date_val, (tuple, list)):
        if len(date_val) == 2: return date_val[0], date_val[1]
        elif len(date_val) == 1: return date_val[0], date_val[0]
    return date_val, date_val

# ==========================================
# 1. API 引擎
# ==========================================
def fetch_booking_bundle(legs, cabin, title="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    for attempt in range(2):
        try:
            res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": c_map[cabin], "adults": "1", "currency_code": "TWD"}, timeout=30)
            rem = res.headers.get('x-ratelimit-requests-remaining')
            if rem: st.session_state.quota_remaining = rem
            if res.status_code == 200:
                raw = res.json()
                valid_res = []
                for offer in raw.get('data', {}).get('flightOffers', []):
                    l_sum = []
                    for seg in offer.get('segments', []):
                        f_leg = seg.get('legs', [{}])[0]
                        c_info = f_leg.get('flightInfo', {}).get('carrierInfo', {})
                        car = c_info.get('operatingCarrier') or c_info.get('marketingCarrier', '??')
                        num = f_leg.get('flightInfo', {}).get('flightNumber', '')
                        dep, arr = seg.get('departureAirport', {}).get('code', '???'), seg.get('arrivalAirport', {}).get('code', '???')
                        dt = seg.get('departureTime', '').replace('T', ' ')[:16]
                        if car != "CI": break
                        l_sum.append(f"**{car}{num}** | {dep} ➔ {arr} | {dt}")
                    if len(l_sum) == 4:
                        valid_res.append({"title": title, "total": offer.get('priceBreakdown', {}).get('total', {}).get('units', 0), "legs": l_sum, "d1": d1, "d4": d4})
                if valid_res:
                    valid_res.sort(key=lambda x: x['total'])
                    return {"status": "success", "offer": valid_res[0]}
                return {"status": "success", "offer": None}
            elif res.status_code == 429: time.sleep(3)
            elif res.status_code == 403: return {"status": "quota_exceeded"}
        except: pass
    return {"status": "error"}

# ==========================================
# 2. UI 面板
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary | ULTRA MODE</p>', unsafe_allow_html=True)
st.markdown(f'<div class="quota-box">🔥 <b>Ultra 模式：</b> 剩餘 Premium 額度：<span style="color:#ff4b4b;">{st.session_state.quota_remaining}</span></div>', unsafe_allow_html=True)

with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    st.radio("行程類型", ["來回", "多點"], horizontal=True, key="input_trip_type")
    
    c_d2, c_d3 = st.columns(2)
    if st.session_state.input_trip_type == "來回":
        with c_d2: 
            st.selectbox("🛫 起/終點", ALL_FORMATTED_CITIES, index=get_city_index("TPE"), key="input_base_org")
            st.date_input("D2 去程日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("🛬 中轉點", ALL_FORMATTED_CITIES, index=get_city_index("PRG"), key="input_base_dst")
            st.date_input("D3 回程日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o = d3_d = st.session_state.input_base_org.split(" ")[0]
        d2_d = d3_o = st.session_state.input_base_dst.split(" ")[0]
    else:
        with c_d2:
            st.selectbox("D2 出發", ALL_FORMATTED_CITIES, index=get_city_index("TPE"), key="input_d2_o")
            st.selectbox("D2 抵達", ALL_FORMATTED_CITIES, index=get_city_index("PRG"), key="input_d2_d")
            st.date_input("D2 日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("D3 出發", ALL_FORMATTED_CITIES, index=get_city_index("FRA"), key="input_d3_o")
            st.selectbox("D3 抵達", ALL_FORMATTED_CITIES, index=get_city_index("TPE"), key="input_d3_d")
            st.date_input("D3 日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o, d2_d, d3_o, d3_d = st.session_state.input_d2_o.split(" ")[0], st.session_state.input_d2_d.split(" ")[0], st.session_state.input_d3_o.split(" ")[0], st.session_state.input_d3_d.split(" ")[0]

    st.markdown("---")
    st.subheader("🌍 外站雷達 (D1 / D4)")
    st.checkbox("👯 D1/D4 同步為同一外站點", value=True, key="input_sync_hubs")

    c_r1, c_r4 = st.columns(2)
    with c_r1:
        # 💡 加入 on_change 回呼，實現自動連動
        st.multiselect("D1 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d1_reg", on_change=on_region_change_d1)
        d1_options = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d1_reg else ALL_FORMATTED_CITIES
        st.multiselect("📍 D1 起點庫", d1_options, key="input_d1_hubs")
        st.date_input("📅 D1 日期", value=(date(2026, 6, 10),), key="input_d1_dates")

    with c_r4:
        if st.session_state.input_sync_hubs:
            st.info("💡 已與 D1 同步")
            d4_final_hubs = st.session_state.input_d1_hubs
        else:
            st.multiselect("D4 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d4_reg", on_change=on_region_change_d4)
            d4_options = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d4_reg else ALL_FORMATTED_CITIES
            st.multiselect("📍 D4 終點庫", d4_options, key="input_d4_hubs")
            d4_final_hubs = st.session_state.input_d4_hubs
        st.date_input("📅 D4 日期", value=(date(2026, 6, 26),), key="input_d4_dates")

    st.markdown("---")
    st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"], key="input_cabin")
    st.number_input("基準預算 (TWD)", value=200000, key="input_ref_total")

# --- 執行迴圈 (狂暴模式) ---
if not st.session_state.engine_running:
    if st.button("🔥 啟動火力全開獵殺", use_container_width=True):
        d1_s, d1_e = parse_date_range(st.session_state.input_d1_dates)
        d4_s, d4_e = parse_date_range(st.session_state.input_d4_dates)
        d1_ts = [d1_s + timedelta(days=i) for i in range((d1_e - d1_s).days + 1)]
        d4_ts = [d4_s + timedelta(days=i) for i in range((d4_e - d4_s).days + 1)]
        tasks = []
        for h1_r, h4_r in product(st.session_state.input_d1_hubs, d4_final_hubs if not st.session_state.input_sync_hubs else st.session_state.input_d1_hubs):
            h1, h4 = h1_r.split(" ")[0], h4_r.split(" ")[0]
            for d1, d4 in product(d1_ts, d4_ts):
                if d1 <= st.session_state.input_d2_dt and d4 >= st.session_state.input_d3_dt:
                    l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2_o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d2_o}.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": st.session_state.input_d2_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_o}.AIRPORT", "toId": f"{d3_d}.AIRPORT", "date": st.session_state.input_d3_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    tasks.append((l, st.session_state.input_cabin, f"{h1_r} ➔ {h4_r}", d1, d4))
        if tasks:
            st.session_state.task_list, st.session_state.task_idx = tasks, 0
            st.session_state.valid_offers, st.session_state.engine_running = [], True
            st.rerun()

if st.session_state.engine_running:
    total, curr = len(st.session_state.task_list), st.session_state.task_idx
    BATCH = 20
    st.progress(min(curr/total, 1.0) if total > 0 else 0.0, text=f"🚀 獵殺進度: {curr}/{total}")
    batch = st.session_state.task_list[curr : curr + BATCH]
    with ThreadPoolExecutor(max_workers=10) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4]): t for t in batch}
        for f in as_completed(futures):
            res = f.result()
            if res["status"] == "quota_exceeded": st.session_state.engine_running = False; st.stop()
            if res["status"] == "success" and res.get("offer"):
                o = res["offer"]
                o["ref"] = st.session_state.input_ref_total
                st.session_state.valid_offers.append(o)
    if curr + BATCH >= total:
        st.session_state.engine_running = False; st.rerun()
    else:
        st.session_state.task_idx += BATCH
        time.sleep(0.5); st.rerun()

# 展示結果
if not st.session_state.engine_running and st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    for r in res[:100]:
        with st.expander(f"💰 {r['total']:,} | 省 {r['ref']-r['total']:,} | {r['title']} ({r['d1']})"):
            for leg in r['legs']: st.write(leg)
