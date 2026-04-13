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
    st.error("🚨 找不到 API 金鑰！請於 Secrets 中設定。"); st.stop()

# --- 初始化 Session State ---
if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []

# 🌍 華航站點字典
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
# 📧 郵件功能
# ==========================================
def send_email_report(res_list):
    if not SENDER or not PWD or not RECEIVER: return False
    res_list.sort(key=lambda x: x['total'])
    txt_content = "\n".join([f"💰 {r['total']:,} TWD | 🔥 省 {r.get('ref', 200000)-r['total']:,} | {r['title']} (D1:{r['d1']} / D4:{r['d4']})" for r in res_list])
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = SENDER, RECEIVER, f"✈️ 獵殺報告 - 捕獲 {len(res_list)} 組"
    msg.attach(MIMEText("詳細清單請見附件。", 'plain'))
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
# 1. API 引擎 (Booking.com Multi-Stops)
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
# 2. UI 面板 (記憶狀態與邏輯優化)
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)

# 🚀 參數設定區
with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    st.radio("行程類型", ["來回 (Round-trip)", "多點 (Multi-city)"], horizontal=True, key="input_trip_type")
    
    c_d2, c_d3 = st.columns(2)
    if "來回" in st.session_state.input_trip_type:
        with c_d2: 
            st.selectbox("🛫 起/終點 (TPE)", ALL_FORMATTED_CITIES, index=get_city_index("TPE"), key="input_base_org")
            st.date_input("D2 去程日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("🛬 中轉點 (如 PRG)", ALL_FORMATTED_CITIES, index=get_city_index("PRG"), key="input_base_dst")
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
    sync_hubs = st.checkbox("👯 D1/D4 為同一個外站點", value=True, key="input_sync_hubs")

    c_r1, c_r4 = st.columns(2)
    # D1 設定
    with c_r1:
        st.multiselect("D1 區域過濾 (不選則顯示全部)", list(CI_GLOBAL_HUBS.keys()), key="input_d1_reg")
        d1_options = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d1_reg else ALL_FORMATTED_CITIES
        st.multiselect("📍 D1 起點庫", d1_options, default=d1_options[:2] if d1_options else [], key="input_d1_hubs")
        st.date_input("📅 D1 日期區間", value=(date(2026, 6, 10),), key="input_d1_dates")

    # D4 設定
    with c_r4:
        if st.session_state.input_sync_hubs:
            st.info("💡 已與 D1 同步，無需重複選擇。")
            d4_final_hubs = st.session_state.input_d1_hubs
        else:
            st.multiselect("D4 區域過濾 (不選則顯示全部)", list(CI_GLOBAL_HUBS.keys()), key="input_d4_reg")
            d4_options = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d4_reg else ALL_FORMATTED_CITIES
            st.multiselect("📍 D4 終點庫", d4_options, default=d4_options[:2] if d4_options else [], key="input_d4_hubs")
            d4_final_hubs = st.session_state.input_d4_hubs
        st.date_input("📅 D4 日期區間", value=(date(2026, 6, 26),), key="input_d4_dates")

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1: st.selectbox("艙等 (D2/D3 基準)", ["商務艙", "豪經艙", "經濟艙"], key="input_cabin")
    with col2: st.number_input("基準預算 (TPE直飛價 + 亞洲段)", value=200000, step=5000, key="input_ref_total")
    st.checkbox("📧 完成後將結果 TXT 寄送到信箱", value=True, key="input_email_on")

# --- 執行按鈕 ---
if not st.session_state.engine_running:
    if st.button("🚀 啟動獵殺掃描", use_container_width=True):
        d1_s, d1_e = parse_date_range(st.session_state.input_d1_dates)
        d4_s, d4_e = parse_date_range(st.session_state.input_d4_dates)
        d1_dates = [d1_s + timedelta(days=i) for i in range((d1_e - d1_s).days + 1)]
        d4_dates = [d4_s + timedelta(days=i) for i in range((d4_e - d4_s).days + 1)]
        
        # 🛡️ 邏輯排雷：預先檢查日期
        tasks = []
        error_logs = []
        for h1_raw, h4_raw in product(st.session_state.input_d1_hubs, d4_final_hubs):
            h1, h4 = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 > st.session_state.input_d2_dt: 
                    error_logs.append(f"❌ 衝突: D1({d1}) 不可比 D2({st.session_state.input_d2_dt}) 晚")
                    continue
                if d4 < st.session_state.input_d3_dt:
                    error_logs.append(f"❌ 衝突: D4({d4}) 不可比 D3({st.session_state.input_d3_dt}) 早")
                    continue
                
                l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2_o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, 
                     {"fromId": f"{d2_o}.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": st.session_state.input_d2_dt.strftime("%Y-%m-%d")}, 
                     {"fromId": f"{d3_o}.AIRPORT", "toId": f"{d3_d}.AIRPORT", "date": st.session_state.input_d3_dt.strftime("%Y-%m-%d")}, 
                     {"fromId": f"{d3_d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                tasks.append((l, st.session_state.input_cabin, f"{h1_raw} ➔ {h4_raw}", d1, d4))
        
        if not tasks:
            st.error("⚠️ 無法生成任務！請檢查日期邏輯是否正確。")
            if error_logs: st.warning("\n".join(list(set(error_logs))[:3]))
        else:
            st.session_state.task_list, st.session_state.task_idx = tasks, 0
            st.session_state.valid_offers, st.session_state.engine_running = [], True
            if os.path.exists(BLACKBOX_FILE): os.remove(BLACKBOX_FILE)
            st.rerun()

# --- 接力執行 (Rerun Loop) ---
if st.session_state.engine_running:
    total, curr = len(st.session_state.task_list), st.session_state.task_idx
    BATCH = 15
    batch_tasks = st.session_state.task_list[curr : curr + BATCH]
    
    st.progress(curr/total, text=f"🔥 任務執行中: {curr}/{total} | 已收穫: {len(st.session_state.valid_offers)}")
    
    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], f"{t[2]}", t[3], t[4]): t for t in batch_tasks}
        for f in as_completed(futures):
            res = f.result()
            if res["status"] == "quota_exceeded": 
                st.error("🚨 API 額度用盡！將寄出目前已找到的結果。")
                st.session_state.task_idx = total # 強制結束
                break
            if res["status"] == "success" and res.get("offer"):
                o = res["offer"]
                o["ref"] = st.session_state.input_ref_total
                st.session_state.valid_offers.append(o)
                with open(BLACKBOX_FILE, "a", encoding="utf-8") as file:
                    file.write(json.dumps(o, ensure_ascii=False) + "\n")

    if curr + BATCH >= total:
        if st.session_state.input_email_on and st.session_state.valid_offers:
            send_email_report(st.session_state.valid_offers)
            st.toast("📨 搜尋完畢，報告已寄至信箱！")
        st.session_state.engine_running = False
        st.rerun()
    else:
        st.session_state.task_idx += BATCH
        time.sleep(1); st.rerun()

# --- 4. 戰果展示 ---
if not st.session_state.engine_running and st.session_state.valid_offers:
    st.markdown("---")
    st.success(f"🎉 獵殺完畢！共捕獲 {len(st.session_state.valid_offers)} 組神票。")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    
    df_export = pd.DataFrame([{ "總價": r['total'], "價差": r['ref']-r['total'], "航線": r['title'], "D1": r['d1'] } for r in res])
    st.download_button("📥 下載完整 CSV 戰果", df_export.to_csv(index=False).encode('utf-8-sig'), "Flight_Results.csv", "text/csv")

    for r in res[:50]:
        diff = r['ref'] - r['total']
        with st.expander(f"💰 {r['total']:,} | 🔥 狂省 {diff:,} | {r['title']} (D1:{r['d1']})"):
            for leg in r['legs']: st.write(leg)
