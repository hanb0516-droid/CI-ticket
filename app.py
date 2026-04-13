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
# 0. UI 初始化 & ULTRA 樣式
# ==========================================
st.set_page_config(page_title="Flight Actuary | ULTRA FINAL PRO", page_icon="🚀", layout="wide")
BLACKBOX_FILE = "blackbox_log.jsonl"

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
    st.error("🚨 找不到 Secrets 配置，請檢查 Streamlit 設定。"); st.stop()

# 狀態鎖定
if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "quota_remaining" not in st.session_state: st.session_state.quota_remaining = "12,000 (Ultra)"

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

# --- 工具函數 ---
def on_region_change_d1():
    if st.session_state.input_d1_reg:
        st.session_state.input_d1_hubs = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()]
    else: st.session_state.input_d1_hubs = []

def on_region_change_d4():
    if not st.session_state.get("input_sync_hubs", True):
        if st.session_state.input_d4_reg:
            st.session_state.input_d4_hubs = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()]
        else: st.session_state.input_d4_hubs = []

def parse_date_range_obj(date_val):
    if isinstance(date_val, (tuple, list)):
        if len(date_val) >= 2: return date_val[0], date_val[-1]
        elif len(date_val) == 1: return date_val[0], date_val[0]
    return date_val, date_val

def send_email_report(res_list, d2_o, d2_d, d3_o, d3_d, d2_dt, d3_dt):
    if not SENDER or not PWD or not RECEIVER or not res_list: return False
    res_list.sort(key=lambda x: x['total'])
    
    # 🎯 標題優化：找出核心行程中非台灣的地點
    target_city = next((city for city in [d2_d, d3_o] if city not in ["TPE", "KHH"]), "歐洲/北美")
    
    html_body = f"""
    <html><body>
        <h2>學長，ULTRA 任務完畢！目標：{target_city}</h2>
        <p>行程關鍵：<b>{d2_o} ➔ {d2_d} | {d3_o} ➔ {d3_d}</b></p>
        <p>日期：{d2_dt} 至 {d3_dt}</p>
        <hr>
        <p>以下為精選<b>獲利票 ({len(res_list)} 組)</b>，格式：總價 | 省下金額 | 行程明細</p>
        <pre style="font-size: 14px; line-height: 1.8;">
    """
    for r in res_list:
        diff = r['ref'] - r['total']
        html_body += f"💰 <b>{r['total']:,}</b> | 省 {diff:,} | {r['h1']} ({r['d1']}) ➔ {r['h4']} ({r['d4']})\n"
    
    html_body += "</pre><br><p>祝 旅途愉快！</p></body></html>"
    
    msg = MIMEMultipart()
    msg['From'], msg['To'] = SENDER, RECEIVER
    msg['Subject'] = f"✈️ [目標 {target_city}] 成功捕獲 {len(res_list)} 組獲利票"
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls(); server.login(SENDER, PWD); server.send_message(msg)
        return True
    except: return False

# ==========================================
# 1. API 引擎 (Ultra 狂暴核心)
# ==========================================
def fetch_booking_bundle(legs, cabin, h1="", h4="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    try:
        res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": c_map[cabin], "adults": "1", "currency_code": "TWD"}, timeout=25)
        rem = res.headers.get('x-ratelimit-requests-remaining')
        if rem: st.session_state.quota_remaining = rem
        if res.status_code == 200:
            raw = res.json()
            valid_res = []
            for offer in raw.get('data', {}).get('flightOffers', []):
                l_sum, is_ci = [], True
                for seg in offer.get('segments', []):
                    f_leg = seg.get('legs', [{}])[0]
                    car = (f_leg.get('flightInfo', {}).get('carrierInfo', {}).get('operatingCarrier') or 
                           f_leg.get('flightInfo', {}).get('carrierInfo', {}).get('marketingCarrier', '??'))
                    if car != "CI": is_ci = False; break
                    l_sum.append(f"{car}{f_leg.get('flightInfo', {}).get('flightNumber', '')}")
                if is_ci and len(l_sum) == 4:
                    valid_res.append({"total": offer.get('priceBreakdown', {}).get('total', {}).get('units', 0), "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
            if valid_res:
                valid_res.sort(key=lambda x: x['total'])
                return {"status": "success", "offer": valid_res[0]}
            return {"status": "success", "offer": None}
        elif res.status_code == 429: return {"status": "rate_limit"}
        elif res.status_code == 403: return {"status": "quota_exceeded"}
    except: pass
    return {"status": "error"}

# ==========================================
# 2. UI 面板
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary ULTRA FINAL</p>', unsafe_allow_html=True)
st.markdown(f'<div class="quota-box">🔥 <b>ULTRA 狂暴模式：</b> 剩餘額度：<span style="color:#ff4b4b;">{st.session_state.quota_remaining}</span></div>', unsafe_allow_html=True)

with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    st.radio("行程類型", ["來回", "多點進出"], horizontal=True, key="input_trip_type")
    
    c_d2, c_d3 = st.columns(2)
    if "來回" in st.session_state.input_trip_type:
        with c_d2: 
            st.selectbox("🛫 核心起點 (D2起/D3終)", ALL_FORMATTED_CITIES, index=0, key="input_base_org")
            st.date_input("D2 去程日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("🛬 核心終點 (D2終/D3起)", ALL_FORMATTED_CITIES, index=5, key="input_base_dst")
            st.date_input("D3 回程日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o = d3_d = st.session_state.input_base_org.split(" ")[0]
        d2_d = d3_o = st.session_state.input_base_dst.split(" ")[0]
    else:
        with c_d2:
            st.selectbox("🛫 D2 出發 (TPE)", ALL_FORMATTED_CITIES, index=0, key="input_d2_o")
            st.selectbox("🛬 D2 抵達 (PRG)", ALL_FORMATTED_CITIES, index=5, key="input_d2_d")
            st.date_input("D2 去程日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("🛫 D3 出發 (FRA)", ALL_FORMATTED_CITIES, index=10, key="input_d3_o")
            st.selectbox("🛬 D3 抵達 (TPE)", ALL_FORMATTED_CITIES, index=0, key="input_d3_d")
            st.date_input("D3 回程日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o, d2_d, d3_o, d3_d = st.session_state.input_d2_o.split(" ")[0], st.session_state.input_d2_d.split(" ")[0], st.session_state.input_d3_o.split(" ")[0], st.session_state.input_d3_d.split(" ")[0]

    st.markdown("---")
    st.subheader("🌍 外站雷達 (D1 / D4)")
    st.checkbox("👯 D1/D4 同步為同一站點", value=True, key="input_sync_hubs")

    c_r1, c_r4 = st.columns(2)
    with c_r1:
        st.multiselect("D1 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d1_reg", on_change=on_region_change_d1)
        d1_opt = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d1_reg else ALL_FORMATTED_CITIES
        st.multiselect("📍 D1 起點庫", d1_opt, key="input_d1_hubs")
        st.date_input("📅 D1 日期", value=(date(2026, 6, 10),), key="input_d1_dates")
    with c_r4:
        if st.session_state.input_sync_hubs:
            d4_final_hubs = st.session_state.input_d1_hubs; st.info("已同步 D1 站點")
        else:
            st.multiselect("D4 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d4_reg", on_change=on_region_change_d4)
            d4_opt = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d4_reg else ALL_FORMATTED_CITIES
            st.multiselect("📍 D4 終點庫", d4_opt, key="input_d4_hubs")
            d4_final_hubs = st.session_state.input_d4_hubs
        st.date_input("📅 D4 日期", value=(date(2026, 6, 26),), key="input_d4_dates")

    col_x, col_y = st.columns(2)
    with col_x: st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"], key="input_cabin")
    with col_y: st.number_input("基準預算 (直飛+亞洲)", value=200000, key="input_ref_total")
    st.checkbox("📧 完成後發送 Email (僅含獲利票)", value=True, key="input_email_on")

# --- 執行迴圈 ---
if not st.session_state.engine_running:
    if st.button("🔥 啟動火力全開獵殺", use_container_width=True):
        d1_s, d1_e = parse_date_range_obj(st.session_state.input_d1_dates)
        d4_s, d4_e = parse_date_range_obj(st.session_state.input_d4_dates)
        d1_ts = [d1_s + timedelta(days=i) for i in range((d1_e - d1_s).days + 1)]
        d4_ts = [d4_s + timedelta(days=i) for i in range((d4_e - d4_s).days + 1)]
        
        tasks = []
        for h1_r, h4_r in product(st.session_state.input_d1_hubs, d4_final_hubs):
            h1, h4 = h1_r.split(" ")[0], h4_r.split(" ")[0]
            for d1, d4 in product(d1_ts, d4_ts):
                if d1 <= st.session_state.input_d2_dt and d4 >= st.session_state.input_d3_dt:
                    l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2_o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d2_o}.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": st.session_state.input_d2_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_o}.AIRPORT", "toId": f"{d3_d}.AIRPORT", "date": st.session_state.input_d3_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    tasks.append((l, st.session_state.input_cabin, h1_r, h4_r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))
        if tasks:
            st.session_state.task_list, st.session_state.task_idx, st.session_state.valid_offers, st.session_state.engine_running = tasks, 0, [], True
            st.rerun()

if st.session_state.engine_running:
    total, curr = len(st.session_state.task_list), st.session_state.task_idx
    BATCH = 40
    st.progress(min(curr/total, 1.0) if total > 0 else 0.0, text=f"🚀 進度: {curr}/{total}")
    
    batch = st.session_state.task_list[curr : curr + BATCH]
    with ThreadPoolExecutor(max_workers=20) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5]): t for t in batch}
        for f in as_completed(futures):
            res = f.result()
            if res["status"] == "quota_exceeded": st.session_state.engine_running = False; st.stop()
            if res["status"] == "success" and res.get("offer"):
                o = res["offer"]
                o["ref"] = st.session_state.input_ref_total
                # 🛡️ 潔癖過濾：只存下獲利票
                if (o["ref"] - o["total"]) > 0: st.session_state.valid_offers.append(o)
    
    if curr + BATCH >= total:
        if st.session_state.input_email_on:
            send_email_report(st.session_state.valid_offers, d2_o, d2_d, d3_o, d3_d, st.session_state.input_d2_dt, st.session_state.input_d3_dt)
        st.session_state.engine_running = False; st.rerun()
    else: st.session_state.task_idx += BATCH; time.sleep(0.1); st.rerun()

# 展示
if not st.session_state.engine_running and st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    st.success(f"🎉 獵殺完畢！共捕獲 {len(res)} 組獲利票。")
    for r in res[:100]:
        diff = r['ref']-r['total']
        with st.expander(f"💰 {r['total']:,} | 🔥 省 {diff:,} | {r['h1']} ({r['d1']}) ➔ {r['h4']} ({r['d4']})"):
            st.write(f"航班：{' | '.join(r['legs'])}")
elif not st.session_state.engine_running and st.session_state.task_list:
    st.warning("📉 掃描結束，但本次結果皆為虧損票，已自動濾除。")
