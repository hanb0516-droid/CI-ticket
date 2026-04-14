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
# 0. 全局初始化 & 基準風格
# ==========================================
st.set_page_config(page_title="Flight Actuary | v35.0 FLAGSHIP", page_icon="✈️", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp { background-color: #0b0e14; color: #e0e0e0; }
    html, body, [class*="st-"] { font-size: 13px !important; }
    .quota-box { padding: 10px; background: rgba(0, 230, 118, 0.05); border-radius: 8px; border: 1px solid #00e676; margin-bottom: 15px; }
</style>
""", unsafe_allow_html=True)

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
except KeyError:
    st.error("🚨 缺少 API KEY"); st.stop()

# Email Secrets 防呆讀取
SENDER = st.secrets.get("EMAIL_SENDER")
PWD = st.secrets.get("EMAIL_PASSWORD")
RECEIVER = st.secrets.get("EMAIL_RECEIVER")

# 狀態管理
if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
if "is_hunting" not in st.session_state: st.session_state.is_hunting = False
if "ref_price" not in st.session_state: st.session_state.ref_price = 200000
if "run_id" not in st.session_state: st.session_state.run_id = None

CI_GLOBAL_HUBS = {
    "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
    "東南亞": {"BKK": "曼谷", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光"},
    "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
    "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格"},
    "北美洲": {"LAX": "洛杉磯", "SFO": "舊金山", "ONT": "安大略", "SEA": "西雅圖", "JFK": "紐約", "YVR": "溫哥華"},
    "紐澳": {"SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭"}
}
ALL_CITIES = [f"{code} ({name})" for r, cities in CI_GLOBAL_HUBS.items() for code, name in cities.items()]

def get_city_idx(code):
    for i, s in enumerate(ALL_CITIES):
        if s.startswith(code): return i
    return 0

# ==========================================
# 1. Email 渲染與寄送模組 (排雷一)
# ==========================================
def render_matrix_html(res_list, ref, title_str):
    if not res_list: return "<p>無符合條件的航班。</p>"
    d1_dates = sorted(list(set(r['d1'] for r in res_list)))
    d4_dates = sorted(list(set(r['d4'] for r in res_list)))
    matrix = {}
    prices = [r['total'] for r in res_list]
    min_p, max_p = min(prices) if prices else 0, max(prices) if prices else 0
    for r in res_list:
        key = (r['d1'], r['d4'])
        if key not in matrix or r['total'] < matrix[key]['total']: matrix[key] = r

    html = f"""<div style="background-color: #ffffff; color: #333; padding: 12px; border-radius: 8px; font-family: sans-serif;">
        <h3 style="margin: 0 0 10px 0;">{title_str}</h3>
        <table border="1" style="border-collapse: collapse; text-align: center; width: 100%; font-size: 12px;">
            <tr style="background-color: #333; color: white;"><th>D4↘\\D1➡</th>"""
    for d1 in d1_dates: html += f"<th>{d1[5:]}</th>"
    html += "</tr>"
    for d4 in d4_dates:
        html += f"<tr><td style='background-color: #f2f2f2; font-weight: bold;'>{d4[5:]}</td>"
        for d1 in d1_dates:
            rec = matrix.get((d1, d4))
            if rec:
                save = ref - rec['total']
                alpha = 0.8 if max_p <= min_p else 0.8 - 0.7 * ((rec['total'] - min_p) / (max_p - min_p))
                bg = f"rgba(0, 230, 118, {alpha:.2f})" if save >= 0 else "rgba(255, 182, 193, 0.4)"
                save_text = f"<br><span style='color: {'#d32f2f' if save>=0 else '#1976d2'};'>{'省' if save>=0 else '貴'} {abs(save):,}</span>"
                html += f"<td style='background-color: {bg}; padding: 6px;'><b>{rec['total']:,}</b>{save_text}<br><span style='font-size: 9px; color: #555;'>{rec['h1']}➔{rec['h4']}</span></td>"
            else: html += "<td style='color: #ccc;'>-</td>"
        html += "</tr>"
    return html + "</table></div>"

def send_email_report(res_list, ref, target_str):
    if not SENDER or not PWD or not RECEIVER or not res_list: return
    html_content = render_matrix_html(res_list, ref, f"✈️ 航班獵殺報告 ({target_str}) | 對標直飛: {ref:,}")
    msg = MIMEMultipart()
    msg['From'] = SENDER
    msg['To'] = RECEIVER
    msg['Subject'] = f"✈️ [Flight Radar] 發現 {len(res_list)} 組神票！最低價 {res_list[0]['total']:,} TWD"
    msg.attach(MIMEText(f"<html><body>{html_content}</body></html>", 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login(SENDER, PWD)
            s.send_message(msg)
    except Exception as e:
        print(f"Email failed: {e}")

# ==========================================
# 2. 異步核心引擎
# ==========================================
async def fetch_task_async(client, sem, task_data, current_run_id):
    if st.session_state.run_id != current_run_id: return None
    legs, cabin, h1, h4, d1, d4 = task_data
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    
    async with sem:
        for attempt in range(3):
            if st.session_state.run_id != current_run_id: return None
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"}, timeout=18.0)
                if res.status_code == 200:
                    raw = res.json()
                    valid = []
                    for o in raw.get('data', {}).get('flightOffers', []):
                        l_sum, is_ci = [], True
                        for seg in o.get('segments', []):
                            f = seg.get('legs', [{}])[0].get('flightInfo', {})
                            if f.get('carrierInfo', {}).get('operatingCarrier') != "CI":
                                is_ci = False; break
                            l_sum.append(f"CI{f.get('flightNumber', '')}")
                        p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        if is_ci and len(l_sum) == len(legs):
                            valid.append({"total": p, "legs": l_sum, "h1": h1[:3], "h4": h4[:3], "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429:
                    await asyncio.sleep(1.0 + random.uniform(0.5, 2.0))
            except:
                await asyncio.sleep(0.5)
        return None

# ==========================================
# 3. UI 佈局
# ==========================================
st.markdown(f'<div class="quota-box">🚀 <b>v35.0 旗艦版：</b> Email 模組回歸 & 極限 RPS | 🎯 基準：{st.session_state.ref_price:,}</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 引擎控制")
    cab_map = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cab = st.selectbox("艙等", list(cab_map.keys()))
    workers = st.slider("異步併發上限 (建議80)", 20, 100, 80)
    show_all = st.checkbox("👁️ 透視模式", value=False)
    auto_ref = st.checkbox("自動對標直飛", value=True)
    manual_ref = st.number_input("手動基準", value=200000)
    
    st.markdown("---")
    st.subheader("📬 通知設定")
    email_on = st.checkbox("📧 完成後發送 Email", value=True, disabled=not bool(SENDER))
    if not SENDER: st.caption("⚠️ Secrets 尚未設定 Email 帳密")
    
    st.markdown("---")
    if st.button("🛑 停止 / 重置引擎", type="primary"):
        st.session_state.run_id = None
        st.session_state.is_hunting = False
        st.session_state.valid_offers = []
        st.rerun()

with st.container():
    trip_mode = st.radio("行程模式", ["來回", "多點進出"], horizontal=True)
    c1, c2 = st.columns(2)
    if trip_mode == "來回":
        with c1:
            b_org = st.selectbox("起點", ALL_CITIES, index=get_city_idx("TPE"))
            d2_dt = st.date_input("D2 去程", value=date(2026, 6, 11))
        with c2:
            b_dst = st.selectbox("終點", ALL_CITIES, index=get_city_idx("PRG"))
            d3_dt = st.date_input("D3 回程", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = b_org.split(" ")[0], b_dst.split(" ")[0], b_dst.split(" ")[0], b_org.split(" ")[0]
    else:
        with c1:
            d2os = st.selectbox("D2 起點", ALL_CITIES, index=get_city_idx("TPE"))
            d2ds = st.selectbox("D2 目的地", ALL_CITIES, index=get_city_idx("PRG"))
            d2_dt = st.date_input("D2 日期", value=date(2026, 6, 11))
        with c2:
            d3os = st.selectbox("D3 出發地", ALL_CITIES, index=get_city_idx("FRA"))
            d3ds = st.selectbox("D3 目的地", ALL_CITIES, index=get_city_idx("TPE"))
            d3_dt = st.date_input("D3 日期", value=date(2026, 6, 25))
        d2o, d2d, d3o, d3d = d2os.split(" ")[0], d2ds.split(" ")[0], d3os.split(" ")[0], d3ds.split(" ")[0]

st.markdown("---")
with st.container():
    sync = st.checkbox("👯 D4 同步 D1", value=True)
    cr1, cr4 = st.columns(2)
    with cr1:
        regs = st.multiselect("區域", list(CI_GLOBAL_HUBS.keys()))
        if regs:
            flt = [f"{c} ({n})" for r in regs for c, n in CI_GLOBAL_HUBS[r].items()]
            d1_h = st.multiselect("📍 D1 起點", options=flt, default=flt)
        else: d1_h = st.multiselect("📍 D1 起點", options=ALL_CITIES)
        d1_r = st.date_input("D1 範圍", value=(date(2026, 6, 10), date(2026, 6, 10)))
    with cr4:
        d4_h = d1_h if sync else st.multiselect("📍 D4 終點", ALL_CITIES)
        d4_r = st.date_input("D4 範圍", value=(date(2026, 6, 26), date(2026, 6, 26)))

# ==========================================
# 4. 異步主控台
# ==========================================
async def start_async_hunt():
    d1_s, d1_e = (d1_r[0], d1_r[-1]) if isinstance(d1_r, (list, tuple)) else (d1_r, d1_r)
    d4_s, d4_e = (d4_r[0], d4_r[-1]) if isinstance(d4_r, (list, tuple)) else (d4_r, d4_r)
    tasks = []
    for h1r, h4r in product(d1_h, d4_h):
        h1, h4 = h1r.split(" ")[0], h4r.split(" ")[0]
        for d1, d4 in product([d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)], 
                              [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]):
            if d1 <= d2_dt and d4 >= d3_dt:
                l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                     {"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                     {"fromId": f"{d3d}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                tasks.append((l, cab_map[cab], h1r, h4r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

    if not tasks: st.warning("⚠️ 任務量為 0"); return

    my_run_id = str(uuid.uuid4())
    st.session_state.run_id = my_run_id

    bar = st.progress(0)
    status_area = st.empty()
    res_list = []
    
    limits = httpx.Limits(max_keepalive_connections=100, max_connections=200)
    async with httpx.AsyncClient(timeout=25.0, limits=limits) as client:
        ref_val = manual_ref
        if auto_ref:
            status_area.info("🎯 校準核心直飛價格中...")
            d_legs = [{"fromId": f"{d2o}.AIRPORT", "toId": f"{d2d}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                      {"fromId": f"{d3o}.AIRPORT", "toId": f"{d3d}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
            ref_res = await fetch_task_async(client, asyncio.Semaphore(1), (d_legs, cab_map[cab], "", "", "", ""), my_run_id)
            if ref_res: ref_val = ref_res['total']; st.session_state.ref_price = ref_val

        sem = asyncio.Semaphore(workers)
        start_t = time.time()
        last_ui_update = time.time()
        coros = [fetch_task_async(client, sem, t, my_run_id) for t in tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != my_run_id:
                status_area.warning("🚨 任務已中止！"); return

            r = await coro
            if r and (show_all or (ref_val - r['total'] >= 0)):
                r['ref'] = ref_val
                res_list.append(r)
            
            now = time.time()
            if now - last_ui_update > 1.0 or i == len(tasks) - 1:
                rps = (i + 1) / (now - start_t) if now > start_t else 0
                bar.progress((i + 1) / len(tasks))
                status_area.markdown(f'<div style="color:#00e676; font-weight:bold;">⚡ 進度: {i+1}/{len(tasks)} | 引擎滿載極速: {rps:.1f} RPS | 尋獲: {len(res_list)}</div>', unsafe_allow_html=True)
                last_ui_update = now

    st.session_state.valid_offers = sorted(res_list, key=lambda x: x['total'])[:1000]
    
    # 🛡️ 排雷三：完工後才寄 Email，確保資源不打架
    if st.session_state.run_id == my_run_id and email_on and SENDER and res_list:
        status_area.info("📧 正在生成並發送 Email 報告...")
        target_str = f"{d2o}➔{d2d} | {d3o}➔{d3d}"
        send_email_report(st.session_state.valid_offers, ref_val, target_str)
        st.toast('✅ 獵殺報告已發送至您的信箱！', icon='📧')

    st.session_state.is_hunting = False
    st.session_state.run_id = None
    st.rerun()

if st.button("🚀 啟動異步極速獵殺", disabled=st.session_state.is_hunting, use_container_width=True):
    st.session_state.valid_offers = []
    st.session_state.is_hunting = True
    try: asyncio.run(start_async_hunt())
    except Exception as e: st.error(f"系統異常: {e}"); st.session_state.is_hunting = False

# ==========================================
# 5. 戰果展示 (原生 DataFrame)
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    res = st.session_state.valid_offers
    st.write(f"🏆 成功鎖定 **{len(res)}** 組神票 (對標價: {st.session_state.ref_price:,})")
    
    df_data = []
    for r in res[:50]: # 保留最頂級的 50 組供 UI 快速滑動
        diff = st.session_state.ref_price - r['total']
        df_data.append({
            "總價 (TWD)": f"💰 {r['total']:,}",
            "價差": f"{'🔥 省' if diff>=0 else '📉 貴'} {abs(diff):,}",
            "去程外站 (D1)": f"{r['h1']} ({r['d1']})",
            "回程外站 (D4)": f"{r['h4']} ({r['d4']})",
            "航班號碼": " | ".join(r['legs'])
        })
    st.dataframe(pd.DataFrame(df_data), use_container_width=True, hide_index=True)
