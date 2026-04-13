import streamlit as st
import requests
import json
import time
import os
import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. UI 初始化 (ULTRA 旗艦樣式)
# ==========================================
st.set_page_config(page_title="Flight Actuary | AUTO-BENCHMARK FINAL", page_icon="🏎️", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-image: linear-gradient(rgba(10, 15, 30, 0.4), rgba(10, 15, 30, 0.6)), 
        url("https://images.unsplash.com/photo-1436491865332-7a61a109cc05?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important; background-position: center !important; background-attachment: fixed !important;
    }
    .custom-title {
        background: linear-gradient(45deg, #ff4b4b, #ff8c00); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 3.5rem; text-shadow: 0px 5px 15px rgba(255, 75, 75, 0.4);
    }
    .quota-box {
        padding: 15px; background: rgba(255, 75, 75, 0.15); border-radius: 12px; border: 2px solid #ff4b4b; margin-bottom: 25px;
    }
</style>
""", unsafe_allow_html=True)

try:
    BOOKING_API_KEY = st.secrets["BOOKING_API_KEY"]
    SENDER = st.secrets.get("EMAIL_SENDER")
    PWD = st.secrets.get("EMAIL_PASSWORD")
    RECEIVER = st.secrets.get("EMAIL_RECEIVER")
except KeyError:
    st.error("🚨 Secrets 配置有誤！"); st.stop()

if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "quota_remaining" not in st.session_state: st.session_state.quota_remaining = "12,000 (Ultra)"
if "ref_price" not in st.session_state: st.session_state.ref_price = 0

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

def on_region_change_d1():
    if st.session_state.input_d1_reg:
        st.session_state.input_d1_hubs = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()]
    else: st.session_state.input_d1_hubs = []

def send_email_report(res_list, d2_o, d2_d, d3_o, d3_d, d2_dt, d3_dt, ref):
    if not res_list: return False
    res_list.sort(key=lambda x: x['total'])
    targets = [city for city in [d2_d, d3_o] if city not in ["TPE", "KHH"]]
    target_str = "/".join(list(dict.fromkeys(targets))) if targets else "海外"
    
    html = f"""
    <html><body>
        <h2 style="color: #ff4b4b;">✈️ [目標 {target_str}] 獲利報告</h2>
        <p>台北直飛基準價：<b>{ref:,} TWD</b></p>
        <p>核心行程：{d2_o} ➔ {d2_d} | 去程：{d2_dt} | 回程：{d3_dt}</p>
        <hr>
        <table border="1" cellpadding="8" style="border-collapse: collapse; width: 100%;">
            <tr style="background-color: #f2f2f2;"><th>總票價</th><th>🔥 實省</th><th>外站路徑</th></tr>
    """
    for r in res_list:
        diff = ref - r['total']
        html += f"<tr><td><b>{r['total']:,}</b></td><td style='color:red;'>{diff:,}</td><td>{r['h1']}({r['d1']})➔{r['h4']}({r['d4']})</td></tr>"
    html += "</table></body></html>"
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = SENDER, RECEIVER, f"✈️ [目標 {target_str}] 捕獲 {len(res_list)} 組獲利票 (直飛對標)"
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(SENDER, PWD); s.send_message(msg)
        return True
    except: return False

# ==========================================
# 1. API 引擎 (增加基準價抓取功能)
# ==========================================
def fetch_booking_bundle(legs, cabin, h1="", h4="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    try:
        res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=20)
        rem = res.headers.get('x-ratelimit-requests-remaining')
        if rem: st.session_state.quota_remaining = rem
        if res.status_code == 200:
            raw = res.json()
            valid = []
            for offer in raw.get('data', {}).get('flightOffers', []):
                l_sum, is_ci = [], True
                for seg in offer.get('segments', []):
                    car = seg.get('legs', [{}])[0].get('flightInfo', {}).get('carrierInfo', {}).get('operatingCarrier') or '??'
                    if car != "CI": is_ci = False; break
                    l_sum.append(f"{car}{seg.get('legs', [{}])[0].get('flightInfo', {}).get('flightNumber', '')}")
                if is_ci and len(l_sum) == (4 if h1 else 2): # 外站是4段，直飛是2段
                    valid.append({"total": offer.get('priceBreakdown', {}).get('total', {}).get('units', 0), "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
            if valid: return sorted(valid, key=lambda x: x['total'])[0]
    except: pass
    return None

# ==========================================
# 2. UI 佈局
# ==========================================
st.markdown('<p class="custom-title">✈️ ULTRA AUTO-BENCHMARK</p>', unsafe_allow_html=True)
st.markdown(f'<div class="quota-box">🏎️ <b>極限模式：</b> 剩餘額度：{st.session_state.quota_remaining} | 🎯 目前基準：{st.session_state.ref_price:,} TWD</div>', unsafe_allow_html=True)

with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    st.radio("模式", ["來回", "多點進出"], horizontal=True, key="input_trip_type")
    c1, c2 = st.columns(2)
    if "來回" in st.session_state.input_trip_type:
        with c1: 
            st.selectbox("🛫 台北 (TPE/KHH)", ALL_FORMATTED_CITIES, index=0, key="input_base_org")
            st.date_input("D2 日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c2:
            st.selectbox("🛬 目的地 (如 PRG)", ALL_FORMATTED_CITIES, index=5, key="input_base_dst")
            st.date_input("D3 日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o, d2_d, d3_o, d3_d = st.session_state.input_base_org.split(" ")[0], st.session_state.input_base_dst.split(" ")[0], st.session_state.input_base_dst.split(" ")[0], st.session_state.input_base_org.split(" ")[0]
    else:
        with c1:
            st.selectbox("🛫 D2 出發", ALL_FORMATTED_CITIES, index=0, key="input_d2_o")
            st.selectbox("🛬 D2 抵達", ALL_FORMATTED_CITIES, index=5, key="input_d2_d")
            st.date_input("D2 日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c2:
            st.selectbox("🛫 D3 出發", ALL_FORMATTED_CITIES, index=10, key="input_d3_o")
            st.selectbox("🛬 D3 抵達", ALL_FORMATTED_CITIES, index=0, key="input_d3_d")
            st.date_input("D3 日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o, d2_d, d3_o, d3_d = st.session_state.input_d2_o.split(" ")[0], st.session_state.input_d2_d.split(" ")[0], st.session_state.input_d3_o.split(" ")[0], st.session_state.input_d3_d.split(" ")[0]

    st.markdown("---")
    st.subheader("🌍 外站雷達 (D1 / D4)")
    st.checkbox("👯 D1/D4 同步為同一站點", value=True, key="input_sync")
    cr1, cr4 = st.columns(2)
    with cr1:
        st.multiselect("D1 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d1_reg", on_change=on_region_change_d1)
        d1_opt = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d1_reg else ALL_FORMATTED_CITIES
        st.multiselect("📍 D1 起點", d1_opt, key="input_d1_hubs")
        st.date_input("📅 D1 日期", value=(date(2026, 6, 10),), key="input_d1_dates")
    with cr4:
        d4_hubs = st.session_state.input_d1_hubs if st.session_state.input_sync else st.multiselect("📍 D4 終點", ALL_FORMATTED_CITIES, key="input_d4_hubs")
        if st.session_state.input_sync: st.info("已同步 D1")
        st.date_input("📅 D4 日期", value=(date(2026, 6, 26),), key="input_d4_dates")

    cab_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    st.selectbox("艙等", list(cab_map.keys()), key="input_cabin")
    st.checkbox("自動抓取當前直飛價作為基準", value=True, key="input_auto_ref")
    st.number_input("手動基準預算 (若關閉自動)", value=200000, key="input_manual_ref")

# --- 核心執行 ---
if not st.session_state.engine_running:
    if st.button("🚀 啟動自動對標獵殺", use_container_width=True):
        d1_in, d4_in = st.session_state.input_d1_dates, st.session_state.input_d4_dates
        d1_s, d1_e = (d1_in[0], d1_in[-1]) if isinstance(d1_in, (list, tuple)) else (d1_in, d1_in)
        d4_s, d4_e = (d4_in
