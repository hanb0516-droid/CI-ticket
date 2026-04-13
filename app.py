import streamlit as st
import requests
import json
import time
import os
import pandas as pd
from datetime import datetime, timedelta, date
from itertools import product
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# 0. 企業級 UI、金鑰與狀態初始化
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
    .rescue-box {
        padding: 15px; border: 2px dashed #ffb300; background: rgba(255, 179, 0, 0.15); 
        border-radius: 10px; margin-bottom: 20px; color: #ffffff;
    }
    .leaderboard-box {
        padding: 15px; border-left: 5px solid #4da8da; background: rgba(20, 35, 55, 0.7); 
        border-radius: 8px; margin-bottom: 20px; color: #ffffff;
    }
</style>
""", unsafe_allow_html=True)

try:
    raw_key = st.secrets["BOOKING_API_KEY"]
    BOOKING_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
except KeyError:
    st.error("🚨 找不到 API 金鑰，請於 Streamlit Secrets 中設定 BOOKING_API_KEY。"); st.stop()

# --- 初始化 Session State ---
if "engine_running" not in st.session_state: st.session_state.engine_running = False
if "task_list" not in st.session_state: st.session_state.task_list = []
if "task_idx" not in st.session_state: st.session_state.task_idx = 0
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "core_price" not in st.session_state: st.session_state.core_price = 175000
if "base_cache" not in st.session_state: st.session_state.base_cache = {}
if "quota_dead" not in st.session_state: st.session_state.quota_dead = False
if "hide_loss" not in st.session_state: st.session_state.hide_loss = True

# 🌍 升級版：華航全球樞紐站點 (CI GLOBAL HUBS)
CI_GLOBAL_HUBS = {
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光", "ROR": "帛琉"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "TAK": "高松", "HIJ": "廣島", "KOJ": "鹿兒島", "KMQ": "小松", "TOY": "富山", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "港澳大陸": {"HKG": "香港", "MFM": "澳門", "PEK": "北京", "PVG": "上海浦東", "SHA": "上海虹橋", "CAN": "廣州", "SZX": "深圳", "XMN": "廈門", "CTU": "成都", "CKG": "重慶"},
    "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
    "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
    "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
}
ALL_FORMATTED_CITIES = [f"{code} ({name})" for region, cities in CI_GLOBAL_HUBS.items() for code, name in cities.items()]

# ==========================================
# 0.5 📦 黑盒子資料讀取區
# ==========================================
st.markdown('<p class="custom-title">✈️ Flight Actuary Console</p>', unsafe_allow_html=True)
st.markdown('<p style="color:#cbd5e1; font-weight:600; margin-bottom:25px;">全球地毯式搜索・智能區間切換版</p>', unsafe_allow_html=True)

if not st.session_state.engine_running and os.path.exists(BLACKBOX_FILE):
    rescued_data = []
    with open(BLACKBOX_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try: rescued_data.append(json.loads(line))
                except json.JSONDecodeError: pass 
    
    if rescued_data:
        st.markdown(f"<div class='rescue-box'><h4>📁 黑盒子搶救紀錄</h4><p>成功找回上次掃描的 <b>{len(rescued_data)}</b> 組聯程票：</p></div>", unsafe_allow_html=True)
        if st.button("🗑️ 清除黑盒子紀錄 (準備執行全新掃描)"):
            os.remove(BLACKBOX_FILE)
            st.session_state.valid_offers = []
            st.rerun()

# ==========================================
# 1. API 請求引擎
# ==========================================
def fetch_booking_bundle(legs, cabin, strict_ci, title="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    c_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": c_map[cabin], "adults": "1", "currency_code": "TWD"}, timeout=30)
            if res.status_code == 200:
                raw = res.json()
                valid_res = []
                for offer in raw.get('data', {}).get('flightOffers', []):
                    is_valid, l_sum = True, []
                    for seg in offer.get('segments', []):
                        f_leg = seg.get('legs', [{}])[0]
                        c_info = f_leg.get('flightInfo', {}).get('carrierInfo', {})
                        car = c_info.get('operatingCarrier') or c_info.get('marketingCarrier', '??')
                        num = f_leg.get('flightInfo', {}).get('flightNumber', '')
                        dep = seg.get('departureAirport', {}).get('code', '???')
                        arr = seg.get('arrivalAirport', {}).get('code', '???')
                        dt = seg.get('departureTime', '').replace('T', ' ')[:16]
                        if strict_ci and car != "CI": is_valid = False; break
                        l_sum.append(f"**{car}{num}** | {dep} ➔ {arr} | {dt}")
                    if is_valid and len(l_sum) == 4:
                        valid_res.append({"title": title, "total": offer.get('priceBreakdown', {}).get('total', {}).get('units', 0), "legs": l_sum, "d1": d1, "d4": d4})
                if valid_res:
                    valid_res.sort(key=lambda x: x['total'])
                    return {"status": "success", "offer": valid_res[0]}
                return {"status": "success", "offer": None}
            elif res.status_code in [403, 429]:
                if "quota" in res.text.lower(): return {"status": "quota_exceeded"}
                time.sleep(2); continue
            else: return {"status": "error"}
        except: return {"status": "error"}
    return {"status": "error"}

# ==========================================
# 2. UI 介面與動態連動
# ==========================================
# 智能解析日期區間 (解決點選一天還是兩天的問題)
def parse_date_range(date_val):
    if isinstance(date_val, (tuple, list)):
        if len(date_val) == 2: return date_val[0], date_val[1]
        elif len(date_val) == 1: return date_val[0], date_val[0]
    return date_val, date_val

if "d1_city" not in st.session_state: st.session_state.d1_city = [f"{c} ({n})" for c, n in CI_GLOBAL_HUBS["港澳大陸"].items()]
if "d4_city" not in st.session_state: st.session_state.d4_city = [f"{c} ({n})" for c, n in CI_GLOBAL_HUBS["港澳大陸"].items()]
def sync_d1(): st.session_state.d1_city = ALL_FORMATTED_CITIES if "全部" in st.session_state.d1_reg else [f"{c} ({n})" for r in st.session_state.d1_reg if r in CI_GLOBAL_HUBS for c, n in CI_GLOBAL_HUBS[r].items()]
def sync_d4(): st.session_state.d4_city = ALL_FORMATTED_CITIES if "全部" in st.session_state.d4_reg else [f"{c} ({n})" for r in st.session_state.d4_reg if r in CI_GLOBAL_HUBS for c, n in CI_GLOBAL_HUBS[r].items()]

if st.session_state.engine_running:
    st.info("⚙️ **跨夜自動接力獵殺進行中...** 請保持網頁開啟。")
    if st.session_state.valid_offers:
        st.markdown("<div class='leaderboard-box'><h4>🏆 即時最高省錢排行榜 (Top 5)</h4>", unsafe_allow_html=True)
        temp_res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
        for idx, r in enumerate(temp_res[:5], 1):
            diff = r["ref"] - r['total']
            b_h = f"<span style='color:#00e676; font-weight:bold;'>🔥 省 {diff:,}</span>" if diff > 50000 else f"<span style='color:#b2ff59;'>✨ 省 {diff:,}</span>"
            st.markdown(f"**Top {idx}:** `{r['total']:,} TWD` | {b_h} | {r['title']} (D1:{r['d1']})", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    if st.button("🛑 提前終止掃描並進行結算", type="primary"):
        st
