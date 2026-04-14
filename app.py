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
# 0. UI 初始化 (Hyper-Drive 樣式)
# ==========================================
st.set_page_config(page_title="Flight Actuary | HYPER-DRIVE", page_icon="⚡", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-image: linear-gradient(rgba(10, 15, 30, 0.5), rgba(10, 15, 30, 0.7)), 
        url("https://images.unsplash.com/photo-1436491865332-7a61a109cc05?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important; background-position: center !important; background-attachment: fixed !important;
    }
    .custom-title {
        background: linear-gradient(45deg, #00e676, #00e5ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 3.5rem; text-shadow: 0px 5px 20px rgba(0, 230, 118, 0.3);
    }
    .quota-box {
        padding: 15px; background: rgba(0, 230, 118, 0.1); border-radius: 12px; border: 2px solid #00e676; margin-bottom: 25px;
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

# 狀態鎖定
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

# ==========================================
# 📊 核心功能：動態生成矩陣或清單 HTML
# ==========================================
def generate_report_html(res_list, ref, target_str):
    d1_dates = sorted(list(set(r['d1'] for r in res_list)))
    d4_dates = sorted(list(set(r['d4'] for r in res_list)))
    
    # 判斷是否為區間 (單日顯示清單，多日顯示矩陣)
    is_matrix = len(d1_dates) > 1 or len(d4_dates) > 1

    if is_matrix:
        matrix = {}
        min_price = float('inf')
        max_price = 0
        for r in res_list:
            key = (r['d1'], r['d4'])
            if key not in matrix or r['total'] < matrix[key]['total']:
                matrix[key] = r
                min_price = min(min_price, r['total'])
                max_price = max(max_price, r['total'])

        html = f"""
        <div style="background-color: #ffffff; color: #333333; padding: 20px; border-radius: 12px; margin-bottom: 20px;">
            <h2 style="color: #00e676; margin-top: 0;">⚡ 價格熱力矩陣：{target_str}</h2>
            <p>直飛基準：<b>{ref:,} TWD</b> | 最低票價：<b style="color:red;">{min_price:,} TWD</b></p>
            <table border="1" style="border-collapse: collapse; text-align: center; width: 100%; max-width: 900px; font-size: 13px;">
                <tr style="background-color: #333; color: white;">
                    <th style="padding: 10px;">D4回 ↘ \\ D1去 ➡</th>
        """
        for d1 in d1_dates: html += f"<th style='padding: 10px;'>{d1[5:]}</th>"
        html += "</tr>"
        
        for d4 in d4_dates:
            html += f"<tr><th style='padding: 10px; background-color: #f2f2f2;'>{d4[5:]}</th>"
            for d1 in d1_dates:
                record = matrix.get((d1, d4))
                if record:
                    price, saving = record['total'], ref - record['total']
                    alpha = 0.8 if max_price == min_price else 0.8 - 0.7 * ((price - min_price) / (max_price - min_price))
                    bg_color = f"rgba(0, 230, 118, {alpha:.2f})"
                    html += f"<td style='padding: 8px; background-color: {bg_color}; border: 1px solid #ddd;'>"
                    html += f"<div style='font-size: 15px; font-weight: bold;'>{price:,}</div>"
                    html += f"<div style='color: #d32f2f; font-weight: bold;'>省 {saving:,}</div>"
                    html += f"<div style='font-size: 10px; color: #555; margin-top: 4px;'>{record['h1'][:3]} ➔ {record['h4'][:3]}</div>"
                    html += "</td>"
                else: html += "<td style='padding: 8px; background-color: #fafafa; color: #ccc; border: 1px solid #ddd;'>-</td>"
            html += "</tr>"
        html += "</table></div>"
        return html, True # True 表示回傳的是矩陣

    else:
        # 單日清單模式
        html = f"""
        <div style="background-color: #ffffff; color: #333333; padding: 20px; border-radius: 12px; margin-bottom: 20px;">
            <h2 style="color: #00e676; margin-top: 0;">⚡ 獲利清單：{target_str}</h2>
            <p>直飛基準價：<b>{ref:,} TWD</b> | 共捕獲 <b>{len(res_list)}</b> 組</p>
            <table border="1" cellpadding="10" style="border-collapse: collapse; width: 100%;">
                <tr style="background-color: #f8f8f8;"><th>票價 (TWD)</th><th style="color: red;">實省金額</th><th>行程 (D1 ➔ D4)</th></tr>
        """
        for r in res_list:
            diff = ref - r['total']
            html += f"<tr><td><b>{r['total']:,}</b></td><td style='color:red; font-weight:bold;'>{diff:,}</td><td>{r['h1']} ({r['d1']}) ➔ {r['h4']} ({r['d4']})</td></tr>"
        html += "</table></div>"
        return html, False # False 表示回傳的是清單

def send_email_report(res_list, d2_o, d2_d, d3_o, d3_d, d2_dt, d3_dt, ref):
    if not SENDER or not PWD or not RECEIVER or not res_list: return False
    res_list.sort(key=lambda x: x['total'])
    targets = [city for city in [d2_d, d3_o] if city not in ["TPE", "KHH"]]
    target_str = "/".join(list(dict.fromkeys(targets))) if targets else "海外目的地"
    
    html_content, is_matrix = generate_report_html(res_list, ref, target_str)
    
    msg = MIMEMultipart()
    msg['From'], msg['To'] = SENDER, RECEIVER
    format_type = "矩陣解析" if is_matrix else "單日清單"
    msg['Subject'] = f"⚡ [{format_type}] 目標 {target_str} | 捕獲 {len(res_list)} 組"
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(SENDER, PWD); s.send_message(msg)
        return True
    except: return False

# ==========================================
# 1. API 引擎
# ==========================================
def fetch_booking_bundle(legs, cabin, h1="", h4="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": BOOKING_API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    try:
        res = requests.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=15)
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
                if is_ci and len(l_sum) == (4 if h1 else 2):
                    valid.append({"total": offer.get('priceBreakdown', {}).get('total', {}).get('units', 0), "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
            if valid: return sorted(valid, key=lambda x: x['total'])[0]
    except: pass
    return None

# ==========================================
# 2. UI 面板
# ==========================================
st.markdown('<p class="custom-title">⚡ ULTRA HYPER-DRIVE</p>', unsafe_allow_html=True)
st.markdown(f'<div class="quota-box">🏎️ <b>星際躍遷模式：</b> 剩餘額度：{st.session_state.quota_remaining} | 🎯 目前基準：{st.session_state.ref_price:,} TWD</div>', unsafe_allow_html=True)

with st.container():
    st.subheader("📌 核心行程 (D2 / D3)")
    st.radio("行程類型", ["來回", "多點進出"], horizontal=True, key="input_trip_type")
    c1, c2 = st.columns(2)
    if "來回" in st.session_state.input_trip_type:
        with c1: 
            st.selectbox("🛫 核心起點", ALL_FORMATTED_CITIES, index=0, key="input_base_org")
            st.date_input("D2 去程日期", value=date(2026, 6, 11), key="input_d2_dt")
        with c2:
            st.selectbox("🛬 核心終點", ALL_FORMATTED_CITIES, index=5, key="input_base_dst")
            st.date_input("D3 回程日期", value=date(2026, 6, 25), key="input_d3_dt")
        d2_o = d3_d = st.session_state.input_base_org.split(" ")[0]
        d2_d = d3_o = st.session_state.input_base_dst.split(" ")[0]
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
        st.multiselect("📍 D1 起點庫", d1_opt, key="input_d1_hubs")
        st.date_input("📅 D1 日期", value=(date(2026, 6, 10),), key="input_d1_dates")
    with cr4:
        d4_hubs = st.session_state.input_d1_hubs if st.session_state.input_sync else st.multiselect("📍 D4 終點庫", ALL_FORMATTED_CITIES, key="input_d4_hubs")
        if st.session_state.input_sync: st.info("已同步 D1")
        st.date_input("📅 D4 日期", value=(date(2026, 6, 26),), key="input_d4_dates")

    cab_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    st.selectbox("艙等", list(cab_map.keys()), key="input_cabin")
    st.checkbox("自動對標直飛價", value=True, key="input_auto_ref")
    st.number_input("手動基準預算", value=200000, key="input_manual_ref")

# --- 核心執行 ---
if not st.session_state.engine_running:
    if st.button("🚀 啟動極限 HYPER-DRIVE 獵殺", use_container_width=True):
        d1_in, d4_in = st.session_state.input_d1_dates, st.session_state.input_d4_dates
        d1_s, d1_e = (d1_in[0], d1_in[-1]) if isinstance(d1_in, (list, tuple)) else (d1_in, d1_in)
        d4_s, d4_e = (d4_in[0], d4_in[-1]) if isinstance(d4_in, (list, tuple)) else (d4_in, d4_in)
        
        final_ref = st.session_state.input_manual_ref
        if st.session_state.input_auto_ref:
            with st.spinner("🎯 正在校準直飛基準價..."):
                direct_legs = [{"fromId": f"{d2_o}.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": st.session_state.input_d2_dt.strftime("%Y-%m-%d")},
                               {"fromId": f"{d3_o}.AIRPORT", "toId": f"{d3_d}.AIRPORT", "date": st.session_state.input_d3_dt.strftime("%Y-%m-%d")}]
                res = fetch_booking_bundle(direct_legs, cab_map[st.session_state.input_cabin])
                if res: final_ref = res['total']; st.session_state.ref_price = final_ref

        d1_ts, d4_ts = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days+1)], [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days+1)]
        tasks = []
        for h1_r, h4_r in product(st.session_state.input_d1_hubs, d4_hubs):
            h1, h4 = h1_r.split(" ")[0], h4_r.split(" ")[0]
            for d1, d4 in product(d1_ts, d4_ts):
                if d1 <= st.session_state.input_d2_dt and d4 >= st.session_state.input_d3_dt:
                    l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2_o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d2_o}.AIRPORT", "toId": f"{d2_d}.AIRPORT", "date": st.session_state.input_d2_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_o}.AIRPORT", "toId": f"{d3_d}.AIRPORT", "date": st.session_state.input_d3_dt.strftime("%Y-%m-%d")}, 
                         {"fromId": f"{d3_d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    tasks.append((l, cab_map[st.session_state.input_cabin], h1_r, h4_r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d"), final_ref))
        if tasks:
            st.session_state.task_list, st.session_state.task_idx, st.session_state.valid_offers, st.session_state.engine_running = tasks, 0, [], True
            st.rerun()

if st.session_state.engine_running:
    total, curr, BATCH = len(st.session_state.task_list), st.session_state.task_idx, 300
    st.progress(min(curr/total, 1.0), text=f"⚡ HYPER-DRIVE 執行中: {curr}/{total}")
    batch = st.session_state.task_list[curr : curr + BATCH]
    with ThreadPoolExecutor(max_workers=60) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5]): t for t in batch}
        for f in as_completed(futures):
            res = f.result()
            if res and (t_ref := batch[0][6]) - res['total'] > 0:
                res['ref'] = t_ref
                st.session_state.valid_offers.append(res)
    if curr + BATCH >= total:
        send_email_report(st.session_state.valid_offers, d2_o, d2_d, d3_o, d3_d, st.session_state.input_d2_dt, st.session_state.input_d3_dt, st.session_state.ref_price)
        st.session_state.engine_running = False; st.rerun()
    else: st.session_state.task_idx += BATCH; st.rerun()

# --- 戰果展示區 (網頁版 UI 雙模切換) ---
if not st.session_state.engine_running and st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    
    # 🎯 動態生成 WebApp 顯示內容 (呼叫剛寫好的共用函數)
    targets = [city for city in [d2_d, d3_o] if city not in ["TPE", "KHH"]]
    target_str = "/".join(list(dict.fromkeys(targets))) if targets else "海外目的地"
    ui_html, is_matrix = generate_report_html(res, st.session_state.ref_price, target_str)
    
    # 渲染至 Streamlit 畫面
    st.markdown(ui_html, unsafe_allow_html=True)
    
    # 矩陣下方保留原始可展開的列表，方便查看航班細節
    if is_matrix:
        st.markdown("### 🏆 詳細獲利清單 (展開看航班細節)")
        for r in res[:50]:
            with st.expander(f"💰 {r['total']:,} | 🔥 省 {r['ref']-r['total']:,} | {r['h1']} ({r['d1']}) ➔ {r['h4']} ({r['d4']})"):
                st.write(f"航班：{' | '.join(r['legs'])}")
