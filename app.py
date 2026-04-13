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
# 0. 介面與狀態初始化
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
</style>
""", unsafe_allow_html=True)

try:
    BOOKING_API_KEY = st.secrets["BOOKING_API_KEY"]
    SENDER = st.secrets.get("EMAIL_SENDER")
    PWD = st.secrets.get("EMAIL_PASSWORD")
    RECEIVER = st.secrets.get("EMAIL_RECEIVER")
except KeyError:
    st.error("🚨 找不到 API 金鑰！請確認 Secrets 設定。"); st.stop()

if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []

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

def parse_date_range(date_val):
    if isinstance(date_val, (tuple, list)):
        if len(date_val) == 2: return date_val[0], date_val[1]
        elif len(date_val) == 1: return date_val[0], date_val[0]
    return date_val, date_val

# ==========================================
# 1. API 引擎 (增加重試與速率保護)
# ==========================================
def fetch_booking_bundle(legs, cabin, title="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    # 最大嘗試 3 次，應對 429 速率限制
    for attempt in range(3):
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
            
            elif res.status_code == 429:
                # 📢 速率過快，強制休息後重試
                time.sleep(5)
                continue
            
            elif res.status_code == 403:
                # 💀 真正的額度用盡
                return {"status": "quota_exceeded"}
                
        except Exception as e:
            time.sleep(2)
    return {"status": "error"}

# ==========================================
# 2. UI 面板
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)

with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    st.radio("行程類型", ["來回", "多點"], horizontal=True, key="input_trip_type")
    
    c_d2, c_d3 = st.columns(2)
    if st.session_state.input_trip_type == "來回":
        with c_d2: 
            st.selectbox("🛫 起/終點", ALL_FORMATTED_CITIES, index=0, key="input_base_org")
            st.date_input("D2 去程日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("🛬 中轉點", ALL_FORMATTED_CITIES, index=5, key="input_base_dst")
            st.date_input("D3 回程日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o = d3_d = st.session_state.input_base_org.split(" ")[0]
        d2_d = d3_o = st.session_state.input_base_dst.split(" ")[0]
    else:
        with c_d2:
            st.selectbox("D2 出發", ALL_FORMATTED_CITIES, index=0, key="input_d2_o")
            st.selectbox("D2 抵達", ALL_FORMATTED_CITIES, index=5, key="input_d2_d")
            st.date_input("D2 日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("D3 出發", ALL_FORMATTED_CITIES, index=10, key="input_d3_o")
            st.selectbox("D3 抵達", ALL_FORMATTED_CITIES, index=0, key="input_d3_d")
            st.date_input("D3 日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o, d2_d, d3_o, d3_d = st.session_state.input_d2_o.split(" ")[0], st.session_state.input_d2_d.split(" ")[0], st.session_state.input_d3_o.split(" ")[0], st.session_state.input_d3_d.split(" ")[0]

    st.markdown("---")
    st.subheader("🌍 外站雷達 (D1 / D4)")
    st.checkbox("👯 D1/D4 設定為同一個外站點", value=True, key="input_sync_hubs")

    c_r1, c_r4 = st.columns(2)
    with c_r1:
        st.multiselect("D1 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d1_reg")
        d1_options = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d1_reg else ALL_FORMATTED_CITIES
        st.multiselect("📍 D1 起點庫", d1_options, key="input_d1_hubs")
        st.date_input("📅 D1 日期區間", value=(date(2026, 6, 10),), key="input_d1_dates")
    with c_r4:
        if st.session_state.input_sync_hubs:
            d4_final_hubs = st.session_state.input_d1_hubs
            st.info("💡 已與 D1 同步")
        else:
            st.multiselect("D4 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d4_reg")
            d4_options = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d4_reg else ALL_FORMATTED_CITIES
            st.multiselect("📍 D4 終點庫", d4_options, key="input_d4_hubs")
            d4_final_hubs = st.session_state.input_d4_hubs
        st.date_input("📅 D4 日期區間", value=(date(2026, 6, 26),), key="input_d4_dates")

    st.markdown("---")
    st.selectbox("搜尋艙等", ["商務艙", "豪經艙", "經濟艙"], key="input_cabin")
    st.number_input("基準預算 (TWD)", value=200000, step=5000, key="input_ref_total")

# --- 執行迴圈 ---
if not st.session_state.engine_running:
    if st.button("🚀 啟動獵殺掃描", use_container_width=True):
        d1_s, d1_e = parse_date_range(st.session_state.input_d1_dates)
        d4_s, d4_e = parse_date_range(st.session_state.input_d4_dates)
        d1_dates = [d1_s + timedelta(days=i) for i in range((d1_e - d1_s).days + 1)]
        d4_dates = [d4_s + timedelta(days=i) for i in range((d4_e - d4_s).days + 1)]
        
        tasks = []
        for h1_raw, h4_raw in product(st.session_state.input_d1_hubs, d4_final_hubs):
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
            st.rerun()

if st.session_state.engine_running:
    total, curr = len(st.session_state.task_list), st.session_state.task_idx
    BATCH = 5 # ⚡️ 降低單次併發量，保護頻率限制
    
    st.progress(min(curr / total, 1.0) if total > 0 else 0.0, text=f"🔥 進度: {curr}/{total}")
    
    batch_tasks = st.session_state.task_list[curr : curr + BATCH]
    # ⚡️ 降低 max_workers 避免觸發 429
    with ThreadPoolExecutor(max_workers=2) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4]): t for t in batch_tasks}
        for f in as_completed(futures):
            res = f.result()
            if res["status"] == "quota_exceeded": 
                st.error("🚨 偵測到額度完全用盡 (403 Error)！"); st.session_state.engine_running = False; st.stop()
            if res["status"] == "success" and res.get("offer"):
                o = res["offer"]
                o["ref"] = st.session_state.input_ref_total
                st.session_state.valid_offers.append(o)

    if curr + BATCH >= total:
        st.session_state.engine_running = False; st.rerun()
    else:
        st.session_state.task_idx += BATCH
        time.sleep(2) # ⚡️ 強制冷卻 2 秒，確保不觸發 API 頻率限制
        st.rerun()

# 戰果展示
if not st.session_state.engine_running and st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    for r in res[:50]:
        with st.expander(f"💰 {r['total']:,} | 省 {r['ref']-r['total']:,} | {r['title']} ({r['d1']})"):
            for leg in r['legs']: st.write(leg)import streamlit as st
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
# 0. 介面與狀態初始化
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
</style>
""", unsafe_allow_html=True)

try:
    BOOKING_API_KEY = st.secrets["BOOKING_API_KEY"]
    SENDER = st.secrets.get("EMAIL_SENDER")
    PWD = st.secrets.get("EMAIL_PASSWORD")
    RECEIVER = st.secrets.get("EMAIL_RECEIVER")
except KeyError:
    st.error("🚨 找不到 API 金鑰！請確認 Secrets 設定。"); st.stop()

if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []

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

def parse_date_range(date_val):
    if isinstance(date_val, (tuple, list)):
        if len(date_val) == 2: return date_val[0], date_val[1]
        elif len(date_val) == 1: return date_val[0], date_val[0]
    return date_val, date_val

# ==========================================
# 1. API 引擎 (增加重試與速率保護)
# ==========================================
def fetch_booking_bundle(legs, cabin, title="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    # 最大嘗試 3 次，應對 429 速率限制
    for attempt in range(3):
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
            
            elif res.status_code == 429:
                # 📢 速率過快，強制休息後重試
                time.sleep(5)
                continue
            
            elif res.status_code == 403:
                # 💀 真正的額度用盡
                return {"status": "quota_exceeded"}
                
        except Exception as e:
            time.sleep(2)
    return {"status": "error"}

# ==========================================
# 2. UI 面板
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)

with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    st.radio("行程類型", ["來回", "多點"], horizontal=True, key="input_trip_type")
    
    c_d2, c_d3 = st.columns(2)
    if st.session_state.input_trip_type == "來回":
        with c_d2: 
            st.selectbox("🛫 起/終點", ALL_FORMATTED_CITIES, index=0, key="input_base_org")
            st.date_input("D2 去程日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("🛬 中轉點", ALL_FORMATTED_CITIES, index=5, key="input_base_dst")
            st.date_input("D3 回程日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o = d3_d = st.session_state.input_base_org.split(" ")[0]
        d2_d = d3_o = st.session_state.input_base_dst.split(" ")[0]
    else:
        with c_d2:
            st.selectbox("D2 出發", ALL_FORMATTED_CITIES, index=0, key="input_d2_o")
            st.selectbox("D2 抵達", ALL_FORMATTED_CITIES, index=5, key="input_d2_d")
            st.date_input("D2 日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c_d3:
            st.selectbox("D3 出發", ALL_FORMATTED_CITIES, index=10, key="input_d3_o")
            st.selectbox("D3 抵達", ALL_FORMATTED_CITIES, index=0, key="input_d3_d")
            st.date_input("D3 日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o, d2_d, d3_o, d3_d = st.session_state.input_d2_o.split(" ")[0], st.session_state.input_d2_d.split(" ")[0], st.session_state.input_d3_o.split(" ")[0], st.session_state.input_d3_d.split(" ")[0]

    st.markdown("---")
    st.subheader("🌍 外站雷達 (D1 / D4)")
    st.checkbox("👯 D1/D4 設定為同一個外站點", value=True, key="input_sync_hubs")

    c_r1, c_r4 = st.columns(2)
    with c_r1:
        st.multiselect("D1 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d1_reg")
        d1_options = [f"{c} ({n})" for r in st.session_state.input_d1_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d1_reg else ALL_FORMATTED_CITIES
        st.multiselect("📍 D1 起點庫", d1_options, key="input_d1_hubs")
        st.date_input("📅 D1 日期區間", value=(date(2026, 6, 10),), key="input_d1_dates")
    with c_r4:
        if st.session_state.input_sync_hubs:
            d4_final_hubs = st.session_state.input_d1_hubs
            st.info("💡 已與 D1 同步")
        else:
            st.multiselect("D4 區域過濾", list(CI_GLOBAL_HUBS.keys()), key="input_d4_reg")
            d4_options = [f"{c} ({n})" for r in st.session_state.input_d4_reg for c, n in CI_GLOBAL_HUBS[r].items()] if st.session_state.input_d4_reg else ALL_FORMATTED_CITIES
            st.multiselect("📍 D4 終點庫", d4_options, key="input_d4_hubs")
            d4_final_hubs = st.session_state.input_d4_hubs
        st.date_input("📅 D4 日期區間", value=(date(2026, 6, 26),), key="input_d4_dates")

    st.markdown("---")
    st.selectbox("搜尋艙等", ["商務艙", "豪經艙", "經濟艙"], key="input_cabin")
    st.number_input("基準預算 (TWD)", value=200000, step=5000, key="input_ref_total")

# --- 執行迴圈 ---
if not st.session_state.engine_running:
    if st.button("🚀 啟動獵殺掃描", use_container_width=True):
        d1_s, d1_e = parse_date_range(st.session_state.input_d1_dates)
        d4_s, d4_e = parse_date_range(st.session_state.input_d4_dates)
        d1_dates = [d1_s + timedelta(days=i) for i in range((d1_e - d1_s).days + 1)]
        d4_dates = [d4_s + timedelta(days=i) for i in range((d4_e - d4_s).days + 1)]
        
        tasks = []
        for h1_raw, h4_raw in product(st.session_state.input_d1_hubs, d4_final_hubs):
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
            st.rerun()

if st.session_state.engine_running:
    total, curr = len(st.session_state.task_list), st.session_state.task_idx
    BATCH = 5 # ⚡️ 降低單次併發量，保護頻率限制
    
    st.progress(min(curr / total, 1.0) if total > 0 else 0.0, text=f"🔥 進度: {curr}/{total}")
    
    batch_tasks = st.session_state.task_list[curr : curr + BATCH]
    # ⚡️ 降低 max_workers 避免觸發 429
    with ThreadPoolExecutor(max_workers=3) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4]): t for t in batch_tasks}
        for f in as_completed(futures):
            res = f.result()
            if res["status"] == "quota_exceeded": 
                st.error("🚨 偵測到額度完全用盡 (403 Error)！"); st.session_state.engine_running = False; st.stop()
            if res["status"] == "success" and res.get("offer"):
                o = res["offer"]
                o["ref"] = st.session_state.input_ref_total
                st.session_state.valid_offers.append(o)

    if curr + BATCH >= total:
        st.session_state.engine_running = False; st.rerun()
    else:
        st.session_state.task_idx += BATCH
        time.sleep(2) # ⚡️ 強制冷卻 2 秒，確保不觸發 API 頻率限制
        st.rerun()

# 戰果展示
if not st.session_state.engine_running and st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    for r in res[:50]:
        with st.expander(f"💰 {r['total']:,} | 省 {r['ref']-r['total']:,} | {r['title']} ({r['d1']})"):
            for leg in r['legs']: st.write(leg)
