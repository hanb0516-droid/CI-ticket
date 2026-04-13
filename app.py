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
# 0. 介面與資料庫初始化
# ==========================================
st.set_page_config(page_title="Flight Actuary | 華航外站獵殺器", page_icon="✈️", layout="wide")
BLACKBOX_FILE = "blackbox_log.jsonl"

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-image: linear-gradient(rgba(15, 20, 35, 0.2), rgba(15, 20, 35, 0.5)), 
        url("https://images.unsplash.com/photo-1436491865332-7a61a109cc05?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important; background-position: center !important; background-attachment: fixed !important;
    }
    [data-testid="stExpander"] {
        background-color: rgba(20, 35, 55, 0.6) !important; backdrop-filter: blur(15px) !important;
        border: 1px solid rgba(255, 255, 255, 0.25) !important; border-radius: 12px !important;
        box-shadow: 0 10px 40px 0 rgba(0, 0, 0, 0.5) !important; margin-bottom: 15px;
    }
    .custom-title {
        background: linear-gradient(45deg, #ffffff, #4da8da); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 3rem; margin-bottom: -5px; text-shadow: 0px 4px 10px rgba(0,0,0,0.5);
    }
    .live-hit {
        padding: 12px; border-left: 6px solid #00e676; background: rgba(0, 230, 118, 0.15); 
        margin-bottom: 12px; border-radius: 8px; color: #ffffff; font-weight: 600; backdrop-filter: blur(5px);
    }
</style>
""", unsafe_allow_html=True)

try:
    BOOKING_API_KEY = st.secrets["BOOKING_API_KEY"]
    SENDER = st.secrets.get("EMAIL_SENDER")
    PWD = st.secrets.get("EMAIL_PASSWORD")
    RECEIVER = st.secrets.get("EMAIL_RECEIVER")
except KeyError:
    st.error("🚨 找不到 API 金鑰！"); st.stop()

# --- 初始化 Session State (核心狀態控管) ---
if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "quota_dead" not in st.session_state: st.session_state.quota_dead = False

# 🌍 華航站點庫
CI_GLOBAL_HUBS = {
    "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光", "ROR": "帛琉"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "TAK": "高松", "HIJ": "廣島", "KOJ": "鹿兒島", "KMQ": "小松", "TOY": "富山", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "港澳大陸": {"HKG": "香港", "MFM": "澳門", "PEK": "北京", "PVG": "上海浦東", "SHA": "上海虹橋", "CAN": "廣州", "SZX": "深圳", "XMN": "廈門", "CTU": "成都", "CKG": "重慶"},
    "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
    "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
    "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
}
ALL_FORMATTED_CITIES = [f"{code} ({name})" for region, cities in CI_GLOBAL_HUBS.items() for code, name in cities.items()]

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
# 📧 郵件發送功能
# ==========================================
def send_email_report(res_list):
    if not SENDER or not PWD or not RECEIVER: return
    lines = []
    res_list.sort(key=lambda x: x['total'])
    for r in res_list:
        diff = r.get("ref", 200000) - r['total']
        lines.append(f"💰 {r['total']:,} TWD | 🔥 狂省 {diff:,} | {r['title']} (D1:{r['d1']} / D4:{r['d4']})")
    txt_content = "\n".join(lines)
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = SENDER, RECEIVER, f"✈️ 華航獵殺完畢 - 找到 {len(res_list)} 組"
    msg.attach(MIMEText(f"任務完成，明細見附件。", 'plain'))
    att = MIMEBase('application', 'octet-stream')
    att.set_payload(txt_content.encode('utf-8'))
    encoders.encode_base64(att)
    att.add_header('Content-Disposition', f"attachment; filename=Flight_Results.txt")
    msg.attach(att)
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls(); server.login(SENDER, PWD); server.send_message(msg)
        return True
    except: return False

# ==========================================
# 1. API 引擎
# ==========================================
def fetch_booking_bundle(legs, cabin, title="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    try:
        res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": c_map[cabin], "adults": "1", "currency_code": "TWD"}, timeout=30)
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
        elif res.status_code in [403, 429]: return {"status": "quota_exceeded"}
    except: pass
    return {"status": "error"}

# ==========================================
# 2. UI 面板 (記憶力增強型)
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)

# 🚀 輸入區：使用 key 鎖定狀態
with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    # 使用 key 確保重整後不會跳回預設值
    st.radio("模式", ["來回", "多點"], horizontal=True, key="input_trip_type")
    
    c_d2, c_d3 = st.columns(2)
    if st.session_state.input_trip_type == "來回":
        with c_d2: 
            st.selectbox("🛫 起/終點", ALL_FORMATTED_CITIES, index=get_city_index("TPE"), key="input_base_org")
            st.date_input("D2 日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("🛬 中轉點", ALL_FORMATTED_CITIES, index=get_city_index("PRG"), key="input_base_dst")
            st.date_input("D3 日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o = d3_d = st.session_state.input_base_org.split(" ")[0]
        d2_d = d3_o = st.session_state.input_base_dst.split(" ")[0]
    else:
        with c_d2:
            st.selectbox("D2出發", ALL_FORMATTED_CITIES, index=get_city_index("TPE"), key="input_d2_o")
            st.selectbox("D2抵達", ALL_FORMATTED_CITIES, index=get_city_index("PRG"), key="input_d2_d")
            st.date_input("D2日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("D3出發", ALL_FORMATTED_CITIES, index=get_city_index("FRA"), key="input_d3_o")
            st.selectbox("D3抵達", ALL_FORMATTED_CITIES, index=get_city_index("TPE"), key="input_d3_d")
            st.date_input("D3日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o = st.session_state.input_d2_o.split(" ")[0]
        d2_d = st.session_state.input_d2_d.split(" ")[0]
        d3_o = st.session_state.input_d3_o.split(" ")[0]
        d3_d = st.session_state.input_d3_d.split(" ")[0]

    with st.expander("🌍 外站雷達設定 (D1/D4)"):
        c_r1, c_r4 = st.columns(2)
        with c_r1:
            st.multiselect("D1 區域", list(CI_GLOBAL_HUBS.keys()), default=["港澳大陸"], key="input_d1_reg")
            d1_list = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()]
            st.multiselect("📍 D1 起點", d1_list, default=d1_list[:2] if d1_list else [], key="input_d1_hubs")
            st.date_input("📅 D1 日期", value=(date(2026, 6, 10),), key="input_d1_dates")
        with c_r4:
            st.multiselect("D4 區域", list(CI_GLOBAL_HUBS.keys()), default=["港澳大陸"], key="input_d4_reg")
            d4_list = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()]
            st.multiselect("📍 D4 終點", d4_list, default=d4_list[:2] if d4_list else [], key="input_d4_hubs")
            st.date_input("📅 D4 日期", value=(date(2026, 6, 26),), key="input_d4_dates")

    st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"], key="input_cabin")
    st.number_input("基準總預算", value=200000, key="input_ref_total")
    st.checkbox("📧 完成後寄送 Email", value=True, key="input_email_on")

# --- 啟動與接力執行 ---
if not st.session_state.engine_running:
    if st.button("🚀 啟動地毯式掃描", use_container_width=True):
        d1_s, d1_e = parse_date_range(st.session_state.input_d1_dates)
        d4_s, d4_e = parse_date_range(st.session_state.input_d4_dates)
        d1_dates = [d1_s + timedelta(days=i) for i in range((d1_e - d1_s).days + 1)]
        d4_dates = [d4_s + timedelta(days=i) for i in range((d4_e - d4_s).days + 1)]
        
        tasks = []
        for h1_raw, h4_raw in product(st.session_state.input_d1_hubs, st.session_state.input_d4_hubs):
            h1, h4 = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 <= st.session_state.input_d2_dt and d4 >= st.session_state.input_d3_dt:
                    l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2_o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d2_o}.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": st.session_state.input_d2_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_o}.AIRPORT", "toId": f"{d3_d}.AIRPORT", "date": st.session_state.input_d3_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    tasks.append((l, st.session_state.input_cabin, f"{h1_raw} ➔ {h4_raw}", d1, d4))
        
        if tasks:
            st.session_state.task_list, st.session_state.task_idx = tasks, 0
            st.session_state.valid_offers, st.session_state.engine_running = [], True
            if os.path.exists(BLACKBOX_FILE): os.remove(BLACKBOX_FILE)
            st.rerun()

# 接力執行中 UI
if st.session_state.engine_running:
    total, curr = len(st.session_state.task_list), st.session_state.task_idx
    BATCH = 15
    batch_tasks = st.session_state.task_list[curr : curr + BATCH]
    
    st.progress(curr/total, text=f"🔥 獵殺進度: {curr}/{total} | 已收穫: {len(st.session_state.valid_offers)}")
    
    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3]): t for t in batch_tasks}
        for f in as_completed(futures):
            res = f.result()
            if res["status"] == "quota_exceeded": st.session_state.quota_dead = True; break
            if res["status"] == "success" and res.get("offer"):
                o = res["offer"]
                o["ref"] = st.session_state.input_ref_total
                st.session_state.valid_offers.append(o)
                with open(BLACKBOX_FILE, "a", encoding="utf-8") as file:
                    file.write(json.dumps(o, ensure_ascii=False) + "\n")

    if st.session_state.quota_dead or (curr + BATCH >= total):
        if st.session_state.input_email_on and st.session_state.valid_offers:
            send_email_report(st.session_state.valid_offers)
        st.session_state.engine_running = False
        st.rerun()
    else:
        st.session_state.task_idx += BATCH
        time.sleep(1); st.rerun()

# ==========================================
# 4. 戰果展示
# ==========================================
if not st.session_state.engine_running and st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    
    # 下載按鈕
    df_export = pd.DataFrame([{ "總價": r['total'], "省": r['ref']-r['total'], "航線": r['title'], "D1": r['d1'] } for r in res])
    st.download_button("📥 下載完整 CSV 戰果", df_export.to_csv(index=False).encode('utf-8-sig'), "Flight_Results.csv", "text/csv")

    for r in res[:50]:
        diff = r['ref'] - r['total']
        with st.expander(f"💰 {r['total']:,} | 🔥 狂省 {diff:,} | {r['title']} (D1:{r['d1']})"):
            for leg in r['legs']: st.write(leg)
