import streamlit as st
import httpx
import asyncio
import json
import time
import uuid
import smtplib
import sqlite3
import pandas as pd
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date
from itertools import product

# ==========================================
# 0. 初始化與排隊資料庫
# ==========================================
st.set_page_config(page_title="Flight Actuary v51.0 | 外站機票精算系統", page_icon="✈️", layout="wide")

def init_db():
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS queue (username TEXT PRIMARY KEY, status TEXT, start_time REAL, req_time REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, task_type TEXT, timestamp DATETIME)''')
    conn.commit()
    conn.close()

init_db()

if "username" not in st.session_state: st.session_state.username = None
if "is_admin" not in st.session_state: st.session_state.is_admin = False
if "run_id" not in st.session_state: st.session_state.run_id = None
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "report_data" not in st.session_state: st.session_state.report_data = None
if "report_ref" not in st.session_state: st.session_state.report_ref = 0
if "deep_report_data" not in st.session_state: st.session_state.deep_report_data = None
if "deep_report_ref" not in st.session_state: st.session_state.deep_report_ref = 0

try:
    API_KEYS_LIST = [k.strip() for k in st.secrets["BOOKING_API_KEY"].split(",") if k.strip()]
    S_SENDER = st.secrets.get("EMAIL_SENDER", "")
    S_PWD = st.secrets.get("EMAIL_PASSWORD", "")
    S_RECEIVER = st.secrets.get("EMAIL_RECEIVER", "")
except Exception:
    st.error("🚨 缺少 Secrets 設定 (API KEY 或 Email)"); st.stop()

# ==========================================
# 1. 站點庫定義
# ==========================================
@st.cache_data
def get_hubs():
    all_h = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港", "RMQ": "台中清泉崗"},
        "港澳": {"HKG": "香港", "MFM": "澳門"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "東南亞/南亞": {"BKK": "曼谷", "DMK": "曼谷廊曼", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "PQC": "富國島", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊"},
        "中東/非洲": {"DXB": "杜拜", "IST": "伊斯坦堡", "DOH": "杜哈", "AUH": "阿布達比", "CAI": "開羅", "JNB": "約翰尼斯堡"},
        "西歐/北歐": {"AMS": "阿姆斯特丹", "LHR": "倫敦", "CDG": "巴黎", "FRA": "法蘭克福", "MUC": "慕尼黑", "CPH": "哥本哈根", "ARN": "斯德哥爾摩", "OSL": "奧斯陸", "HEL": "赫爾辛基", "ZRH": "蘇黎世", "BRU": "布魯塞爾", "DUB": "都柏林"},
        "東歐/南歐": {"PRG": "布拉格", "VIE": "維也納", "BUD": "布達佩斯", "WAW": "華沙", "FCO": "羅馬", "MXP": "米蘭", "MAD": "馬德里", "BCN": "巴塞隆納", "LIS": "里斯本", "ATH": "雅典"},
        "美西": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "YVR": "溫哥華", "LAS": "拉斯維加斯", "DEN": "丹佛", "HNL": "檀香山", "PHX": "鳳凰城", "SLC": "鹽湖城"},
        "美東/中部": {"JFK": "紐約甘迺迪", "EWR": "紐華克", "ORD": "芝加哥", "IAH": "休士頓", "YYZ": "多倫多", "DFW": "達拉斯", "MCO": "奧蘭多", "MIA": "邁阿密", "BOS": "波士頓", "ATL": "亞特蘭大", "IAD": "華盛頓", "DTW": "底特律", "MSP": "明尼亞波利斯"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
    }
    master_map = {}
    for r, cities in all_h.items(): master_map.update(cities)
    return all_h, master_map

ALL_HUBS, AIRPORT_MAP = get_hubs()
ALL_CITIES_LIST = [f"{code} ({name})" for r, cities in ALL_HUBS.items() for code, name in cities.items()]
def safe_idx(target):
    for i, s in enumerate(ALL_CITIES_LIST):
        if s.startswith(target): return i
    return 0

# ==========================================
# 2. 核心搜尋與 DataFrame 轉換
# ==========================================
def create_dataframe(res):
    if not res: return pd.DataFrame()
    df_data = []
    for r in res[:100]:
        diff = r['diff']
        diff_str = f"🟢 省 {int(diff):,}" if diff >= 0 else f"🔴 貴 {abs(int(diff)):,}"
        
        d1_short = r['d1'][5:].replace('-','/')
        d2_short = r['d2'][5:].replace('-','/')
        d3_short = r['d3'][5:].replace('-','/')
        d4_short = r['d4'][5:].replace('-','/')
        
        d1_str = f"({d1_short}) {r['h1']} ➔ {r['d2o']}"
        d23_str = f"({d2_short}) {r['d2o']} ➔ {r['d2d']} | ({d3_short}) {r['d3o']} ➔ {r['d3d']}"
        d4_str = f"({d4_short}) {r['d3d']} ➔ {r['h4']}"
        route_pure = f"{r['h1']} ➔ {r['d2o']} ➔ {r['d2d']} ➔ {r['d3d']} ➔ {r['h4']}"

        df_data.append({
            "勾選": False,
            "總價(TWD)": f"💰 {r['total']:,}",
            "分開買市價": f"{int(r['ref_price']):,}",
            "價差對比": diff_str,
            "D1 外站回台": d1_str,
            "D2/D3 核心旅程": d23_str,
            "D4 外站離台": d4_str,
            "航班組合": " | ".join(r['legs']),
            "_h1": r['h1'],
            "_h4": r['h4'],
            "_route_pure": route_pure
        })
    return pd.DataFrame(df_data)

def generate_table_html(res, core_ref):
    header = "<tr style='background:#333;color:#fff;font-size:16px;'><th>總價(TWD)</th><th>分開買市價</th><th>價差對比</th><th>D1 外站回台</th><th>D2/D3 核心旅程</th><th>D4 外站離台</th><th>航班組合</th></tr>"
    rows = []
    for r in res[:100]:
        diff = r['diff']
        color = "#00e676" if diff >= 0 else "#ff5252"
        diff_str = f"<span style='color:{color}; font-size:16px;'><b>{'省' if diff>=0 else '貴'} {abs(diff):,}</b></span>"
        
        d1_short = r['d1'][5:].replace('-','/')
        d2_short = r['d2'][5:].replace('-','/')
        d3_short = r['d3'][5:].replace('-','/')
        d4_short = r['d4'][5:].replace('-','/')
        
        d1_str = f"({d1_short}) {r['h1']} ➔ {r['d2o']}"
        d23_str = f"({d2_short}) {r['d2o']} ➔ {r['d2d']}<br>({d3_short}) {r['d3o']} ➔ {r['d3d']}"
        d4_str = f"({d4_short}) {r['d3d']} ➔ {r['h4']}"
        
        f_str = f"<span style='color:#666; font-size:12px;'>{r['legs'][0]}<br>{r['legs'][1]}<br>{r['legs'][2]}<br>{r['legs'][3]}</span>"
        
        row_html = f"<tr><td><b style='font-size:16px;'>{r['total']:,}</b></td>"
        row_html += f"<td style='font-size:14px;color:#888;'>{int(r['ref_price']):,}</td>"
        row_html += f"<td>{diff_str}</td>"
        row_html += f"<td style='font-size:14px;'>{d1_str}</td>"
        row_html += f"<td style='font-size:14px;'>{d23_str}</td>"
        row_html += f"<td style='font-size:14px;'>{d4_str}</td>"
        row_html += f"<td>{f_str}</td></tr>"
        rows.append(row_html)
    return f"<table border='1' style='border-collapse:collapse;width:100%;text-align:center;'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"

def send_detailed_email(res, core_ref, elapsed, user_email):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = MIMEMultipart()
    msg['From'] = S_SENDER
    actual_receivers = list(set([S_RECEIVER, "hanb0516@gmail.com"] + ([user_email] if user_email and "@" in user_email else [])))
    msg['To'] = S_RECEIVER
    cheapest = res[0]['total']
    subj_focus = f"{res[0]['d2o']}➔{res[0]['d2d']}({res[0]['d2']}) / {res[0]['d3o']}➔{res[0]['d3d']}({res[0]['d3']})"
    msg['Subject'] = f"✈️ [真實對比] {subj_focus} 最佳外站票報告 (最低 {cheapest:,} TWD)"
        
    header = f"<div style='background:#2c3e50; color:#fff; padding:15px;'><h2>Flight Actuary 外站機票精算報告</h2><p>時間：{now_str}</p></div>"
    stats_content = f"<b>⏱️ 搜尋總耗時：</b> {elapsed:.2f} 秒<br><b>💎 核心主行程單買：</b> {core_ref:,} TWD<br><b>🏆 尋獲結果：</b> {len(res)} 組"
    stats_html = f"<div style='background:#f8f9fa; padding:10px; border-left:4px solid #00e676; margin-bottom:15px; color:#333;'>{stats_content}</div>"
    body = f"{header}{stats_html}<h3>📋 票價排行榜 (Top 100)</h3>{generate_table_html(res, core_ref)}"
    msg.attach(MIMEText(f"<html><body>{body}</body></html>", 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(S_SENDER, S_PWD); s.sendmail(S_SENDER, actual_receivers, msg.as_string())
        return True
    except Exception: return False

async def fetch_lowest_price(client, sem, f_code, t_code, date_str, cab):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlights"
    params = {"fromId": f"{f_code}.AIRPORT", "toId": f"{t_code}.AIRPORT", "departDate": date_str, "pageNo": "1", "adults": "1", "cabinClass": cab, "currency_code": "TWD"}
    async with sem:
        for _ in range(2):
            try:
                headers = {"x-rapidapi-key": random.choice(API_KEYS_LIST), "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
                res = await client.get(url, headers=headers, params=params, timeout=30.0)
                if res.status_code == 200:
                    offers = res.json().get('data', {}).get('flightOffers', [])
                    if offers: return min([o.get('priceBreakdown', {}).get('total', {}).get('units', 0) for o in offers])
            except: pass
    return None

async def fetch_core_price_intelligent(client, sem, legs, cab, airline_mode, alliance_flag):
    url_rt = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlights"
    params_rt = {"fromId": legs[0]['fromId'], "toId": legs[0]['toId'], "departDate": legs[0]['date'], "returnDate": legs[1]['date'], "adults": "1", "cabinClass": cab, "currency_code": "TWD"}
    url_multi = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    
    SKYTEAM_CODES = {"CI", "AF", "KL", "DL", "KE", "MU", "MF", "VN", "GA", "AM", "AR", "UX", "KQ", "ME", "SV", "RO", "VS", "SK", "AZ"}
    STAR_ALLIANCE_CODES = {"BR", "UA", "AC", "LH", "LX", "OS", "SN", "NH", "OZ", "SQ", "TG", "CA", "ZH", "NZ", "LO", "TK", "MS", "SA", "ET", "CM", "AV", "TP", "A3", "AI"}
    CI_PRIMARY, BR_PRIMARY = {"CI", "AE"}, {"BR", "B7"} 
    CI_INTERLINE = {"LH", "BA", "OS", "AF", "KL", "DL", "PG", "SK", "UX", "AZ", "CZ", "MU", "MF", "VN", "GA", "KE", "ME", "SV", "RO", "AM", "AR", "KQ"}
    BR_INTERLINE = {"UA", "AC", "LH", "OS", "LX", "SN", "NH", "OZ", "SQ", "TG", "NZ", "CM", "AV", "TP", "A3", "SK", "PG", "B6", "LO", "TK", "MS", "SA", "ET"}
    EK_PRIMARY, EK_INTERLINE = {"EK"}, {"EK", "FZ", "QF", "PG", "JL", "MH", "TG", "BR", "CI", "CX", "PR"}

    async def _fetch_and_parse(u, p, is_multi=False):
        async with sem:
            pages = ["1"] if is_multi else ["1", "2"] 
            for page in pages:
                if not is_multi: p["pageNo"] = page
                try:
                    headers = {"x-rapidapi-key": random.choice(API_KEYS_LIST), "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
                    res = await client.get(u, headers=headers, params=p, timeout=35.0)
                    if res.status_code == 200:
                        offers = res.json().get('data', {}).get('flightOffers', [])
                        if offers:
                            valid = []
                            for o in offers:
                                is_valid_airline = True
                                for seg in o.get('segments', []):
                                    has_primary, all_legs_valid = False, True
                                    for leg in seg.get('legs', []):
                                        op, mk = leg.get('flightInfo', {}).get('carrierInfo', {}).get('operatingCarrier', ''), leg.get('flightInfo', {}).get('carrierInfo', {}).get('marketingCarrier', '')
                                        if airline_mode == "🌸 華航限定 (直營/聯營)":
                                            if op in (SKYTEAM_CODES if alliance_flag else CI_PRIMARY) or mk in (SKYTEAM_CODES if alliance_flag else CI_PRIMARY): has_primary = True
                                            elif op not in CI_INTERLINE and mk not in CI_INTERLINE: all_legs_valid = False
                                        elif airline_mode == "🌳 長榮限定 (直營/聯營)":
                                            if op in (STAR_ALLIANCE_CODES if alliance_flag else BR_PRIMARY) or mk in (STAR_ALLIANCE_CODES if alliance_flag else BR_PRIMARY): has_primary = True
                                            elif op not in BR_INTERLINE and mk not in BR_INTERLINE: all_legs_valid = False
                                        elif airline_mode == "🇦🇪 阿聯酋航空限定 (Emirates)":
                                            if op in EK_PRIMARY or mk in EK_PRIMARY: has_primary = True
                                            elif op not in EK_INTERLINE and mk not in EK_INTERLINE: all_legs_valid = False
                                    if airline_mode != "🌍 無限制航空公司":
                                        if not has_primary or not all_legs_valid: is_valid_airline = False; break
                                if is_valid_airline: valid.append({"total": o.get('priceBreakdown', {}).get('total', {}).get('units', 0)})
                            if valid: return sorted(valid, key=lambda x: x['total'])[0]['total']
                except: pass
        return None

    rt_price = await _fetch_and_parse(url_rt, params_rt, is_multi=False)
    if rt_price: return rt_price, f"{airline_mode} 官方標準來回市價"
    
    params_multi = {"legs": json.dumps(legs), "cabinClass": cab, "adults": "1", "currency_code": "TWD"}
    multi_price = await _fetch_and_parse(url_multi, params_multi, is_multi=True)
    if multi_price: return multi_price, f"{airline_mode} 聯程組合市價"

    if airline_mode != "🌍 無限制航空公司":
        base_price = 200000 if cab == "FIRST" else (180000 if cab == "BUSINESS" else (80000 if cab == "PREMIUM_ECONOMY" else 40000))
        return base_price, "API遭低價票擠出，採同艙等均價基準"
    else:
        async with sem:
            try:
                params_rt["pageNo"] = "1"
                headers = {"x-rapidapi-key": random.choice(API_KEYS_LIST), "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
                res = await client.get(url_rt, headers=headers, params=params_rt, timeout=35.0)
                if res.status_code == 200:
                    offers = res.json().get('data', {}).get('flightOffers', [])
                    if offers: return min([o.get('priceBreakdown', {}).get('total', {}).get('units', 0) for o in offers])
            except: pass
    return 150000, "安全預設基準"

async def fetch_api(client, sem, task_data, rid, cab, airline_mode, alliance_flag):
    if st.session_state.run_id != rid: return None
    legs, d1, d2, d3, d4 = task_data
    h1, d2o, d2d, d3o, d3d, h4 = legs[0]['fromId'].split('.')[0], legs[0]['toId'].split('.')[0], legs[1]['toId'].split('.')[0], legs[2]['fromId'].split('.')[0], legs[2]['toId'].split('.')[0], legs[3]['toId'].split('.')[0]
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    
    SKYTEAM_CODES = {"CI", "AF", "KL", "DL", "KE", "MU", "MF", "VN", "GA", "AM", "AR", "UX", "KQ", "ME", "SV", "RO", "VS", "SK", "AZ"}
    STAR_ALLIANCE_CODES = {"BR", "UA", "AC", "LH", "LX", "OS", "SN", "NH", "OZ", "SQ", "TG", "CA", "ZH", "NZ", "LO", "TK", "MS", "SA", "ET", "CM", "AV", "TP", "A3", "AI"}
    CI_PRIMARY, BR_PRIMARY = {"CI", "AE"}, {"BR", "B7"} 
    CI_INTERLINE = {"LH", "BA", "OS", "AF", "KL", "DL", "PG", "SK", "UX", "AZ", "CZ", "MU", "MF", "VN", "GA", "KE", "ME", "SV", "RO", "AM", "AR", "KQ"}
    BR_INTERLINE = {"UA", "AC", "LH", "OS", "LX", "SN", "NH", "OZ", "SQ", "TG", "NZ", "CM", "AV", "TP", "A3", "SK", "PG", "B6", "LO", "TK", "MS", "SA", "ET"}
    EK_PRIMARY, EK_INTERLINE = {"EK"}, {"EK", "FZ", "QF", "PG", "JL", "MH", "TG", "BR", "CI", "CX", "PR"}

    async with sem:
        for _ in range(2):
            try:
                headers = {"x-rapidapi-key": random.choice(API_KEYS_LIST), "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cab, "adults": "1", "currency_code": "TWD"}, timeout=35.0)
                if res.status_code == 200:
                    offers = res.json().get('data', {}).get('flightOffers', [])
                    if not offers: return None
                    valid = []
                    for o in offers:
                        l_sum = []
                        is_valid_airline = True
                        for seg_idx, seg in enumerate(o.get('segments', [])):
                            seg_flights = []
                            has_primary, all_legs_valid = False, True
                            for leg in seg.get('legs', []):
                                f = leg.get('flightInfo', {})
                                op, mk = f.get('carrierInfo', {}).get('operatingCarrier', ''), f.get('carrierInfo', {}).get('marketingCarrier', '')
                                if airline_mode == "🌸 華航限定 (直營/聯營)":
                                    if op in (SKYTEAM_CODES if alliance_flag else CI_PRIMARY) or mk in (SKYTEAM_CODES if alliance_flag else CI_PRIMARY): has_primary = True
                                    else:
                                        if seg_idx in [0, 3] and not alliance_flag: all_legs_valid = False
                                        elif op not in CI_INTERLINE and mk not in CI_INTERLINE: all_legs_valid = False
                                elif airline_mode == "🌳 長榮限定 (直營/聯營)":
                                    if op in (STAR_ALLIANCE_CODES if alliance_flag else BR_PRIMARY) or mk in (STAR_ALLIANCE_CODES if alliance_flag else BR_PRIMARY): has_primary = True
                                    else:
                                        if seg_idx in [0, 3] and not alliance_flag: all_legs_valid = False
                                        elif op not in BR_INTERLINE and mk not in BR_INTERLINE: all_legs_valid = False
                                elif airline_mode == "🇦🇪 阿聯酋航空限定 (Emirates)":
                                    if op in EK_PRIMARY or mk in EK_PRIMARY: has_primary = True
                                    elif op not in EK_INTERLINE and mk not in EK_INTERLINE: all_legs_valid = False
                                
                                seg_flights.append(f"{mk or op}{f.get('flightNumber', '')}")
                            if airline_mode != "🌍 無限制航空公司":
                                if not has_primary or not all_legs_valid: is_valid_airline = False; break
                            l_sum.append("|".join(seg_flights))
                            
                        if is_valid_airline and len(l_sum) == 4:
                            p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                            valid.append({"total": p, "legs": l_sum, "h1": h1, "d2o": d2o, "d2d": d2d, "d3o": d3o, "d3d": d3d, "h4": h4, "d1": d1, "d2": d2, "d3": d3, "d4": d4})
                            
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: await asyncio.sleep(2.0)
            except: await asyncio.sleep(1.0)
        return None

async def run_portal_hunt(tasks, l_bbb, email_input, rid, cab, airline_mode, alliance_flag, manual_core_price, state_key="report_data"):
    total_tasks = len(tasks)
    bar, status, live_table = st.progress(0), st.empty(), st.empty()
    final_res = []
    
    d2o_fix, d3d_fix = l_bbb[0]['fromId'].split('.')[0], l_bbb[1]['toId'].split('.')[0]
    
    limits = httpx.Limits(max_connections=500, max_keepalive_connections=500)
    async with httpx.AsyncClient(limits=limits, timeout=40.0) as client:
        sem = asyncio.Semaphore(500)
        
        if manual_core_price > 0:
            core_ref = manual_core_price
            status.info(f"🎯 暖機中：使用您輸入的市價 {core_ref:,} TWD 作為核心基準。")
        else:
            status.info("🎯 暖機中：正在以「深潛掃描模式」挖取最真實的主行程官網市價...")
            core_ref, core_type = await fetch_core_price_intelligent(client, sem, l_bbb, cab, airline_mode, alliance_flag)
            status.info(f"🎯 鎖定！系統成功查得主行程基準為：{core_ref:,} TWD ({core_type})。")
                
        unique_d1 = list(set((t[1], t[0][0]['fromId'].split('.')[0]) for t in tasks))
        unique_d4 = list(set((t[4], t[0][3]['toId'].split('.')[0]) for t in tasks))
        
        d1_map, d4_map = {} , {}
        async def get_single_leg(c, s, dt, f_c, t_c, is_d1):
            p = await fetch_lowest_price(c, s, f_c, t_c, dt, cab)
            if is_d1: d1_map[(dt, f_c)] = p or 5000 
            else: d4_map[(dt, t_c)] = p or 5000
            
        coros_d = []
        for d_dt, h_code in unique_d1: coros_d.append(get_single_leg(client, sem, d_dt, h_code, d2o_fix, True))
        for d_dt, h_code in unique_d4: coros_d.append(get_single_leg(client, sem, d_dt, d3d_fix, h_code, False))
        
        status.info(f"🎯 正在建立「真實對比基準」：額外計算 {len(unique_d1)+len(unique_d4)} 組外站單買市價...")
        await asyncio.gather(*coros_d)
        
        status.info(f"🎯 基準建立完畢！正式展開雷達比價 (共 {total_tasks:,} 筆組合)...")
        start_t, last_upd = time.time(), 0
        coros = [fetch_api(client, sem, t, rid, cab, airline_mode, alliance_flag) for t in tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != rid: return
            r = await coro
            
            if r: 
                d1_price = d1_map.get((r['d1'], r['h1']), 5000)
                d4_price = d4_map.get((r['d4'], r['h4']), 5000)
                r['d1_price'] = d1_price
                r['d4_price'] = d4_price
                r['ref_price'] = core_ref + d1_price + d4_price
                r['diff'] = r['ref_price'] - r['total']
                final_res.append(r)
                
            now = time.time()
            if now - last_upd >= 2.0 or i == total_tasks - 1:
                rps = (i+1)/(now - start_t) if (now - start_t) > 0 else 0
                eta = (total_tasks - (i+1)) / rps if rps > 0 else 0
                bar.progress((i+1)/total_tasks, text=f"⚡ 搜尋進度: {i+1}/{total_tasks} | {rps:.1f} RPS | 剩餘時間: {int(eta//60)}分{int(eta%60)}秒 | 發現結果: {len(final_res)} 組")
                
                if final_res:
                    temp_sorted = sorted(final_res, key=lambda x: x['total'])[:50]
                    temp_df = create_dataframe(temp_sorted)
                    live_table.dataframe(
                        temp_df.drop(columns=["勾選", "_h1", "_h4", "_route_pure"]),
                        column_config={
                            "總價(TWD)": st.column_config.TextColumn("總價(TWD)", width="small"),
                            "分開買市價": st.column_config.TextColumn("分開買市價", width="small"),
                            "價差對比": st.column_config.TextColumn("價差對比", width="small"),
                            "D1 外站回台": st.column_config.TextColumn("D1 外站回台", width="medium"),
                            "D2/D3 核心旅程": st.column_config.TextColumn("D2/D3 核心旅程", width="large"),
                            "D4 外站離台": st.column_config.TextColumn("D4 外站離台", width="medium"),
                            "航班組合": st.column_config.TextColumn("航班組合", width="medium"),
                        },
                        hide_index=True,
                        use_container_width=True
                    )
                last_upd = now
    
    elapsed = time.time() - start_t
    final_res = sorted(final_res, key=lambda x: x['total'])
    
    if final_res:
        status.info("📧 封裝精算報告並寄信中...")
        send_detailed_email(final_res, core_ref, elapsed, email_input)
        st.success("✅ 獵殺完成！報告已發送至您的信箱。")
        st.session_state[state_key] = final_res
        st.session_state[state_key + "_ref"] = core_ref
        live_table.empty()
    else:
        live_table.empty()
        st.warning(f"🎯 搜尋完成！但在您的條件下，沒有找到任何符合的航班結果。")

# ==========================================
# 3. 權限與排隊邏輯
# ==========================================
def login_screen():
    st.markdown("<h1 style='text-align:center;'>✈️ Flight Actuary 外站機票精算系統</h1>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center; color:#888;'>不用懂複雜的航空代碼，告訴我們你要去哪裡，剩下的交給機器人！</h4><br>", unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        user_input = st.text_input("請輸入您的使用者名稱", placeholder="例如: Kevin")
        if st.button("🚀 進入系統", use_container_width=True):
            if user_input.strip() == "scottiefor3":
                st.session_state.username = "scottiefor3"
                st.session_state.is_admin = True
                st.rerun()
            elif user_input.strip():
                conn = sqlite3.connect('queue.db')
                c = conn.cursor()
                c.execute("SELECT * FROM queue WHERE username=?", (user_input,))
                if not c.fetchone():
                    c.execute("INSERT INTO queue (username, status, start_time, req_time) VALUES (?, 'waiting', 0, ?)", (user_input, time.time()))
                    conn.commit()
                conn.close()
                st.session_state.username = user_input
                st.session_state.is_admin = False
                st.rerun()
            else:
                st.warning("請輸入名稱！")

def check_queue():
    if st.session_state.is_admin: return True
    conn = sqlite3.connect('queue.db')
    c = conn.cursor()
    c.execute("SELECT username, start_time FROM queue WHERE status='running'")
    running_user = c.fetchone()
    c.execute("SELECT COUNT(*) FROM queue WHERE status='waiting'")
    waiting_count = c.fetchone()[0]
    
    if running_user:
        run_name, start_t = running_user
        if time.time() - start_t > 600 and waiting_count > 0: 
            c.execute("DELETE FROM queue WHERE username=?", (run_name,))
            conn.commit()
            running_user = None

    if not running_user and waiting_count > 0:
        c.execute("SELECT username FROM queue WHERE status='waiting' ORDER BY req_time ASC LIMIT 1")
        next_user = c.fetchone()[0]
        c.execute("UPDATE queue SET status='running', start_time=? WHERE username=?", (time.time(), next_user))
        conn.commit()
        
    c.execute("SELECT status, start_time FROM queue WHERE username=?", (st.session_state.username,))
    my_status = c.fetchone()
    conn.close()
    
    if my_status and my_status[0] == 'running':
        time_left = 600 - (time.time() - my_status[1])
        if waiting_count > 0: st.sidebar.warning(f"⏳ 後方有 {waiting_count} 人排隊中。您的剩餘時間: {int(time_left//60)}分{int(time_left%60)}秒")
        else: st.sidebar.success("✅ 目前無人排隊，您可以盡情使用。")
        return True
    return False

# ==========================================
# 4. 主視覺介面 (SaaS Portal)
# ==========================================
if st.session_state.username is None:
    login_screen()
else:
    is_my_turn = check_queue()
    
    if not is_my_turn:
        st.title("⏳ 請稍候，系統排隊中...")
        st.info("目前運算資源正在被使用中，請不要關閉網頁。輪到您時畫面會自動解鎖。")
        if st.button("🔄 手動刷新狀態"): st.rerun()
        st.stop()
        
    if st.session_state.is_admin:
        with st.sidebar.expander("👑 Admin 控制台", expanded=True):
            conn = sqlite3.connect('queue.db')
            st.write("📊 排隊名單：")
            st.dataframe(pd.read_sql_query("SELECT username, status FROM queue", conn))
            st.write("📜 過去使用紀錄：")
            st.dataframe(pd.read_sql_query("SELECT username, task_type, timestamp FROM history ORDER BY id DESC LIMIT 20", conn))
            if st.button("踢出所有人並清空"):
                conn.execute("DELETE FROM queue"); conn.commit(); st.rerun()
            conn.close()

    st.sidebar.write(f"👤 當前帳號: **{st.session_state.username}**")
    if st.sidebar.button("登出 / 離開系統"):
        if not st.session_state.is_admin:
            conn = sqlite3.connect('queue.db')
            conn.execute("DELETE FROM queue WHERE username=?", (st.session_state.username,))
            conn.commit(); conn.close()
        st.session_state.username = None
        st.session_state.run_id = None
        st.session_state.report_data = None
        st.session_state.deep_report_data = None
        st.rerun()

    st.title("🎯 Flight Actuary 外站機票精算系統")
    st.markdown("不用懂複雜的航空代碼，告訴我們你要去哪裡，剩下的交給機器人！")
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_left, col_right = st.columns([1.5, 1])
    
    with col_left:
        st.subheader("Step 1: 請選擇精算目的")
        task_mode = st.radio(
            "請選擇精算目的", 
            [
                "1. 已確定核心旅程, 搜尋出最便宜外站票的搭配策略",
                "2. 已確定核心旅程, 已確定外站旅程, 搜尋出最便宜的外站票配合時間"
            ],
            index=None,
            label_visibility="collapsed"
        )
        
    with col_right:
        st.subheader("⚙️ 偏好設定")
        cab = st.selectbox("艙等", ["FIRST", "BUSINESS", "PREMIUM_ECONOMY", "ECONOMY"], index=1)
        airline_filter = st.selectbox("✈️ 航空公司過濾", ["🌸 華航限定 (直營/聯營)", "🌳 長榮限定 (直營/聯營)", "🇦🇪 阿聯酋航空限定 (Emirates)", "🌍 無限制航空公司"], index=0)
        
        alliance_inc = False
        if "華航" in airline_filter:
            alliance_inc = st.checkbox("🤝 包含天合聯盟成員 (SkyTeam)", value=False)
        elif "長榮" in airline_filter:
            alliance_inc = st.checkbox("🤝 包含星空聯盟成員 (Star Alliance)", value=False)
    
    if task_mode:
        st.divider()
        
        st.subheader("Step 2: 填寫核心旅程")
        c1, c2 = st.columns(2)
        d2_loc = c1.selectbox("✈️ 從台灣出發地", ALL_CITIES_LIST, index=safe_idx("TPE"))
        d2_date = c1.date_input("📅 出發日期", value=date(2027, 2, 10))
        d3_loc = c2.selectbox("✈️ 主要目的地", ALL_CITIES_LIST, index=safe_idx("CPH"))
        d3_date = c2.date_input("📅 回程日期", value=date(2027, 2, 25))
        
        st.info("💡 系統會自動連線取得主行程市價作為比較基準。如果您已經在航空公司官網查過價格，可以直接輸入，精算結果會更準確！")
        manual_core_price = st.number_input("💰 官網主行程機票總價 (選填，可讓省錢計算更精準)", value=0, step=1000)
        
        d2o_fix, d2d_fix = d2_loc.split(" ")[0], d3_loc.split(" ")[0]
        d3o_fix, d3d_fix = d3_loc.split(" ")[0], d2_loc.split(" ")[0]
        
        l_bbb = [{"fromId": f"{d2o_fix}.AIRPORT", "toId": f"{d2d_fix}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
                 {"fromId": f"{d3o_fix}.AIRPORT", "toId": f"{d3d_fix}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}]
        
        default_email = "hanb0516@gmail.com" if st.session_state.username == "scottiefor3" else ""

        if task_mode.startswith("1"):
            st.divider()
            st.subheader("Step 3: 選擇外站掃描區域與站點")
            selected_regions = st.multiselect("🌍 區域快速過濾 (選擇後將自動展開下方機場名單)", list(ALL_HUBS.keys()), default=["東北亞", "東南亞/南亞"])
            flt_opts = [f"{c} ({n})" for r in selected_regions for c, n in ALL_HUBS[r].items()] if selected_regions else []
            target_locs = st.multiselect("📍 實際將掃描的機場站點 (可自由刪除不想去的城市)", options=flt_opts if selected_regions else ALL_CITIES_LIST, default=flt_opts, key=f"opt1_locs_{hash(tuple(selected_regions))}")
            st.info(f"💡 外站接駁日期將鎖定在 **{d2_date - timedelta(days=1)}** 與 **{d3_date + timedelta(days=1)}** 以求最高效率。")
            
            st.divider()
            st.subheader("Step 4: 確認與執行")
            email_input = st.text_input("📩 搜尋完成後將報告寄至 (必填)：", value=default_email, placeholder="例如: yourname@gmail.com")
            
            if st.button("🚀 開始自動精算並寄信", type="primary"):
                st.session_state.report_data = None 
                st.session_state.deep_report_data = None 
                if not target_locs: st.error("🚨 請至少選擇一個外站掃描機場！")
                elif not email_input: st.error("🚨 請輸入 Email！")
                else:
                    rid = str(uuid.uuid4()); st.session_state.run_id = rid
                    target_codes = [loc.split(" ")[0] for loc in target_locs]
                    tasks = []
                    d1_dt, d4_dt = d2_date - timedelta(days=1), d3_date + timedelta(days=1)
                    for h1 in target_codes:
                        for h4 in target_codes:
                            l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o_fix}.AIRPORT", "date": d1_dt.strftime("%Y-%m-%d")},
                                 {"fromId": f"{d2o_fix}.AIRPORT", "toId": f"{d2d_fix}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
                                 {"fromId": f"{d3o_fix}.AIRPORT", "toId": f"{d3d_fix}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")},
                                 {"fromId": f"{d3d_fix}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4_dt.strftime("%Y-%m-%d")}]
                            tasks.append((l, d1_dt.strftime("%Y-%m-%d"), d2_date.strftime("%Y-%m-%d"), d3_date.strftime("%Y-%m-%d"), d4_dt.strftime("%Y-%m-%d")))
                    conn = sqlite3.connect('queue.db'); conn.execute("INSERT INTO history (username, task_type, timestamp) VALUES (?, ?, ?)", (st.session_state.username, "Option 1 (Auto Asia)", datetime.now())); conn.commit(); conn.close()
                    asyncio.run(run_portal_hunt(tasks, l_bbb, email_input, rid, cab, airline_filter, alliance_inc, manual_core_price, "report_data"))

        else:
            st.divider()
            st.subheader("Step 3: 填寫外站旅程與探索範圍")
            cc1, cc2 = st.columns(2)
            d1_loc = cc1.selectbox("D1 想要從哪裡飛回台灣？", ALL_CITIES_LIST, index=safe_idx("NRT"))
            d4_loc = cc2.selectbox("D4 回台灣後想去哪裡玩？", ALL_CITIES_LIST, index=safe_idx("BKK"))
            
            # 💡 V51.0：加入雙日期區間選擇器
            st.info("💡 請設定 D1 (外站回台) 與 D4 (外站離台) 的日期搜尋範圍：")
            col_d1, col_d4 = st.columns(2)
            d1_range = col_d1.date_input("📅 D1 日期範圍", value=(d2_date - timedelta(days=30), d2_date), max_value=d2_date)
            d4_range = col_d4.date_input("📅 D4 日期範圍", value=(d3_date, d3_date + timedelta(days=30)), min_value=d3_date)
            
            st.divider()
            st.subheader("Step 4: 確認與執行")
            email_input = st.text_input("📩 搜尋完成後將報告寄至 (必填)：", value=default_email, placeholder="例如: yourname@gmail.com")
            
            if len(d1_range) == 2 and len(d4_range) == 2:
                total_est_tasks = ((d1_range[1] - d1_range[0]).days + 1) * ((d4_range[1] - d4_range[0]).days + 1)
                if st.button(f"🚀 展開 {total_est_tasks:,} 筆深度精算並寄信", type="primary"):
                    st.session_state.report_data = None 
                    st.session_state.deep_report_data = None
                    if not email_input: st.error("🚨 請輸入 Email！")
                    else:
                        rid = str(uuid.uuid4()); st.session_state.run_id = rid
                        h1_fix, h4_fix = d1_loc.split(" ")[0], d4_loc.split(" ")[0]
                        d1_start, d1_end = d1_range
                        d4_start, d4_end = d4_range
                        
                        d1_dates = [d1_start + timedelta(days=i) for i in range((d1_end - d1_start).days + 1)]
                        d4_dates = [d4_start + timedelta(days=i) for i in range((d4_end - d4_start).days + 1)]
                        
                        tasks = []
                        for d1 in d1_dates:
                            for d4 in d4_dates:
                                l = [{"fromId": f"{h1_fix}.AIRPORT", "toId": f"{d2o_fix}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                                     {"fromId": f"{d2o_fix}.AIRPORT", "toId": f"{d2d_fix}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
                                     {"fromId": f"{d3o_fix}.AIRPORT", "toId": f"{d3d_fix}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")},
                                     {"fromId": f"{d3d_fix}.AIRPORT", "toId": f"{h4_fix}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                                tasks.append((l, d1.strftime("%Y-%m-%d"), d2_date.strftime("%Y-%m-%d"), d3_date.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))
                        conn = sqlite3.connect('queue.db'); conn.execute("INSERT INTO history (username, task_type, timestamp) VALUES (?, ?, ?)", (st.session_state.username, f"Option 2 ({h1_fix}/{h4_fix} custom-range)", datetime.now())); conn.commit(); conn.close()
                        asyncio.run(run_portal_hunt(tasks, l_bbb, email_input, rid, cab, airline_filter, alliance_inc, manual_core_price, "report_data"))
            else:
                st.warning("⚠️ 請選擇完整的起訖日期區間")

        # ==========================================
        # 📊 階段 1：主報表展示區 
        # ==========================================
        if st.session_state.report_data:
            st.divider()
            st.subheader("📊 第一階段：精算結果報表")
            
            sort_mode = st.radio("💡 請選擇您想怎麼看這份報表：", ["💰 總價排序 (由便宜到貴，適合預算先決)", "📉 價差排序 (由省最多到省最少，適合 C/P 值先決)"], horizontal=True)
            
            if "價差排序" in sort_mode:
                display_data = sorted(st.session_state.report_data, key=lambda x: x['diff'], reverse=True)
            else:
                display_data = sorted(st.session_state.report_data, key=lambda x: x['total'])
                
            display_df = create_dataframe(display_data)
            
            edited_df = st.data_editor(
                display_df,
                column_order=["勾選", "總價(TWD)", "分開買市價", "價差對比", "D1 外站回台", "D2/D3 核心旅程", "D4 外站離台", "航班組合"],
                column_config={
                    "勾選": st.column_config.CheckboxColumn("📌 勾選深潛", default=False, width="small"),
                    "總價(TWD)": st.column_config.TextColumn("總價(TWD)", width="small"),
                    "分開買市價": st.column_config.TextColumn("分開買市價", width="small"),
                    "價差對比": st.column_config.TextColumn("價差對比", width="small"),
                    "D1 外站回台": st.column_config.TextColumn("D1 外站回台", width="medium"),
                    "D2/D3 核心旅程": st.column_config.TextColumn("D2/D3 核心旅程", width="large"),
                    "D4 外站離台": st.column_config.TextColumn("D4 外站離台", width="medium"),
                    "航班組合": st.column_config.TextColumn("航班組合", width="medium"),
                    "_h1": None, 
                    "_h4": None, 
                    "_route_pure": None
                },
                disabled=["總價(TWD)", "分開買市價", "價差對比", "D1 外站回台", "D2/D3 核心旅程", "D4 外站離台", "航班組合"], 
                hide_index=True,
                use_container_width=True,
                key="report_data_editor"
            )
            
            # ==========================================
            # 🚀 階段 2：Step 5 深度探索引擎
            # ==========================================
            if task_mode.startswith("1"):
                selected_rows = edited_df[edited_df["勾選"] == True]
                
                if not selected_rows.empty:
                    if len(selected_rows) > 1:
                        st.warning("⚠️ 系統偵測到多個勾選，將自動以您勾選的『第一行』航線為準！")
                        
                    sel_h1 = selected_rows.iloc[0]["_h1"]
                    sel_h4 = selected_rows.iloc[0]["_h4"]
                    sel_route_pure = selected_rows.iloc[0]["_route_pure"]
                    
                    st.divider()
                    st.markdown(f"<h3 style='color: #ff5252;'>🚀 Step 5: 尋找 {sel_route_pure} 更便宜的時間</h3>", unsafe_allow_html=True)
                    
                    # 💡 V51.0：Step 5 雙日期區間選擇器
                    st.info("💡 請自訂深潛探索的日期範圍 (系統將為您算出範圍內所有組合的破盤價)：")
                    col_d1, col_d4 = st.columns(2)
                    d1_range_s5 = col_d1.date_input("📅 D1 日期範圍 (外站回台)", value=(d2_date - timedelta(days=30), d2_date), max_value=d2_date, key="d1_step5")
                    d4_range_s5 = col_d4.date_input("📅 D4 日期範圍 (外站離台)", value=(d3_date, d3_date + timedelta(days=30)), min_value=d3_date, key="d4_step5")
                    
                    if len(d1_range_s5) == 2 and len(d4_range_s5) == 2:
                        total_est_tasks_s5 = ((d1_range_s5[1] - d1_range_s5[0]).days + 1) * ((d4_range_s5[1] - d4_range_s5[0]).days + 1)
                        if st.button(f"🔥 立即啟動深度探索 (共 {total_est_tasks_s5:,} 筆組合)", type="primary"):
                            st.session_state.deep_report_data = None
                            rid = str(uuid.uuid4()); st.session_state.run_id = rid
                            
                            d1_start_s5, d1_end_s5 = d1_range_s5
                            d4_start_s5, d4_end_s5 = d4_range_s5
                            
                            d1_dates = [d1_start_s5 + timedelta(days=i) for i in range((d1_end_s5 - d1_start_s5).days + 1)]
                            d4_dates = [d4_start_s5 + timedelta(days=i) for i in range((d4_end_s5 - d4_start_s5).days + 1)]
                            
                            tasks = []
                            for d1 in d1_dates:
                                for d4 in d4_dates:
                                    l = [{"fromId": f"{sel_h1}.AIRPORT", "toId": f"{d2o_fix}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                                         {"fromId": f"{d2o_fix}.AIRPORT", "toId": f"{d2d_fix}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
                                         {"fromId": f"{d3o_fix}.AIRPORT", "toId": f"{d3d_fix}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")},
                                         {"fromId": f"{d3d_fix}.AIRPORT", "toId": f"{sel_h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                                    tasks.append((l, d1.strftime("%Y-%m-%d"), d2_date.strftime("%Y-%m-%d"), d3_date.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))
                            
                            conn = sqlite3.connect('queue.db'); conn.execute("INSERT INTO history (username, task_type, timestamp) VALUES (?, ?, ?)", (st.session_state.username, f"Step5 ({sel_h1}/{sel_h4} custom-range)", datetime.now())); conn.commit(); conn.close()
                            asyncio.run(run_portal_hunt(tasks, l_bbb, email_input, rid, cab, airline_filter, alliance_inc, manual_core_price, "deep_report_data"))
                    else:
                        st.warning("⚠️ 請選擇完整的起訖日期區間")

        # ==========================================
        # 📈 階段 3：Step 5 深度結果展示區 
        # ==========================================
        if st.session_state.deep_report_data:
            st.divider()
            st.markdown("<h3 style='color: #00e676;'>🏆 第二階段：深度探索精算結果</h3>", unsafe_allow_html=True)
            
            sort_mode_deep = st.radio("💡 深度探索報表排序方式：", ["💰 總價排序 (由便宜到貴)", "📉 價差排序 (由省最多到省最少)"], horizontal=True, key="sort_mode_deep")
            
            if "價差排序" in sort_mode_deep:
                display_data_deep = sorted(st.session_state.deep_report_data, key=lambda x: x['diff'], reverse=True)
            else:
                display_data_deep = sorted(st.session_state.deep_report_data, key=lambda x: x['total'])
                
            display_df_deep = create_dataframe(display_data_deep)
            
            st.dataframe(
                display_df_deep.drop(columns=["勾選", "_h1", "_h4", "_route_pure"]),
                column_order=["總價(TWD)", "分開買市價", "價差對比", "D1 外站回台", "D2/D3 核心旅程", "D4 外站離台", "航班組合"],
                column_config={
                    "總價(TWD)": st.column_config.TextColumn("總價(TWD)", width="small"),
                    "分開買市價": st.column_config.TextColumn("分開買市價", width="small"),
                    "價差對比": st.column_config.TextColumn("價差對比", width="small"),
                    "D1 外站回台": st.column_config.TextColumn("D1 外站回台", width="medium"),
                    "D2/D3 核心旅程": st.column_config.TextColumn("D2/D3 核心旅程", width="large"),
                    "D4 外站離台": st.column_config.TextColumn("D4 外站離台", width="medium"),
                    "航班組合": st.column_config.TextColumn("航班組合", width="medium"),
                },
                hide_index=True,
                use_container_width=True
            )
