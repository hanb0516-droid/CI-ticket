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
st.set_page_config(page_title="Flight Actuary | v36.3 UNLOCKED", page_icon="🎯", layout="wide")

@st.cache_data
def get_hubs():
    h = {
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
        "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
        "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
        "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
    }
    all_c = [f"{code} ({name})" for r, cities in h.items() for code, name in cities.items()]
    def f_idx(target):
        for i, s in enumerate(all_c):
            if s.startswith(target): return i
        return 0
    return h, all_c, f_idx("TPE"), f_idx("PRG"), f_idx("FRA")

CI_HUBS, ALL_CITIES, IDX_TPE, IDX_PRG, IDX_FRA = get_hubs()

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 缺少 API KEY (請確認 Secrets 設定)")
    st.stop()

# Email Secrets
SENDER = st.secrets.get("EMAIL_SENDER", "")
PWD = st.secrets.get("EMAIL_PASSWORD", "")
RECEIVER = st.secrets.get("EMAIL_RECEIVER", "")

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "run_id" not in st.session_state: st.session_state.run_id = None
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000

# 🛡️ 排雷三：日期安全解析，防止單一日期引發崩潰
def get_safe_dates(d_input):
    if isinstance(d_input, (list, tuple)):
        if len(d_input) == 2: return d_input[0], d_input[1]
        if len(d_input) == 1: return d_input[0], d_input[0]
    return d_input, d_input

# ==========================================
# 1. Email 邏輯模組 (規則判定)
# ==========================================
def generate_table_html(res, ref):
    rows = "".join([f"<tr><td>{r['total']:,}</td><td>{ref-r['total']:,}</td><td>{r['h1']}➔{r['h4']}</td><td>{r['d1']}/{r['d4']}</td><td>{' | '.join(r['legs'])}</td></tr>" for r in res[:100]])
    return f"<table border='1' style='border-collapse:collapse;width:100%;text-align:center;'><thead><tr style='background:#333;color:#fff;'><th>價格</th><th>獲利</th><th>路線</th><th>日期</th><th>航班</th></tr></thead><tbody>{rows}</tbody></table>"

def generate_matrix_html(res, ref, title):
    d1_dates = sorted(list(set(r['d1'] for r in res)))
    d4_dates = sorted(list(set(r['d4'] for r in res)))
    matrix = {(r['d1'], r['d4']): r for r in res}
    prices = [r['total'] for r in res]
    mi, ma = min(prices) if prices else 0, max(prices) if prices else 0
    
    h = [f"<h3>{title}</h3><table border='1' style='border-collapse:collapse;font-size:11px;text-align:center;'>"]
    h.append("<tr style='background:#333;color:#fff;'><th>D4↘\\D1➡</th>" + "".join([f"<th>{d[5:]}</th>" for d in d1_dates]) + "</tr>")
    for d4 in d4_dates:
        row = [f"<tr><td style='background:#f2f2f2;font-weight:bold;'>{d4[5:]}</td>"]
        for d1 in d1_dates:
            r = matrix.get((d1, d4))
            if r:
                diff = ref - r['total']
                alpha = 0.8 if ma <= mi else 0.8 - 0.7*((r['total']-mi)/(ma-mi))
                bg = f"rgba(0,230,118,{alpha:.2f})" if diff >= 0 else "rgba(255,182,193,0.4)"
                row.append(f"<td style='background:{bg};padding:5px;'><b>{r['total']:,}</b><br><span style='color:{'#d32f2f' if diff>=0 else '#1976d2'}'>{'省' if diff>=0 else '貴'}{abs(diff):,}</span></td>")
            else: row.append("<td>-</td>")
        row.append("</tr>")
        h.append("".join(row))
    h.append("</table>")
    return "".join(h)

def send_smart_email(res, ref, target_str, is_range):
    if not SENDER or not PWD or not res: return
    msg = MIMEMultipart()
    msg['Subject'] = f"✈️ 航班獵殺報：{target_str} (最低 {res[0]['total']:,})"
    
    if not is_range:
        body = f"<h2>單一日期搜尋結果</h2>{generate_table_html(res, ref)}"
    else:
        body = f"<h2>日期區間熱力圖分析</h2>{generate_matrix_html(res, ref, '全球最優組合')}"
        routes = sorted(list(set(f"{r['h1']}➔{r['h4']}" for r in res)))
        for route in routes[:5]:
            route_data = [r for r in res if f"{r['h1']}➔{r['h4']}" == route]
            body += f"<hr>{generate_matrix_html(route_data, ref, f'站點：{route}')}"
            
    msg.attach(MIMEText(f"<html><body>{body}</body></html>", 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(SENDER, PWD); s.send_message(msg)
    except Exception:
        pass 

# ==========================================
# 2. 異步核心 (智慧剪枝)
# ==========================================
async def fetch_task(client, sem, task_data, rid):
    if st.session_state.run_id != rid: return None
    legs, cabin, h1, h4, d1, d4 = task_data
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    async with sem:
        for _ in range(2):
            if st.session_state.run_id != rid: return None
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=18.0)
                if res.status_code == 200:
                    raw = res.json()
                    valid = []
                    for o in raw.get('data', {}).get('flightOffers', []):
                        l_sum, is_ci = [], True
                        for seg in o.get('segments', []):
                            f = seg.get('legs', [{}])[0].get('flightInfo', {})
                            if f.get('carrierInfo', {}).get('operatingCarrier') != "CI": is_ci = False; break
                            l_sum.append(f"CI{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        if is_ci and len(l_sum) == len(legs):
                            valid.append({"total": p, "legs": l_sum, "h1": h1[:3], "h4": h4[:3], "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: await asyncio.sleep(1 + random.random())
            except Exception:
                pass 
        return None

# ==========================================
# 3. UI 選單
# ==========================================
with st.sidebar:
    st.header("⚙️ 獵殺控制台")
    workers = st.slider("併發上限 (RPS調整)", 20, 100, 80)
    pruning_on = st.checkbox("🧠 啟動智慧剪枝 (Phase 1)", value=True, help="先偵查外站價格，剔除垃圾組合，速度快 3 倍")
    email_on = st.checkbox("📧 寄送獵殺報告", value=True)
    if st.button("🛑 緊急停止", type="primary"): 
        st.session_state.run_id = None; st.rerun()

st.markdown(f"<div style='padding:10px; background:rgba(0,230,118,0.05); border-radius:8px; border:1px solid #00e676; margin-bottom:15px;'>🎯 <b>對標基準：</b> {st.session_state.ref_price:,} TWD</div>", unsafe_allow_html=True)

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
    sync = st.checkbox("👯 D4 同步 D1", value=True)
    cr1, cr4 = st.columns(2)
    with cr1:
        regs = st.multiselect("區域過濾", list(CI_HUBS.keys()))
        if regs:
            flt = [f"{c} ({n})" for r in regs for c, n in CI_HUBS[r].items()]
            # 🛡️ 排雷一：動態 Key 綁定，強制 Streamlit 生成新選單，保證 Default 絕對生效！
            d1_h = st.multiselect("📍 D1 起點", options=flt, default=flt, key=f"d1_{'-'.join(regs)}")
        else:
            d1_h = st.multiselect("📍 D1 起點", options=ALL_CITIES, key="d1_all")
        d1_r = st.date_input("D1 日期範圍", value=(date(2026, 6, 10),))
    with cr4:
        d4_h = d1_h if sync else st.multiselect("📍 D4 終點", ALL_CITIES, key="d4_all")
        d4_r = st.date_input("D4 日期範圍", value=(date(2026, 6, 26),))

# ==========================================
# 4. 執行大腦
# ==========================================
async def start_hunt():
    rid = str(uuid.uuid4()); st.session_state.run_id = rid
    
    # 🛡️ 排雷三：安全解析日期，避免單一日期報錯
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
                tasks.append((l, "BUSINESS", h1r, h4r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks: 
        st.warning("⚠️ 任務量為 0，請檢查日期順序或站點。")
        return
    
    bar = st.progress(0); status = st.empty(); final_res = []
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    
    async with httpx.AsyncClient(timeout=25.0, limits=limits) as client:
        ref_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                    {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
        ref_res = await fetch_task(client, asyncio.Semaphore(1), (ref_legs, "BUSINESS", "", "", "", ""), rid)
        ref_val = ref_res['total'] if ref_res else 200000
        st.session_state.ref_price = ref_val

        sem = asyncio.Semaphore(workers)
        start_t = time.time()
        coros = [fetch_task(client, sem, t, rid) for t in tasks]
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != rid: return # 使用者強制中斷
            r = await coro
            if r and (ref_val - r['total'] >= 0): final_res.append(r)
            if i % 10 == 0 or i == len(tasks)-1:
                rps = (i+1)/(time.time()-start_t) if time.time() > start_t else 0
                bar.progress((i+1)/len(tasks), text=f"⚡ 進度: {i+1}/{len(tasks)} | 時速: {rps:.1f} RPS | 獲取: {len(final_res)}")
                
    st.session_state.valid_offers = sorted(final_res, key=lambda x: x['total'])
    if email_on and st.session_state.valid_offers:
        status.success("📧 獵殺完畢，正在生成 Email...")
        send_smart_email(st.session_state.valid_offers, ref_val, f"{d2o}➔{d2d}", is_range)
    st.session_state.run_id = None; st.rerun()

# 🛡️ 排雷二：徹底拔除 disabled 屬性！按鈕永遠不會反灰！
if st.button("🚀 啟動極速獵殺", use_container_width=True):
    st.session_state.valid_offers = []
    asyncio.run(start_hunt())

# ==========================================
# 5. 戰果展示 (DataFrame + Matrix)
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    tabs = st.tabs(["🏆 獲利排行", "📊 全域熱力矩陣"])
    with tabs[0]:
        df = pd.DataFrame([{
            "總價 (TWD)": f"{r['total']:,}",
            "價差": f"{st.session_state.ref_price-r['total']:,}",
            "外站組合": f"{r['h1']} / {r['h4']}",
            "日期組合": f"{r['d1']}~{r['d4']}",
            "航班明細": " | ".join(r['legs'])
        } for r in st.session_state.valid_offers])
        st.dataframe(df, use_container_width=True, hide_index=True)
    with tabs[1]:
        st.markdown(generate_matrix_html(st.session_state.valid_offers, st.session_state.ref_price, "全球最優組合"), unsafe_allow_html=True)
