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
st.set_page_config(page_title="Flight Actuary | v39.8 THERMAL", page_icon="✈️", layout="wide")

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
    st.error("🚨 缺少 API KEY"); st.stop()

S_SENDER, S_PWD, S_RECEIVER = st.secrets.get("EMAIL_SENDER", ""), st.secrets.get("EMAIL_PASSWORD", ""), st.secrets.get("EMAIL_RECEIVER", "")

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "run_id" not in st.session_state: st.session_state.run_id = None
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

def generate_table_html(res, ref):
    rows = "".join([f"<tr><td>{r['total']:,}</td><td><span style='color:{'#d32f2f' if (ref-r['total'])>=0 else '#1976d2'}'>{'省' if (ref-r['total'])>=0 else '貴'} {abs(ref-r['total']):,}</span></td><td>{get_name(r['h1'])} ➔ {get_name(r['h4'])}</td><td>{r['d1']}/{r['d4']}</td><td><span style='font-size:10px;'>{' | '.join(r['legs'])}</span></td></tr>" for r in res[:50]])
    return f"<table border='1' style='border-collapse:collapse;width:100%;text-align:center;font-size:12px;'><thead><tr style='background:#333;color:#fff;'><th>總價(TWD)</th><th>價差</th><th>路線</th><th>日期組合</th><th>航班明細</th></tr></thead><tbody>{rows}</tbody></table>"

# 🎨 視覺大改版：色溫熱力圖 (Warm/Cold Diverging Colormap)
def generate_matrix_html(res, ref, title):
    if not res: return ""
    d1_dates = sorted(list(set(r['d1'] for r in res)))
    d4_dates = sorted(list(set(r['d4'] for r in res)))
    matrix = {(r['d1'], r['d4']): r for r in res}
    
    # 找出基準價兩端的最大極值，用於漸層比例計算
    diffs = [ref - r['total'] for r in res]
    max_save = max([0] + diffs)
    max_lose = abs(min([0] + diffs))
    
    h = [f"<h4 style='margin-bottom:5px; color:#2c3e50;'>📍 {title}</h4><table border='1' style='border-collapse:collapse;font-size:11px;text-align:center;margin-bottom:15px;'>"]
    h.append("<tr style='background:#333;color:#fff;'><th>D4↘\\D1➡</th>" + "".join([f"<th>{d[5:]}</th>" for d in d1_dates]) + "</tr>")
    
    for d4 in d4_dates:
        row = [f"<tr><td style='background:#f2f2f2; color:#000; font-weight:bold;'>{d4[5:]}</td>" ]
        for d1 in d1_dates:
            r = matrix.get((d1, d4))
            if r:
                diff = ref - r['total']
                
                if diff > 0:
                    # 省錢 (暖色：白色 -> 深紅)
                    ratio = diff / max_save if max_save > 0 else 0
                    r_val = 255
                    g_val = int(255 * (1 - ratio) + 50 * ratio)
                    b_val = int(255 * (1 - ratio) + 50 * ratio)
                elif diff < 0:
                    # 賠錢 (冷色：白色 -> 藍色)
                    ratio = abs(diff) / max_lose if max_lose > 0 else 0
                    r_val = int(255 * (1 - ratio) + 50 * ratio)
                    g_val = int(255 * (1 - ratio) + 120 * ratio)
                    b_val = 255
                else:
                    # 打平 (白色)
                    r_val, g_val, b_val = 255, 255, 255
                    
                bg = f"rgba({r_val},{g_val},{b_val},0.85)"
                
                # 確保在白色背景附近時，字體會自動變深色以供辨識
                luminance = 0.299 * r_val + 0.587 * g_val + 0.114 * b_val
                text_color = "#000" if luminance > 160 else "#fff"

                row.append(f"<td style='background:{bg};padding:5px;color:{text_color};'><b>{r['total']:,}</b><br><span style='color:{text_color};'>{'省' if diff>=0 else '貴'}{abs(diff):,}</span></td>")
            else: 
                row.append("<td style='color:#888;'>-</td>")
        row.append("</tr>")
        h.append("".join(row))
    return "".join(h) + "</table>"

# 🛡️ 通訊防護
def send_detailed_email(res, ref, target_str, is_range, elapsed, dps, version="v39.8"):
    if not S_SENDER or not S_PWD or not S_RECEIVER: return False, "信箱帳密尚未設定"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = MIMEMultipart()
    msg['Subject'] = f"✈️ [{version}] {target_str} 報告 (最低 {res[0]['total']:,} TWD)"
    
    header = f"<div style='background:#2c3e50; color:#fff; padding:15px;'><h2>版本：{version}</h2><p>時間：{now_str}</p></div>"
    stats_html = f"<div style='background:#f8f9fa; padding:10px; border-left:4px solid #00e676; margin-bottom:15px; color:#333;'><b>⏱️ 搜尋總耗時：</b> {elapsed:.2f} 秒<br><b>⚡ 平均 DPS (RPS)：</b> {dps:.2f} 筆/秒<br><b>🎯 直飛基準價：</b> {ref:,} TWD<br><b>🏆 尋獲神票：</b> {len(res)} 組</div>"
    
    if not is_range:
        body = f"{header}{stats_html}<h3>📋 獲利神票榜</h3>{generate_table_html(res, ref)}"
    else:
        body = f"{header}{stats_html}<h3>📋 獲利神票榜 (Top 50)</h3>{generate_table_html(res, ref)}<hr><h3>📊 各站點專屬熱力圖</h3>"
        routes = sorted(list(set(f"{get_name(r['h1'])} ➔ {get_name(r['h4'])}" for r in res)))
        
        max_maps = 3 if len(res) > 2000 else 10
        for route_str in routes[:max_maps]:
            h1_code = route_str.split(" (")[0]
            h4_code = route_str.split(" ➔ ")[1].split(" (")[0]
            route_data = [r for r in res if r['h1'] == h1_code and r['h4'] == h4_code]
            body += generate_matrix_html(route_data, ref, f"路線組合：{route_str}")
        
        if len(routes) > max_maps:
            body += f"<p style='color:#7f8c8d; font-size:12px; margin-top:15px;'>...為避免郵件檔案過大遭 Gmail 伺服器拒收，已自動隱藏其餘 {len(routes) - max_maps} 組熱力圖。請至系統網頁端查看完整數據。</p>"

    msg.attach(MIMEText(f"<html><body>{body}</body></html>", 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(S_SENDER, S_PWD); s.send_message(msg)
        return True, ""
    except Exception as e:
        return False, str(e)

# ==========================================
# 2. 異步引擎
# ==========================================
async def fetch_api(client, sem, task_data, rid, ci_only_flag):
    if st.session_state.run_id != rid: return None
    legs, cabin, h1, h4, d1, d4 = task_data
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
                                op = c_info.get('operatingCarrier', '')
                                mk = c_info.get('marketingCarrier', '')
                                
                                if ci_only_flag and op != "CI" and mk != "CI":
                                    is_valid_airline = False
                                
                                l_sum.append(f"{mk or op}{f.get('flightNumber', '')}")
                        
                        if is_valid_airline:
                            p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                            valid.append({"total": p, "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
                            
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: await asyncio.sleep(2.0)
            except: await asyncio.sleep(1.0)
        return None

# ==========================================
# 3. UI 介面
# ==========================================
with st.sidebar:
    st.header("⚙️ 獵殺控制台 (v39.8)")
    cab = st.selectbox("艙等", ["BUSINESS", "PREMIUM_ECONOMY", "ECONOMY"])
    
    ci_only = st.checkbox("🌸 華航限定 (直營/聯營)", value=True, help="打勾：僅保留華航執飛或聯營之航班\n取消：全球航空不限航空大亂鬥")
    workers = st.slider("併發上限", 20, 100, 50)
    show_all = st.checkbox("👁️ 透視模式 (顯示賠錢票)", value=True)
    
    st.divider()
    use_manual_ref = st.checkbox("🛠️ 使用手動基準價", value=False)
    manual_ref_val = st.number_input("輸入官網直飛價 (TWD)", value=int(st.session_state.ref_price), step=1000)
    
    email_on = st.checkbox("完成後寄送報告", value=True)
    if st.button("🛑 停止任務"): st.session_state.run_id = None; st.rerun()

final_ref_price = manual_ref_val if use_manual_ref else st.session_state.ref_price
st.markdown(f"<div style='padding:10px;background:rgba(0,230,118,0.1);border-radius:8px;'>🎯 <b>當前對標基準價：</b> {final_ref_price:,} TWD {'(手動校準)' if use_manual_ref else '(自動抓取)'}</div>", unsafe_allow_html=True)

trip_mode = st.radio("行程模式", ["來回", "多點進出"], horizontal=True)
c1, c2 = st.columns(2)
if trip_mode == "來回":
    b_org = c1.selectbox("起點", ALL_CITIES, index=IDX_TPE); d2_dt = c1.date_input("去程日期", value=date(2026, 6, 11))
    b_dst = c2.selectbox("終點", ALL_CITIES, index=IDX_PRG); d3_dt = c2.date_input("回程日期", value=date(2026, 6, 25))
    d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
else:
    d2os = c1.selectbox("D2 出發", ALL_CITIES, index=IDX_TPE); d2_dt = c1.date_input("D2 日期", value=date(2026, 6, 11))
    d2ds = c1.selectbox("D2 目的", ALL_CITIES, index=IDX_PRG)
    d3os = c2.selectbox("D3 出發", ALL_CITIES, index=IDX_FRA); d3_dt = c2.date_input("D3 日期", value=date(2026, 6, 25))
    d3ds = c2.selectbox("D3 目的", ALL_CITIES, index=IDX_TPE)
    d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

st.markdown("---")
cr1, cr4 = st.columns(2)
regs = cr1.multiselect("區域快速過濾", list(CI_HUBS.keys()))
flt_opts = [f"{c} ({n})" for r in regs for c, n in CI_HUBS[r].items()] if regs else ALL_CITIES
d1_key = f"d1_sel_{hash(tuple(regs))}"
curr_d1 = st.session_state.get(d1_key, flt_opts if regs else [])
d1_h = cr1.multiselect(f"📍 D1 起點站 ({len(curr_d1)})", options=flt_opts, default=flt_opts if regs else None, key=d1_key)
d1_r = cr1.date_input("D1 日期範圍", value=(date(2026, 6, 10),))
d4_h = cr4.multiselect("📍 D4 終點站", options=flt_opts, default=flt_opts if regs else None)
d4_r = cr4.date_input("D4 日期範圍", value=(date(2026, 6, 26),))

# ==========================================
# 4. 獵殺執行大腦
# ==========================================
async def start_hunt():
    rid = str(uuid.uuid4()); st.session_state.run_id = rid
    d1_s, d1_e = get_safe_dates(d1_r); d4_s, d4_e = get_safe_dates(d4_r)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]

    tasks = []
    for h1r, h4r, d1, d4 in product(d1_h, d4_h, d1_list, d4_list):
        if d1 <= d2_dt and d4 >= d3_dt:
            l = [{"fromId": f"{h1r[:3]}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                 {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                 {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                 {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4r[:3]}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
            tasks.append((l, cab, h1r[:3], h4r[:3], d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks: st.warning("任務量為 0"); return
    bar = st.progress(0); status = st.empty(); final_res = []
    
    async with httpx.AsyncClient(timeout=40.0) as client:
        if not use_manual_ref:
            ref_l = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            ref_res = await fetch_api(client, asyncio.Semaphore(1), (ref_l, cab, d2o, d3d, d2_dt.strftime("%Y-%m-%d"), d3_dt.strftime("%Y-%m-%d")), rid, ci_only)
            if ref_res: st.session_state.ref_price = ref_res['total']

        sem = asyncio.Semaphore(workers)
        total_start_time = time.time()
        coros = [fetch_api(client, sem, t, rid, ci_only) for t in tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != rid: return
            r = await coro
            
            if r and (show_all or (final_ref_price - r['total'] >= 0)): final_res.append(r)
            
            elapsed_now = time.time() - total_start_time
            rps = (i+1)/elapsed_now if elapsed_now > 0 else 0
            bar.progress((i+1)/len(tasks), text=f"⚡ 獵殺中: {i+1}/{len(tasks)} | 速時: {rps:.1f} RPS | 鎖定: {len(final_res)}")

        total_elapsed = time.time() - total_start_time
        final_rps = len(tasks) / total_elapsed if total_elapsed > 0 else 0
        st.session_state.perf_stats = {"time": total_elapsed, "dps": final_rps}

    st.session_state.valid_offers = sorted(final_res, key=lambda x: x['total'])
    is_range = len(d1_list) > 1 or len(d4_list) > 1
    
    if email_on and st.session_state.valid_offers:
        status.info("📧 正在封裝報表並發送 Email (資料量大時需時較長)...")
        is_success, err_msg = send_detailed_email(st.session_state.valid_offers, final_ref_price, f"{d2o}➔{d2d}", is_range, total_elapsed, final_rps)
        if is_success:
            status.success("📧 獵殺完成！已成功寄送 Email 報告。")
        else:
            status.error(f"🚨 Email 寄送失敗！原因: {err_msg}")
    else:
        status.success("🎯 獵殺完成！")
        
    st.session_state.run_id = None; st.rerun()

if st.button("🚀 啟動極速獵殺 (v39.8 THERMAL)", use_container_width=True):
    st.session_state.valid_offers = []
    asyncio.run(start_hunt())

# ==========================================
# 5. 展示
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    
    p_time = st.session_state.perf_stats.get('time', 0)
    p_dps = st.session_state.perf_stats.get('dps', 0)
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
            "總價 (TWD)": f"{r['total']:,}", 
            "獲利": f"{final_ref_price-r['total']:,}",
            "路線": f"{get_name(r['h1'])} ➔ {get_name(r['h4'])}", 
            "日期組合": f"{r['d1']}~{r['d4']}", 
            "航班": " | ".join(r['legs'])
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
                st.markdown(generate_matrix_html(route_data, final_ref_price, f"組合分析：{get_name(h1_c)} ➔ {get_name(h4_c)}"), unsafe_allow_html=True)
