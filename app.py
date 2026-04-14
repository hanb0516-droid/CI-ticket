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
st.set_page_config(page_title="Flight Actuary | v38.5 ZERO-DROP", page_icon="🎯", layout="wide")

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

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 缺少 API KEY (請在 Secrets 設定 BOOKING_API_KEY)")
    st.stop()

S_SENDER = st.secrets.get("EMAIL_SENDER", "")
S_PWD = st.secrets.get("EMAIL_PASSWORD", "")
S_RECEIVER = st.secrets.get("EMAIL_RECEIVER", "")

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "run_id" not in st.session_state: st.session_state.run_id = None
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000
if "perf_stats" not in st.session_state: st.session_state.perf_stats = {"time": 0, "dps": 0}

# ==========================================
# 1. 核心工具函數 (分流矩陣與 Email)
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
    h.append("</table>")
    return "".join(h)

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
    except Exception as e:
        print(f"Email failed: {e}")

# ==========================================
# 2. 異步核心引擎 (🛡️ 排雷修復：防戰損指數退避)
# ==========================================
async def fetch_api(client, sem, task_data, rid):
    if st.session_state.run_id != rid: return None
    legs, cabin, h1, h4, d1, d4 = task_data
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    
    async with sem:
        # 🛠️ 核心修復：從 2 次重試改為 5 次，保證每一張票都不會因為 429 被吃掉
        for attempt in range(5):
            if st.session_state.run_id != rid: return None
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=20.0)
                if res.status_code == 200:
                    raw = res.json()
                    valid = []
                    for o in raw.get('data', {}).get('flightOffers', []):
                        l_sum = []
                        for seg in o.get('segments', []):
                            for leg in seg.get('legs', []):
                                f = leg.get('flightInfo', {})
                                c_info = f.get('carrierInfo', {})
                                op = c_info.get('operatingCarrier', '')
                                mk = c_info.get('marketingCarrier', '')
                                l_sum.append(f"{mk or op}{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        valid.append({"total": p, "legs": l_sum, "h1": h1[:3], "h4": h4[:3], "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: 
                    # 🛠️ 核心修復：指數退避 (Exponential Backoff)，越撞牆睡越久，打破封鎖
                    await asyncio.sleep((1.5 ** attempt) + random.uniform(0.5, 1.5))
            except Exception: 
                await asyncio.sleep(2.0) # 遇到 Timeout 也給予喘息時間
        return None # 只有真的試了 5 次都失敗，才忍痛丟棄

# ==========================================
# 3. UI 介面
# ==========================================
st.markdown("<style>[data-testid='stAppViewContainer']{background-color:#0b0e14;color:#e0e0e0;}.quota-box{padding:10px;background:rgba(0,230,118,0.05);border-radius:8px;border:1px solid #00e676;margin-bottom:15px;}</style>", unsafe_allow_html=True)
st.markdown(f"<div class='quota-box'>🎯 <b>對標基準：</b> {st.session_state.ref_price:,} TWD</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 獵殺控制台")
    cab_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cab = st.selectbox("艙等", list(cab_map.keys()))
    workers = st.slider("併發上限 (RPS調整)", 20, 100, 80)
    show_all = st.checkbox("👁️ 透視模式 (顯示賠錢票)", value=True)
    email_on = st.checkbox("📧 完成後發送報告", value=True)
    auto_ref = st.checkbox("自動對標直飛", value=True)
    manual_ref = st.number_input("手動基準", value=200000)
    if st.button("🛑 強制重置/停止", type="primary"):
        st.session_state.run_id = None; st.session_state.valid_offers = []; st.rerun()

trip_mode = st.radio("行程模式", ["來回", "多點進出"], horizontal=True)
c1, c2 = st.columns(2)
if trip_mode == "來回":
    with c1: b_org = st.selectbox("起點", ALL_CITIES, index=IDX_TPE); d2_dt = st.date_input("D2 去程", value=date(2026, 6, 11))
    with c2: b_dst = st.selectbox("終點", ALL_CITIES, index=IDX_PRG); d3_dt = st.date_input("D3 回程", value=date(2026, 6, 25))
    d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
else:
    with c1: d2os = st.selectbox("D2 出發", ALL_CITIES, index=IDX_TPE); d2ds = st.selectbox("D2 目的地", ALL_CITIES, index=IDX_PRG); d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
    with c2: d3os = st.selectbox("D3 出發", ALL_CITIES, index=IDX_FRA); d3ds = st.selectbox("D3 目的地", ALL_CITIES, index=IDX_TPE); d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))
    d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

with st.container():
    st.markdown("---")
    sync = st.checkbox("👯 D4 同步 D1 選擇", value=True)
    cr1, cr4 = st.columns(2)
    with cr1:
        regs = st.multiselect("區域快速過濾", list(CI_HUBS.keys()))
        flt_options = [f"{c} ({n})" for r in regs for c, n in CI_HUBS[r].items()] if regs else ALL_CITIES
        d1_h = st.multiselect("📍 D1 起點站", options=flt_options, default=flt_options if regs else None, key=f"d1_select_{hash(tuple(regs))}")
        d1_r = st.date_input("D1 日期 (單日或範圍)", value=(date(2026, 6, 10),))
    with cr4:
        d4_h = d1_h if sync else st.multiselect("📍 D4 終點站", ALL_CITIES, key="d4_manual")
        d4_r = st.date_input("D4 日期 (單日或範圍)", value=(date(2026, 6, 26),))

# ==========================================
# 4. 獵殺執行大腦
# ==========================================
async def start_hunt():
    rid = str(uuid.uuid4()); st.session_state.run_id = rid
    d1_s, d1_e = get_safe_dates(d1_r)
    d4_s, d4_e = get_safe_dates(d4_r)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]
    is_range = len(d1_list) > 1 or len(d4_list) > 1

    tasks = []
    for h1r, h4r in product(d1_h, d4_h):
        h1, h4 = h1r.split(" ")[0], h4r.split(" ")[0]
        for d1, d4 in product(d1_list, d4_list):
            if d1 <= d2_dt and d4 >= d3_dt:
                l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                     {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                tasks.append((l, cab_map[cab], h1r, h4r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks: st.warning("⚠️ 任務量為 0，請檢查日期順序。"); return

    bar = st.progress(0); status = st.empty(); final_res = []
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    
    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        ref_val = manual_ref
        if auto_ref:
            status.info("🎯 正在獲取核心直飛市場基準價...")
            ref_l = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            ref_res = await fetch_api(client, asyncio.Semaphore(1), (ref_l, cab_map[cab], "", "", "", ""), rid)
            if ref_res: ref_val = ref_res['total']; st.session_state.ref_price = ref_val

        sem = asyncio.Semaphore(workers)
        total_start_time = time.time()
        coros = [fetch_api(client, sem, t, rid) for t in tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != rid: return
            r = await coro
            
            if r and (show_all or (ref_val - r['total'] >= 0)): final_res.append(r)
            
            if i % 10 == 0 or i == len(tasks)-1:
                elapsed_now = time.time() - total_start_time
                rps = (i+1)/elapsed_now if elapsed_now > 0 else 0
                bar.progress((i+1)/len(tasks), text=f"⚡ 獵殺中: {i+1}/{len(tasks)} | 速時: {rps:.1f} RPS | 鎖定: {len(final_res)}")

        total_elapsed = time.time() - total_start_time
        final_rps = len(tasks) / total_elapsed if total_elapsed > 0 else 0
        st.session_state.perf_stats = {"time": total_elapsed, "dps": final_rps}

    st.session_state.valid_offers = sorted(final_res, key=lambda x: x['total'])
    
    if email_on and st.session_state.valid_offers:
        status.success("📧 獵殺完成！正在發送滿配 Email 報告...")
        send_detailed_email(st.session_state.valid_offers, ref_val, f"{d2o}➔{d2d}", is_range, total_elapsed, final_rps)
    
    st.session_state.run_id = None; st.rerun()

if st.button("🚀 啟動極速獵殺", use_container_width=True):
    st.session_state.valid_offers = []
    asyncio.run(start_hunt())

# ==========================================
# 5. 網頁戰果展示
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    
    p_time = st.session_state.perf_stats['time']
    p_dps = st.session_state.perf_stats['dps']
    st.markdown(f"""
    <div style='background:rgba(0, 230, 118, 0.1); padding:15px; border-radius:8px; border-left:5px solid #00e676; margin-bottom:20px;'>
        <h4 style='margin:0 0 10px 0; color:#00e676;'>📊 任務執行報告</h4>
        <b>⏱️ 總耗時：</b> <span style='color:#fff;'>{p_time:.2f} 秒</span> &nbsp;&nbsp;|&nbsp;&nbsp; 
        <b>⚡ 平均 DPS (引擎時速)：</b> <span style='color:#fff;'>{p_dps:.2f} 筆/秒</span> &nbsp;&nbsp;|&nbsp;&nbsp;
        <b>🏆 鎖定神票：</b> <span style='color:#fff;'>{len(st.session_state.valid_offers)} 組</span>
    </div>
    """, unsafe_allow_html=True)
    
    t1, t2 = st.tabs(["🏆 獲利神票榜", "📍 分站點矩陣"])
    
    with t1:
        df = pd.DataFrame([{
            "總價 (TWD)": f"{r['total']:,}", "獲利": f"{st.session_state.ref_price-r['total']:,}",
            "站點組合": f"{get_name(r['h1'])} ➔ {get_name(r['h4'])}", "日期": f"{r['d1']}~{r['d4']}", "航班明細": " | ".join(r['legs'])
        } for r in st.session_state.valid_offers])
        st.dataframe(df, use_container_width=True, hide_index=True)
        
    with t2:
        routes = sorted(list(set(f"{r['h1']} ➔ {r['h4']}" for r in st.session_state.valid_offers)))
        if not routes:
            st.info("無獲利矩陣資料")
        else:
            for route_key in routes:
                h1_c, h4_c = route_key.split(" ➔ ")
                route_data = [r for r in st.session_state.valid_offers if r['h1'] == h1_c and r['h4'] == h4_c]
                st.markdown(generate_matrix_html(route_data, st.session_state.ref_price, f"組合分析：{get_name(h1_c)} ➔ {get_name(h4_c)}"), unsafe_allow_html=True)
