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
# 0. 初始化與靜態快取
# ==========================================
st.set_page_config(page_title="Flight Actuary | v43.3 CORE B", page_icon="✈️", layout="wide")

@st.cache_data
def get_hubs():
    ci_h = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
        "港澳": {"HKG": "香港", "MFM": "澳門"},
        "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
        "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
    }
    all_h = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港", "RMQ": "台中清泉崗"},
        "港澳": {"HKG": "香港", "MFM": "澳門"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山", "CJJ": "清州", "HKD": "函館", "SDJ": "仙台"},
        "東南亞": {"BKK": "曼谷", "DMK": "曼谷廊曼", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "PQC": "富國島", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
        "中東/中亞": {"DXB": "杜拜", "IST": "伊斯坦堡", "DOH": "杜哈", "DEL": "新德里"},
        "西歐": {"AMS": "阿姆斯特丹", "LHR": "倫敦", "CDG": "巴黎", "FRA": "法蘭克福", "MUC": "慕尼黑"},
        "東歐": {"PRG": "布拉格", "VIE": "維也納", "BUD": "布達佩斯", "WAW": "華沙"},
        "南歐": {"FCO": "羅馬", "MXP": "米蘭", "MAD": "馬德里", "BCN": "巴塞隆納"},
        "北歐": {"CPH": "哥本哈根", "ARN": "斯德哥爾摩", "OSL": "奧斯陸", "HEL": "赫爾辛基"},
        "美西": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "YVR": "溫哥畫"},
        "美東/中部": {"JFK": "紐約", "EWR": "紐華克", "ORD": "芝加哥", "IAH": "休士頓", "YYZ": "多倫多"},
        "南美": {"GRU": "聖保羅", "EZE": "布宜諾斯艾利斯", "SCL": "聖地牙哥"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭", "PER": "伯斯"}
    }
    def flatten(h_dict): return [f"{code} ({name})" for r, cities in h_dict.items() for code, name in cities.items()]
    master_map = {}
    for r, cities in all_h.items(): master_map.update(cities)
    for r, cities in ci_h.items(): master_map.update(cities)
    return ci_h, flatten(ci_h), all_h, flatten(all_h), master_map

CI_HUBS, CI_CITIES, ALL_HUBS, ALL_CITIES, AIRPORT_MAP = get_hubs()

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 缺少 API KEY"); st.stop()

S_SENDER, S_PWD, S_RECEIVER = st.secrets.get("EMAIL_SENDER", ""), st.secrets.get("EMAIL_PASSWORD", ""), st.secrets.get("EMAIL_RECEIVER", "")

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "run_id" not in st.session_state: st.session_state.run_id = None
if "ref_aaa" not in st.session_state: st.session_state.ref_aaa = 0
if "ref_bbb" not in st.session_state: st.session_state.ref_bbb = 0
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000
if "perf_stats" not in st.session_state: st.session_state.perf_stats = {"time": 0, "dps": 0}

# ==========================================
# 1. 核心工具函數
# ==========================================
def get_safe_dates(d_input):
    if isinstance(d_input, (list, tuple)):
        if len(d_input) >= 2: return d_input[0], d_input[1]
        if len(d_input) == 1: return d_input[0], d_input[0]
    return d_input, d_input

def get_name(code):
    return f"{code} ({AIRPORT_MAP.get(code, '未知')})"

def generate_table_html(res, ref, core_ref, core_mode, limit=100):
    display_res = res[:limit]
    is_mode_b = core_mode.startswith("B")
    header = "<tr style='background:#333;color:#fff;'><th>總價(TWD)</th>"
    if not is_mode_b:
        header += "<th>獲利(雙基準)</th><th>比較核心旅程</th>"
    else:
        header += "<th>核心旅程票價</th>"
    header += "<th>探索路線</th><th>MM-DD 日期組合</th><th>航班明細</th></tr>"
    
    rows = []
    for r in display_res:
        route_str = f"{get_name(r['h1'])} ➔ {get_name(r['h4'])}" if not is_mode_b else f"{get_name(r['d2d'])} ➔ {get_name(r['d3o'])}"
        row_html = f"<tr><td>{r['total']:,}</td>"
        if not is_mode_b:
            row_html += f"<td><span style='color:{'#d32f2f' if (ref-r['total'])>=0 else '#1976d2'}'>{'省' if (ref-r['total'])>=0 else '貴'} {abs(ref-r['total']):,}</span></td>"
            row_html += f"<td>{r['total'] - core_ref:+,}</td>"
        else:
            row_html += f"<td>{r['total'] - core_ref:,}</td>"
        row_html += f"<td>{route_str}</td><td><span style='font-size:11px;'>{r['d1'][5:]} ➔ {r['d2'][5:]}<br>{r['d3'][5:]} ➔ {r['d4'][5:]}</span></td><td><span style='font-size:10px;'>{' | '.join(r['legs'])}</span></td></tr>"
        rows.append(row_html)
    return f"<table border='1' style='border-collapse:collapse;width:100%;text-align:center;font-size:12px;'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"

def generate_matrix_html(res, ref, title, core_mode):
    if not res: return ""
    col_key = 'd1' if core_mode.startswith("A") else 'd2'
    row_key = 'd4' if core_mode.startswith("A") else 'd3'
    axis_label = "D4↘\\D1➡" if core_mode.startswith("A") else "D3↘\\D2➡"
    c_dates = sorted(list(set(r[col_key] for r in res)))
    r_dates = sorted(list(set(r[row_key] for r in res)))
    matrix = {(r[col_key], r[row_key]): r for r in res}
    diffs = [ref - r['total'] for r in res]
    max_save = max([0] + diffs)
    max_lose = abs(min([0] + diffs))
    h = [f"<h4 style='margin-bottom:5px; color:#2c3e50;'>📍 {title}</h4><table border='1' style='border-collapse:collapse;font-size:11px;text-align:center;margin-bottom:15px;'>"]
    h.append(f"<tr style='background:#333;color:#fff;'><th>{axis_label}</th>" + "".join([f"<th>{d[5:]}</th>" for d in c_dates]) + "</tr>")
    for r_d in r_dates:
        row = [f"<tr><td style='background:#f2f2f2; color:#000; font-weight:bold;'>{r_d[5:]}</td>" ]
        for c_d in c_dates:
            r = matrix.get((c_d, r_d))
            if r:
                diff = ref - r['total']
                if diff > 0:
                    ratio = diff / max_save if max_save > 0 else 0
                    r_val, g_val, b_val = 255, int(255*(1-ratio)+50*ratio), int(255*(1-ratio)+50*ratio)
                elif diff < 0:
                    ratio = abs(diff) / max_lose if max_lose > 0 else 0
                    r_val, g_val, b_val = int(255*(1-ratio)+50*ratio), int(255*(1-ratio)+120*ratio), 255
                else: r_val, g_val, b_val = 255, 255, 255
                bg = f"rgba({r_val},{g_val},{b_val},0.85)"
                lum = 0.299*r_val + 0.587*g_val + 0.114*b_val
                text_color = "#000" if lum > 160 else "#fff"
                row.append(f"<td style='background:{bg};padding:5px;color:{text_color};'><b>{r['total']:,}</b><br><span style='color:{text_color};'>{'省' if diff>=0 else '貴'}{abs(diff):,}</span></td>")
            else: row.append("<td style='color:#888;'>-</td>")
        row.append("</tr>")
        h.append("".join(row))
    return "".join(h) + "</table>"

# 🛠️ 專屬修改：模式 B 的 Email 標題將焦點轉移至 D1/D4 核心
def send_detailed_email(res, ref, elapsed, dps, aaa, bbb, cab, core_mode, version="v43.3"):
    if not S_SENDER or not S_PWD or not S_RECEIVER: return False, "信箱未設定"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = MIMEMultipart()
    msg['From'] = S_SENDER
    msg['To'] = S_RECEIVER
    cab_map = {"BUSINESS": "商務艙", "PREMIUM_ECONOMY": "豪經艙", "ECONOMY": "經濟艙"}
    cab_zh = cab_map.get(cab, cab)
    cheapest = res[0]['total']
    is_mode_b = core_mode.startswith("B")
    
    if not is_mode_b:
        core_val = bbb
        diff_val = cheapest - bbb
        diff_label = "貴" if diff_val > 0 else "便宜"
        subj_focus = f"{res[0]['d2o']}➔{res[0]['d2d']}({res[0]['d2']}) / {res[0]['d3o']}➔{res[0]['d3d']}({res[0]['d3']})"
        msg['Subject'] = f"✈️ [{version}] {cab_zh} {subj_focus} 核心精算表 (最低 {cheapest:,} TWD, 比起核心旅程 {diff_label} {abs(diff_val):,} TWD)"
    else:
        # 🛠️ 模式 B 修改點：將 D1/D4 路徑與日期作為標題重點
        core_val = aaa
        d1_path = f"{res[0]['h1']}➔{res[0]['d2o']}({res[0]['d1']})"
        d4_path = f"{res[0]['d3d']}➔{res[0]['h4']}({res[0]['d4']})"
        msg['Subject'] = f"✈️ [{version}] {cab_zh} {d1_path} / {d4_path} 核心精算表 (整段最低 {cheapest:,} TWD)"
        
    header = f"<div style='background:#2c3e50; color:#fff; padding:15px;'><h2>版本：{version} {'核心旅程定錨' if is_mode_b else '外站比價'}報告</h2><p>時間：{now_str}</p></div>"
    stats_content = f"<b>⏱️ 搜尋總耗時：</b> {elapsed:.2f} 秒<br><b>⚡ 平均 DPS (RPS)：</b> {dps:.2f} 筆/秒<br>"
    if not is_mode_b:
        stats_content += f"<b>🎯 當前對標基準價：</b> 接駁來回({aaa:,}) + 主行程({bbb:,}) = {ref:,} TWD<br>"
    else:
        stats_content += f"<b>📍 已知固定接駁成本 (D1/D4)：</b> {aaa:,} TWD<br>"
    stats_content += f"<b>🏆 尋獲組合：</b> {len(res)} 組"
    stats_html = f"<div style='background:#f8f9fa; padding:10px; border-left:4px solid #00e676; margin-bottom:15px; color:#333;'>{stats_content}</div>"
    warning = f"<p style='color:#e67e22;'>⚠️ 僅顯示前 100 筆最優結果確保寄達。</p>" if len(res) > 100 else ""
    body = f"{header}{stats_html}{warning}<h3>📋 票價排行榜 (Top 100)</h3>{generate_table_html(res, ref, core_val, core_mode, limit=100)}"
    msg.attach(MIMEText(f"<html><body>{body}</body></html>", 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(S_SENDER, S_PWD); s.send_message(msg)
        return True, ""
    except Exception as e:
        return False, repr(e)

# ==========================================
# 2. 異步引擎
# ==========================================
async def fetch_api(client, sem, task_data, rid, ci_only_flag):
    if st.session_state.run_id != rid: return None
    legs, cabin, h1, d2o, d2d, d3o, d3d, h4, d1, d2, d3, d4 = task_data
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    async with sem:
        for _ in range(2):
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=35.0)
                if res.status_code == 200:
                    raw = res.json()
                    offers = raw.get('data', {}).get('flightOffers', [])
                    if not offers: return None
                    valid = []
                    for o in offers:
                        l_sum = []
                        is_valid_airline = True
                        for seg in o.get('segments', []):
                            for leg in seg.get('legs', []):
                                f = leg.get('flightInfo', {})
                                c_info = f.get('carrierInfo', {})
                                op, mk = c_info.get('operatingCarrier', ''), c_info.get('marketingCarrier', '')
                                if ci_only_flag and op != "CI" and mk != "CI": is_valid_airline = False
                                l_sum.append(f"{mk or op}{f.get('flightNumber', '')}")
                        if is_valid_airline:
                            p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                            valid.append({"total": p, "legs": l_sum, "h1": h1, "d2o": d2o, "d2d": d2d, "d3o": d3o, "d3d": d3d, "h4": h4, "d1": d1, "d2": d2, "d3": d3, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: await asyncio.sleep(2.0)
            except: await asyncio.sleep(1.0)
        return None

# ==========================================
# 3. UI 介面
# ==========================================
with st.sidebar:
    st.header("⚙️ 獵殺控制台 (v43.3)")
    core_mode = st.radio("🎯 核心旅程模式", ["A. 鎖定 D2/D3 (常規尋找便宜外站)", "B. 鎖定 D1/D4 (已知外站, 尋找主行程)"])
    st.divider()
    cab = st.selectbox("艙等", ["BUSINESS", "PREMIUM_ECONOMY", "ECONOMY"])
    ci_only = st.checkbox("🌸 華航限定 (直營/聯營)", value=True)
    workers = st.slider("併發上限", 20, 100, 50)
    show_all = st.checkbox("👁️ 透視模式 (顯示賠錢票)", value=True)
    st.divider()
    use_manual_ref = st.checkbox("🛠️ 使用手動基準價", value=False)
    manual_ref_val = st.number_input("輸入市場參考總價 (TWD)", value=int(st.session_state.ref_price), step=1000)
    email_on = st.checkbox("寄送 Email 報告", value=True)
    if st.button("🛑 停止任務"): st.session_state.run_id = None; st.rerun()

ACTIVE_HUBS = CI_HUBS if ci_only else ALL_HUBS
ACTIVE_CITIES = CI_CITIES if ci_only else ALL_CITIES

def safe_idx(target):
    for i, s in enumerate(ACTIVE_CITIES):
        if s.startswith(target): return i
    return 0

is_mode_b = core_mode.startswith("B")
if not is_mode_b:
    if use_manual_ref:
        st.markdown(f"<div style='padding:10px;background:rgba(0,230,118,0.1);border-radius:8px;'>🎯 <b>當前對標基準價：</b> {manual_ref_val:,} TWD (手動校準)</div>", unsafe_allow_html=True)
    else:
        st.markdown(f"<div style='padding:10px;background:rgba(0,230,118,0.1);border-radius:8px;'>🎯 <b>當前對標基準價：</b> 接駁來回({st.session_state.ref_aaa:,}) + 主行程({st.session_state.ref_bbb:,}) = {st.session_state.ref_price:,} TWD</div>", unsafe_allow_html=True)

trip_mode = st.radio("行程模式", ["來回", "多點進出"], horizontal=True)
c1, c2 = st.columns(2)

if trip_mode == "來回":
    t_l1 = "D1 起點 (外站回台)" if is_mode_b else "去程起點 (D2)"
    t_l2 = "D4 終點 (台灣出發)" if is_mode_b else "去程目的 (D3)"
    t_d1 = "D1 抵台日期" if is_mode_b else "去程日期 (D2)"
    t_d2 = "D4 出發日期" if is_mode_b else "回程日期 (D3)"
    top_loc1 = c1.selectbox(t_l1, ACTIVE_CITIES, index=safe_idx("NRT" if is_mode_b else "TPE"))
    top_dt1 = c1.date_input(t_d1, value=date(2026, 6, 11))
    top_loc2 = c2.selectbox(t_l2, ACTIVE_CITIES, index=safe_idx("BKK" if is_mode_b else "PRG"))
    top_dt2 = c2.date_input(t_d2, value=date(2026, 6, 25))
    top_loc3, top_loc4 = top_loc2, top_loc1
else:
    t_l1 = "D1 起點 (外站)" if is_mode_b else "D2 出發"
    t_l2 = "D1 終點 (台灣Base)" if is_mode_b else "D2 目的"
    t_l3 = "D4 起點 (台灣Base)" if is_mode_b else "D3 出發"
    t_l4 = "D4 終點 (外站)" if is_mode_b else "D3 目的"
    t_d1 = "D1 日期" if is_mode_b else "D2 日期"
    t_d2 = "D4 日期" if is_mode_b else "D3 日期"
    top_loc1 = c1.selectbox(t_l1, ACTIVE_CITIES, index=safe_idx("NRT" if is_mode_b else "TPE"))
    top_dt1 = c1.date_input(t_d1, value=date(2026, 6, 11))
    top_loc2 = c1.selectbox(t_l2, ACTIVE_CITIES, index=safe_idx("TPE" if is_mode_b else "PRG"))
    top_loc3 = c2.selectbox(t_l3, ACTIVE_CITIES, index=safe_idx("TPE" if is_mode_b else "FRA"))
    top_dt2 = c2.date_input(t_d2, value=date(2026, 6, 25))
    top_loc4 = c2.selectbox(t_l4, ACTIVE_CITIES, index=safe_idx("BKK" if is_mode_b else "TPE"))

if is_mode_b:
    h1_fix, d2o_fix, d3d_fix, h4_fix = top_loc1.split(" ")[0], "TPE" if trip_mode == "來回" else top_loc2.split(" ")[0], "TPE" if trip_mode == "來回" else top_loc3.split(" ")[0], top_loc2.split(" ")[0] if trip_mode == "來回" else top_loc4.split(" ")[0]
    d1_fix_dt, d4_fix_dt = top_dt1, top_dt2
else:
    d2o_fix, d2d_fix, d3o_fix, d3d_fix = top_loc1.split(" ")[0], top_loc2.split(" ")[0], top_loc2.split(" ")[0] if trip_mode == "來回" else top_loc3.split(" ")[0], top_loc1.split(" ")[0] if trip_mode == "來回" else top_loc4.split(" ")[0]
    d2_fix_dt, d3_fix_dt = top_dt1, top_dt2

st.markdown("---")
b_l1 = "📍 D2 目的地 (主行程)" if is_mode_b else "📍 D1 起點站 (接駁)"
b_l2 = "📍 D3 出發站 (主行程)" if is_mode_b else "📍 D4 終點站 (接駁)"
b_sync = "👯 D3 同步 D2 選擇" if is_mode_b else "👯 D4 同步 D1 選擇"
b_d1, b_d2 = ("D2 日期範圍", "D3 日期範圍") if is_mode_b else ("D1 日期範圍", "D4 日期範圍")

sync = st.checkbox(b_sync, value=True)
cr1, cr4 = st.columns(2)
with cr1:
    regs = st.multiselect("區域快速過濾", list(ACTIVE_HUBS.keys()))
    flt_opts = [f"{c} ({n})" for r in regs for c, n in ACTIVE_HUBS[r].items()] if regs else ACTIVE_CITIES
    d1_key = f"bot_sel1_{hash(tuple(regs))}"
    if d1_key in st.session_state: st.session_state[d1_key] = [x for x in st.session_state[d1_key] if x in flt_opts]
    curr_b1 = st.session_state.get(d1_key, flt_opts if regs else [])
    bot_locs1 = st.multiselect(f"{b_l1} ({len(curr_b1)})", options=flt_opts, default=curr_b1 if curr_b1 else (flt_opts if regs else None), key=d1_key)
    d_bot1_def = top_dt1 + timedelta(days=1) if is_mode_b else top_dt1 - timedelta(days=1)
    bot_r1 = st.date_input(b_d1, value=(d_bot1_def,))

with cr4:
    d4_key = "bot_sel2_manual"
    if d4_key in st.session_state: st.session_state[d4_key] = [x for x in st.session_state[d4_key] if x in flt_opts]
    curr_b2 = st.session_state.get(d4_key, flt_opts if regs else [])
    bot_locs2 = bot_locs1 if sync else st.multiselect(b_l2, options=flt_opts, default=curr_b2 if curr_b2 else (flt_opts if regs else None), key=d4_key)
    d_bot2_def = top_dt2 - timedelta(days=1) if is_mode_b else top_dt2 + timedelta(days=1)
    bot_r2 = st.date_input(b_d2, value=(d_bot2_def,))

# ==========================================
# 4. 獵殺大腦
# ==========================================
async def start_hunt():
    try:
        rid = str(uuid.uuid4()); st.session_state.run_id = rid
        d_bot1_s, d_bot1_e = get_safe_dates(bot_r1); d_bot2_s, d_bot2_e = get_safe_dates(bot_r2)
        d_bot1_list = [d_bot1_s + timedelta(days=i) for i in range((d_bot1_e-d_bot1_s).days + 1)]
        d_bot2_list = [d_bot2_s + timedelta(days=i) for i in range((d_bot2_e-d_bot2_s).days + 1)]
        tasks = []
        for b1_raw, b2_raw in product(bot_locs1, bot_locs2):
            b1, b2 = b1_raw.split(" ")[0], b2_raw.split(" ")[0]
            for db1, db2 in product(d_bot1_list, d_bot2_list):
                if is_mode_b:
                    h1, d2o, d2d, d3o, d3d, h4 = h1_fix, d2o_fix, b1, b2, d3d_fix, h4_fix
                    d1, d2, d3, d4 = d1_fix_dt, db1, db2, d4_fix_dt
                else:
                    h1, d2o, d2d, d3o, d3d, h4 = b1, d2o_fix, d2d_fix, d3o_fix, d3d_fix, b2
                    d1, d2, d3, d4 = db1, d2_fix_dt, d3_fix_dt, db2
                if d1 <= d2 <= d3 <= d4:
                    l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                         {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2.strftime("%Y-%m-%d")},
                         {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3.strftime("%Y-%m-%d")},
                         {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    tasks.append((l, cab, h1, d2o, d2d, d3o, d3d, h4, d1.strftime("%Y-%m-%d"), d2.strftime("%Y-%m-%d"), d3.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

        total_tasks = len(tasks); bar, status, live_table, final_res = st.progress(0), st.empty(), st.empty(), []
        async with httpx.AsyncClient(timeout=40.0) as client:
            aaa, bbb = 0, 0
            if not use_manual_ref:
                status.info("🎯 計算雙核心基準價中..."); b1_ref, b2_ref = bot_locs1[0].split(" ")[0], bot_locs2[0].split(" ")[0]
                if is_mode_b: rd1, rd2, rd3, rd4 = d1_fix_dt, d_bot1_list[0], d_bot2_list[0], d4_fix_dt
                else: rd1, rd2, rd3, rd4 = d_bot1_list[0], d2_fix_dt, d3_fix_dt, d_bot2_list[0]
                l_aaa = [{"fromId": f"{h1_fix if is_mode_b else b1_ref}.AIRPORT", "toId": f"{d2o_fix}.AIRPORT", "date": rd1.strftime("%Y-%m-%d")},
                         {"fromId": f"{d3d_fix}.AIRPORT", "toId": f"{h4_fix if is_mode_b else b2_ref}.AIRPORT", "date": rd4.strftime("%Y-%m-%d")}]
                l_bbb = [{"fromId": f"{d2o_fix}.AIRPORT", "toId": f"{d2d_fix if not is_mode_b else b1_ref}.AIRPORT", "date": rd2.strftime("%Y-%m-%d")},
                         {"fromId": f"{d3o_fix if not is_mode_b else b2_ref}.AIRPORT", "toId": f"{d3d_fix}.AIRPORT", "date": rd3.strftime("%Y-%m-%d")}]
                r_aaa = await fetch_api(client, asyncio.Semaphore(1), (l_aaa, cab, "REF", "REF", "REF", "REF", "REF", "REF", "", "", "", ""), rid, ci_only)
                r_bbb = await fetch_api(client, asyncio.Semaphore(1), (l_bbb, cab, "REF", "REF", "REF", "REF", "REF", "REF", "", "", "", ""), rid, ci_only)
                aaa, bbb = (r_aaa['total'] if r_aaa else 0), (r_bbb['total'] if r_bbb else 0)
                st.session_state.ref_aaa, st.session_state.ref_bbb, st.session_state.ref_price = aaa, bbb, aaa + bbb

            cur_ref = manual_ref_val if use_manual_ref else st.session_state.ref_price; core_ref_live = bbb if not is_mode_b else aaa
            sem, start_t, last_upd = asyncio.Semaphore(workers), time.time(), 0
            coros = [fetch_api(client, sem, t, rid, ci_only) for t in tasks]
            for i, coro in enumerate(asyncio.as_completed(coros)):
                if st.session_state.run_id != rid: return
                r = await coro
                if r and (show_all or (cur_ref - r['total'] >= 0)): final_res.append(r)
                now = time.time()
                if now - last_upd >= 2.0 or i == total_tasks - 1:
                    rps = (i+1)/(now - start_t) if (now - start_t) > 0 else 0
                    eta = (total_tasks - (i+1)) / rps if rps > 0 else 0
                    bar.progress((i+1)/total_tasks, text=f"⚡ {i+1}/{total_tasks} ({((i+1)/total_tasks*100):.1f}%) | {rps:.1f} RPS | 剩餘: {int(eta//60)}分{int(eta%60)}秒")
                    if final_res:
                        temp_sorted = sorted(final_res, key=lambda x: x['total'])[:50]
                        live_table.markdown(f"### 🚀 即時開獎 (目前最優 TOP 50)\n" + generate_table_html(temp_sorted, cur_ref, core_ref_live, core_mode, 50), unsafe_allow_html=True)
                    last_upd = now
            st.session_state.perf_stats = {"time": time.time() - start_t, "dps": total_tasks / (time.time() - start_t)}

        st.session_state.valid_offers = sorted(final_res, key=lambda x: x['total']); live_table.empty()
        if email_on and st.session_state.valid_offers:
            status.info("📧 封裝精算報告中..."); ok, err = send_detailed_email(st.session_state.valid_offers, cur_ref, st.session_state.perf_stats['time'], st.session_state.perf_stats['dps'], st.session_state.ref_aaa, st.session_state.ref_bbb, cab, core_mode)
            if ok: st.success("📧 獵殺完成！已成功發送 Email。")
            else: st.error(f"🚨 Email 失敗: {err}")
        else: st.success("🎯 獵殺完成！")
    finally: st.session_state.run_id = None

if st.button("🚀 啟動極速獵殺 (v43.3)", use_container_width=True):
    st.session_state.valid_offers = []; asyncio.run(start_hunt())

if st.session_state.valid_offers:
    st.markdown("---")
    cur_ref = manual_ref_val if use_manual_ref else st.session_state.ref_price; core_ref = st.session_state.ref_bbb if not is_mode_b else st.session_state.ref_aaa; p = st.session_state.perf_stats
    st.markdown(f"<div style='background:rgba(0,230,118,0.1); padding:15px; border-radius:8px; border-left:5px solid #00e676; margin-bottom:20px;'><b>⏱️ {p.get('time',0):.2f} 秒</b> | <b>⚡ {p.get('dps',0):.2f} 筆/秒</b> | <b>🏆 {len(st.session_state.valid_offers)} 組</b></div>", unsafe_allow_html=True)
    t1, t2 = st.tabs(["🏆 獲利排行榜", "📍 分站點矩陣"])
    with t1:
        table_data = []
        for r in st.session_state.valid_offers:
            d = {"總價 (TWD)": f"{r['total']:,}"}
            if not is_mode_b: d["獲利 (雙基準)"] = f"{cur_ref-r['total']:+,}"; d["比較核心旅程"] = f"{r['total'] - core_ref:+,}"
            else: d["核心旅程票價"] = f"{r['total'] - core_ref:,}"
            d["探索路線"] = f"{get_name(r['h1'])}➔{get_name(r['h4'])}" if not is_mode_b else f"{get_name(r['d2d'])}➔{get_name(r['d3o'])}"
            d["日期"] = f"{r['d1'][5:]}➔{r['d2'][5:]} | {r['d3'][5:]}➔{r['d4'][5:]}"
            d["航班"] = "|".join(r['legs'])
            table_data.append(d)
        st.dataframe(pd.DataFrame(table_data), use_container_width=True, hide_index=True)
    with t2:
        if not is_mode_b:
            routes = sorted(list(set(f"{r['h1']} ➔ {r['h4']}" for r in st.session_state.valid_offers)))
            for rk in routes:
                h1c, h4c = rk.split(" ➔ "); rd = [r for r in st.session_state.valid_offers if r['h1'] == h1c and r['h4'] == h4c]
                st.markdown(generate_matrix_html(rd, cur_ref, f"分析：外站 {get_name(h1c)} ➔ {get_name(h4c)}", core_mode), unsafe_allow_html=True)
        else:
            routes = sorted(list(set(f"{r['d2d']} ➔ {r['d3o']}" for r in st.session_state.valid_offers)))
            for rk in routes:
                d2c, d3c = rk.split(" ➔ "); rd = [r for r in st.session_state.valid_offers if r['d2d'] == d2c and r['d3o'] == d3c]
                st.markdown(generate_matrix_html(rd, cur_ref, f"分析：主行程 {get_name(d2c)} ➔ {get_name(d3c)}", core_mode), unsafe_allow_html=True)
