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
st.set_page_config(page_title="Flight Actuary | v39.2 STABLE", page_icon="🎯", layout="wide")

@st.cache_data
def get_hubs():
    h = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
        "港澳": {"HKG": "香港", "MFM": "澳門"},
        "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
        "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
    }
    all_c = [f"{code} ({name})" for r, cities in h.items() for code, name in cities.items()]
    flat_map = {code: name for r in h.values() for code, name in r.items()}
    def f_idx(target):
        for i, s in enumerate(all_c):
            if s.startswith(target): return i
        return 0
    return h, all_c, flat_map, f_idx("TPE"), f_idx("PRG"), f_idx("FRA")

CI_HUBS, ALL_CITIES, AIRPORT_MAP, IDX_TPE, IDX_PRG, IDX_FRA = get_hubs()

# 🛡️ 修復點：確保 API_KEY 在全域正確獲取
try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 缺少 API KEY")
    st.stop()

S_SENDER = st.secrets.get("EMAIL_SENDER", "")
S_PWD = st.secrets.get("EMAIL_PASSWORD", "")
S_RECEIVER = st.secrets.get("EMAIL_RECEIVER", "")

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "run_id" not in st.session_state: st.session_state.run_id = None
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000
if "perf_stats" not in st.session_state: st.session_state.perf_stats = {"time": 0, "dps": 0}
if "debug_logs" not in st.session_state: st.session_state.debug_logs = set()

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

def generate_table_html(res, ref):
    rows = "".join([f"<tr><td>{r['total']:,}</td><td><span style='color:{'#d32f2f' if (ref-r['total'])>=0 else '#1976d2'}'>{'省' if (ref-r['total'])>=0 else '貴'} {abs(ref-r['total']):,}</span></td><td>{get_name(r['h1'])} ➔ {get_name(r['h4'])}</td><td>{r['d1']}/{r['d4']}</td><td><span style='font-size:10px;'>{' | '.join(r['legs'])}</span></td></tr>" for r in res[:50]])
    return f"<table border='1' style='border-collapse:collapse;width:100%;text-align:center;font-size:12px;'><thead><tr style='background:#333;color:#fff;'><th>總價(TWD)</th><th>價差</th><th>路線</th><th>日期組合</th><th>航班明細</th></tr></thead><tbody>{rows}</tbody></table>"

def generate_matrix_html(res, ref, title):
    if not res: return ""
    d1_dates = sorted(list(set(r['d1'] for r in res)))
    d4_dates = sorted(list(set(r['d4'] for r in res)))
    matrix = {(r['d1'], r['d4']): r for r in res}
    prices = [r['total'] for r in res]
    mi, ma = min(prices), max(prices)
    h = [f"<h4 style='margin-bottom:5px; color:#2c3e50;'>📍 {title}</h4><table border='1' style='border-collapse:collapse;font-size:11px;text-align:center;margin-bottom:15px;'>"]
    h.append("<tr style='background:#333;color:#fff;'><th>D4↘\\D1➡</th>" + "".join([f"<th>{d[5:]}</th>" for d in d1_dates]) + "</tr>")
    for d4 in d4_dates:
        row = [f"<tr><td style='background:#f2f2f2;font-weight:bold;'>{d4[5:]}</td>" ]
        for d1 in d1_dates:
            r = matrix.get((d1, d4))
            if r:
                diff = ref - r['total']
                alpha = 0.8 if ma <= mi else 0.8 - 0.7*((r['total']-mi)/(ma-mi))
                bg = f"rgba(0,230,118,{alpha:.2f})" if diff >= 0 else "rgba(255,182,193,0.4)"
                row.append(f"<td style='background:{bg};padding:5px;'><b>{r['total']:,}</b><br><span style='color:{'#d32f2f' if diff>=0 else '#1976d2'}'>{'省' if diff>=0 else '貴'}{abs(diff):,}</span></td>")
            else: row.append("<td style='color:#ccc;'>-</td>")
        row.append("</tr>")
        h.append("".join(row))
    return "".join(h) + "</table>"

def send_detailed_email(res, ref, target_str, is_range, elapsed, dps):
    if not S_SENDER or not S_PWD or not S_RECEIVER: return
    msg = MIMEMultipart()
    msg['From'], msg['To'] = S_SENDER, S_RECEIVER
    msg['Subject'] = f"✈️ [Flight Radar] {target_str} (最低 {res[0]['total']:,} TWD)"
    stats_html = f"<div style='background:#f8f9fa; padding:10px; border-left:4px solid #00e676; margin-bottom:15px;'><b>⏱️ 搜尋總耗時：</b> {elapsed:.2f} 秒<br><b>⚡ 平均 DPS (RPS)：</b> {dps:.2f} 筆/秒<br><b>🎯 直飛基準價：</b> {ref:,} TWD</div>"
    if not is_range:
        body = f"<h2>單一日期精確搜尋結果</h2>{stats_html}<h3>📋 獲利神票榜</h3>{generate_table_html(res, ref)}"
    else:
        body = f"<h2>日期區間綜合分析報告</h2>{stats_html}<h3>📋 獲利神票榜 (Top 50)</h3>{generate_table_html(res, ref)}<hr><h3>📊 各站點專屬熱力圖</h3>"
        routes = sorted(list(set(f"{get_name(r['h1'])} ➔ {get_name(r['h4'])}" for r in res)))
        for route_str in routes[:10]:
            h1_code = route_str.split(" (")[0]
            h4_code = route_str.split(" ➔ ")[1].split(" (")[0]
            route_data = [r for r in res if r['h1'] == h1_code and r['h4'] == h4_code]
            body += generate_matrix_html(route_data, ref, f"路線組合：{route_str}")
    msg.attach(MIMEText(f"<html><body style='font-family:sans-serif;'>{body}</body></html>", 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(S_SENDER, S_PWD); s.send_message(msg)
    except Exception: pass

# ==========================================
# 2. 異步核心引擎 (🛡️ 修復 JSON 與 變數作用域)
# ==========================================
async def fetch_api(client, sem, task_data, rid, api_key_val):
    if st.session_state.run_id != rid: return None
    legs, cabin, h1, h4, d1, d4 = task_data
    # 🛡️ 修復點：不要對 legs 重複 json.loads
    route_str = f"{h1}-{h4}"
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": api_key_val, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    async with sem:
        for _ in range(2):
            if st.session_state.run_id != rid: return None
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=60.0)
                if res.status_code == 200:
                    raw = res.json()
                    offers = raw.get('data', {}).get('flightOffers', [])
                    if not offers:
                        st.session_state.debug_logs.add(f"⚠️ 找不到航班: {route_str} ({cabin})")
                        return None
                    valid = []
                    for o in offers:
                        l_sum = []
                        for seg in o.get('segments', []):
                            for leg in seg.get('legs', []):
                                f = leg.get('flightInfo', {})
                                c_info = f.get('carrierInfo', {})
                                op, mk = c_info.get('operatingCarrier', ''), c_info.get('marketingCarrier', '')
                                l_sum.append(f"{mk or op}{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        valid.append({"total": p, "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: await asyncio.sleep(2.0 + random.random())
                else: st.session_state.debug_logs.add(f"❌ HTTP {res.status_code}: {route_str}")
            except Exception as e:
                st.session_state.debug_logs.add(f"💥 異常: {route_str} ({type(e).__name__})")
        return None

# ==========================================
# 3. UI 介面
# ==========================================
st.markdown("<style>[data-testid='stAppViewContainer']{background-color:#0b0e14;color:#e0e0e0;}.quota-box{padding:10px;background:rgba(0,230,118,0.05);border-radius:8px;border:1px solid #00e676;margin-bottom:15px;}</style>", unsafe_allow_html=True)

# 🛡️ 修復點：修正 AttributeError 語法
ref_display = st.session_state.get('ref_price', 200000)
st.markdown(f"<div class='quota-box'>🎯 <b>對標基準：</b> {ref_display:,} TWD</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 獵殺控制台")
    cab_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cab = st.selectbox("艙等", list(cab_map.keys()))
    workers = st.slider("併發上限", 20, 100, 80)
    show_all = st.checkbox("👁️ 透視模式", value=True)
    email_on = st.checkbox("📧 寄送報告", value=True)
    auto_ref = st.checkbox("自動校準基準", value=True)
    if st.button("🛑 停止/重置"): st.session_state.run_id = None; st.session_state.valid_offers = []; st.rerun()

trip_mode = st.radio("行程模式", ["來回", "多點進出"], horizontal=True)
c1, c2 = st.columns(2)
if trip_mode == "來回":
    with c1: b_org = st.selectbox("起點", ALL_CITIES, index=IDX_TPE); d2_dt = st.date_input("去程日期", value=date(2026, 6, 11))
    with c2: b_dst = st.selectbox("終點", ALL_CITIES, index=IDX_PRG); d3_dt = st.date_input("回程日期", value=date(2026, 6, 25))
    d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
else:
    with c1: d2os = st.selectbox("D2 出發", ALL_CITIES, index=IDX_TPE); d2ds = st.selectbox("D2 目的", ALL_CITIES, index=IDX_PRG); d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
    with c2: d3os = st.selectbox("D3 出發", ALL_CITIES, index=IDX_FRA); d3ds = st.selectbox("D3 目的", ALL_CITIES, index=IDX_TPE); d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))
    d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

st.markdown("---")
sync = st.checkbox("👯 D4 同步 D1", value=True)
cr1, cr4 = st.columns(2)
with cr1:
    regs = st.multiselect("區域過濾", list(CI_HUBS.keys()))
    flt_options = [f"{c} ({n})" for r in regs for c, n in CI_HUBS[r].items()] if regs else ALL_CITIES
    d1_key = f"d1_select_{hash(tuple(regs))}"
    curr_d1 = st.session_state.get(d1_key, flt_options if regs else [])
    # 🛡️ 修復點：D1 計數器
    d1_h = st.multiselect(f"📍 D1 起點站 ({len(curr_d1)})", options=flt_options, default=flt_options if regs else None, key=d1_key)
    d1_r = st.date_input("D1 範圍", value=(date(2026, 6, 10),))
with cr4:
    d4_h = d1_h if sync else st.multiselect("📍 D4 終點站", ALL_CITIES, key="d4_manual")
    d4_r = st.date_input("D4 範圍", value=(date(2026, 6, 26),))

# ==========================================
# 4. 執行大腦
# ==========================================
async def start_hunt():
    st.session_state.debug_logs.clear()
    rid = str(uuid.uuid4()); st.session_state.run_id = rid
    d1_s, d1_e = get_safe_dates(d1_r)
    d4_s, d4_e = get_safe_dates(d4_r)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]

    tasks = []
    for h1r, h4r in product(d1_h, d4_h):
        h1, h4 = h1r.split(" ")[0], h4r.split(" ")[0]
        for d1, d4 in product(d1_list, d4_list):
            if d1 <= d2_dt and d4 >= d3_dt:
                l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                     {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                tasks.append((l, cab_map[cab], h1, h4, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks: st.warning("任務量為 0"); return
    bar = st.progress(0); status = st.empty(); final_res = []
    
    async with httpx.AsyncClient(timeout=60.0, limits=httpx.Limits(max_keepalive_connections=150, max_connections=250)) as client:
        ref_val = 200000
        if auto_ref:
            status.info("🎯 校準對標價...")
            ref_l = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            ref_res = await fetch_api(client, asyncio.Semaphore(1), (ref_l, cab_map[cab], d2o, d3d, d2_dt.strftime("%Y-%m-%d"), d3_dt.strftime("%Y-%m-%d")), rid, API_KEY)
            if ref_res: ref_val = ref_res['total']; st.session_state.ref_price = ref_val

        sem = asyncio.Semaphore(workers)
        start_t = time.time()
        coros = [fetch_api(client, sem, t, rid, API_KEY) for t in tasks]
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != rid: return
            r = await coro
            if r and (show_all or (ref_val - r['total'] >= 0)): final_res.append(r)
            if i % 5 == 0 or i == len(tasks)-1:
                elapsed = time.time()-start_t
                rps = (i+1)/elapsed if elapsed > 0 else 0
                bar.progress((i+1)/len(tasks), text=f"⚡ 進度: {i+1}/{len(tasks)} | RPS: {rps:.1f} | 獲取: {len(final_res)}")

        total_elapsed = time.time() - start_t
        st.session_state.perf_stats = {"time": total_elapsed, "dps": len(tasks)/total_elapsed if total_elapsed > 0 else 0}

    st.session_state.valid_offers = sorted(final_res, key=lambda x: x['total'])
    if email_on and st.session_state.valid_offers:
        status.success("📧 獵殺完成！寄送報告...")
        send_detailed_email(st.session_state.valid_offers, ref_val, f"{d2o}➔{d2d}", (len(d1_list)>1 or len(d4_list)>1), total_elapsed, st.session_state.perf_stats['dps'])
    st.session_state.run_id = None; st.rerun()

if st.button("🚀 啟動極速獵殺", use_container_width=True):
    st.session_state.valid_offers = []
    asyncio.run(start_hunt())

# ==========================================
# 5. 展示
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    p = st.session_state.perf_stats
    st.info(f"⏱️ 耗時: {p['time']:.2f}s | ⚡ DPS: {p['dps']:.2f} | 🏆 神票: {len(st.session_state.valid_offers)}")
    t1, t2 = st.tabs(["🏆 獲利榜", "📍 分站矩陣"])
    with t1:
        df = pd.DataFrame([{
            "總價": f"{r['total']:,}", "價差": f"{st.session_state.ref_price-r['total']:,}",
            "組合": f"{get_name(r['h1'])}➔{get_name(r['h4'])}", "日期": f"{r['d1']}~{r['d4']}", "航班": "|".join(r['legs'])
        } for r in st.session_state.valid_offers])
        st.dataframe(df, use_container_width=True, hide_index=True)
    with t2:
        routes = sorted(list(set(f"{r['h1']}➔{r['h4']}" for r in st.session_state.valid_offers)))
        for route in routes:
            h1_c, h4_c = route.split("➔")
            rd = [r for r in st.session_state.valid_offers if r['h1']==h1_c and r['h4']==h4_c]
            st.markdown(generate_matrix_html(rd, st.session_state.ref_price, f"組合：{get_name(h1_c)}➔{get_name(h4_c)}"), unsafe_allow_html=True)

if st.session_state.debug_logs:
    with st.expander("🔍 偵錯日誌"):
        for log in list(st.session_state.debug_logs)[:20]: st.code(log)
