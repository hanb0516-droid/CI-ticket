import streamlit as st
import httpx
import asyncio
import json
import time
import smtplib
from datetime import datetime, timedelta, date
from itertools import product
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==========================================
# 0. UI 初始化 & 旗艦級樣式
# ==========================================
st.set_page_config(page_title="Flight Actuary | FULL CONTROL", page_icon="💎", layout="wide")

st.markdown("""
<style>
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    [data-testid="stAppViewContainer"], .stApp {
        background-image: linear-gradient(rgba(10, 15, 30, 0.6), rgba(10, 15, 30, 0.8)), 
        url("https://images.unsplash.com/photo-1464010141071-6d7c711796be?q=80&w=2074&auto=format&fit=crop");
        background-size: cover !important; background-position: center !important; background-attachment: fixed !important;
    }
    html, body, [class*="st-"] { font-size: 13px !important; color: #e0e0e0; }
    .custom-title {
        background: linear-gradient(45deg, #00e676, #00b0ff); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        font-weight: 900; font-size: 2.2rem !important; text-shadow: 0px 5px 20px rgba(0, 230, 118, 0.2);
    }
    .quota-box {
        padding: 10px; background: rgba(0, 230, 118, 0.05); border-radius: 8px; border: 1px solid #00e676; margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
    SENDER = st.secrets.get("EMAIL_SENDER")
    PWD = st.secrets.get("EMAIL_PASSWORD")
    RECEIVER = st.secrets.get("EMAIL_RECEIVER")
except KeyError:
    st.error("🚨 Secrets 配置有誤！請檢查 Secrets 設定。"); st.stop()

if "valid_offers" not in st.session_state: st.session_state.valid_offers = []
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
# 1. 核心異步引擎
# ==========================================
async def fetch_flight_async(client, semaphore, legs, cabin, h1="", h4="", d1="", d4=""):
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    async with semaphore:
        for attempt in range(4):
            try:
                res = await client.get(url, headers=headers, params={
                    "legs": json.dumps(legs), "cabinClass": cabin, "adults": "1", "currency_code": "TWD"
                }, timeout=25.0)
                if res.status_code == 200:
                    data = res.json()
                    valid = []
                    for offer in data.get('data', {}).get('flightOffers', []):
                        l_sum, is_ci = [], True
                        for seg in offer.get('segments', []):
                            f_info = seg.get('legs', [{}])[0].get('flightInfo', {})
                            car = f_info.get('carrierInfo', {}).get('operatingCarrier') or '??'
                            if car != "CI": is_ci = False; break
                            l_sum.append(f"{car}{f_info.get('flightNumber', '')}")
                        price = offer.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                        if is_ci and len(l_sum) == (4 if h1 else 2) and price > 0:
                            valid.append({"total": price, "legs": l_sum, "h1": h1, "h4": h4, "d1": d1, "d4": d4})
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429:
                    await asyncio.sleep(1.5 * (2 ** attempt))
                    continue
                return None
            except:
                await asyncio.sleep(1)
        return None

# ==========================================
# 📊 UI 渲染與 Email 模組
# ==========================================
def render_matrix_html(res_list, ref, title_str):
    if not res_list: return "<p style='color: #ff4b4b;'>⚠️ 此區間無符合條件之純華航航班。</p>"
    d1_dates = sorted(list(set(r['d1'] for r in res_list)))
    d4_dates = sorted(list(set(r['d4'] for r in res_list)))
    matrix = {}
    min_p, max_p = float('inf'), 0
    for r in res_list:
        key = (r['d1'], r['d4'])
        if key not in matrix or r['total'] < matrix[key]['total']:
            matrix[key] = r
            min_p, max_p = min(min_p, r['total']), max(max_p, r['total'])

    html = f"""<div style="background-color: #ffffff; color: #333; padding: 12px; border-radius: 8px; overflow-x: auto;">
        <h4 style="margin: 0 0 10px 0; font-size: 14px;">{title_str}</h4>
        <table border="1" style="border-collapse: collapse; text-align: center; width: 100%; font-size: 11px; min-width: 600px;">
            <tr style="background-color: #333; color: white;"><th>D4↘\\D1➡</th>"""
    for d1 in d1_dates: html += f"<th>{d1[5:]}</th>"
    html += "</tr>"
    for d4 in d4_dates:
        html += f"<tr><th style='background-color: #f2f2f2;'>{d4[5:]}</th>"
        for d1 in d1_dates:
            rec = matrix.get((d1, d4))
            if rec:
                save = ref - rec['total']
                alpha = 0.8 if max_p <= min_p else 0.8 - 0.7 * ((rec['total'] - min_p) / (max_p - min_p))
                bg = f"rgba(0, 230, 118, {alpha:.2f})" if save >= 0 else "rgba(255, 182, 193, 0.4)"
                save_text = f"<div style='color: {'#d32f2f' if save>=0 else '#1976d2'}; font-weight: bold;'>{'省' if save>=0 else '貴'} {abs(save):,}</div>"
                html += f"<td style='background-color: {bg}; padding: 4px;'><b>{rec['total']:,}</b>{save_text}<div style='font-size: 9px; color: #666;'>{rec['h1'][:3]}➔{rec['h4'][:3]}</div></td>"
            else: html += "<td style='color: #ccc;'>-</td>"
        html += "</tr>"
    return html + "</table></div>"

def send_email_report(res_list, ref, target_str):
    if not SENDER or not PWD or not res_list: return
    html_matrix = render_matrix_html(res_list, ref, f"全球最優解矩陣 (對標直飛：{ref:,})")
    msg = MIMEMultipart()
    msg['From'], msg['To'], msg['Subject'] = SENDER, RECEIVER, f"✈️ [ULTRA] {target_str} 捕捉成功 (最低 {min(r['total'] for r in res_list):,})"
    msg.attach(MIMEText(f"<html><body>{html_matrix}</body></html>", 'html', 'utf-8'))
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(SENDER, PWD); s.send_message(msg)
    except: pass

# ==========================================
# 2. UI 配置區 (🛡️ 修復 UI 連動)
# ==========================================
st.markdown('<p class="custom-title">⚡ ULTRA FULL-CONTROL RADAR</p>', unsafe_allow_html=True)
st.markdown(f'<div class="quota-box">💎 <b>全功能連動模式：</b> 支援開口行程 | 🎯 基準：{st.session_state.ref_price:,} TWD</div>', unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ 核心配置")
    trip_mode = st.radio("行程模式", ["來回", "多點進出"])
    cabin_opt = {"商務艙": "BUSINESS", "豪經艙": "PREMIUM_ECONOMY", "經濟艙": "ECONOMY"}
    cabin = st.selectbox("艙等", list(cabin_opt.keys()))
    auto_ref = st.checkbox("自動對標直飛價", value=True)
    manual_ref = st.number_input("手動預算", value=200000)
    strict_sync = st.checkbox("👯 D1/D4 必須同站點", value=True)
    show_all = st.checkbox("👁️ 透視模式 (含賠錢票)", value=False)
    email_on = st.checkbox("📧 完成後發送 Email", value=True)

c1, c2 = st.columns(2)
with c1:
    st.subheader("📌 核心行程 (D2/D3)")
    if trip_mode == "來回":
        base_org = st.selectbox("起點 (TPE)", ALL_FORMATTED_CITIES, index=0)
        base_dst = st.selectbox("終點 (海外)", ALL_FORMATTED_CITIES, index=5)
        d2_o_code, d2_d_code = base_org.split(" ")[0], base_dst.split(" ")[0]
        d3_o_code, d3_d_code = d2_d_code, d2_o_code
    else:
        col_d2a, col_d2b = st.columns(2)
        with col_d2a: d2_o = st.selectbox("D2 出發地", ALL_FORMATTED_CITIES, index=0)
        with col_d2b: d2_d = st.selectbox("D2 目的地", ALL_FORMATTED_CITIES, index=5)
        col_d3a, col_d3b = st.columns(2)
        with col_d3a: d3_o = st.selectbox("D3 出發地", ALL_FORMATTED_CITIES, index=32) # 範例: PRG
        with col_d3b: d3_d = st.selectbox("D3 目的地", ALL_FORMATTED_CITIES, index=0)
        d2_o_code, d2_d_code = d2_o.split(" ")[0], d2_d.split(" ")[0]
        d3_o_code, d3_d_code = d3_o.split(" ")[0], d3_d.split(" ")[0]
    
    d2_dt = st.date_input("D2 出發日期", value=date(2026, 6, 11))
    d3_dt = st.date_input("D3 回程日期", value=date(2026, 6, 25))

with c2:
    st.subheader("🌍 外站搜捕 (D1/D4)")
    d1_reg = st.multiselect("過濾區域", list(CI_GLOBAL_HUBS.keys()))
    d1_hubs_sel = st.multiselect("📍 外站站點", [f"{c} ({n})" for r in d1_reg for c, n in CI_GLOBAL_HUBS[r].items()] if d1_reg else ALL_FORMATTED_CITIES)
    d1_range = st.date_input("D1 日期範圍", value=(date(2026, 6, 10),))
    d4_range = st.date_input("D4 日期範圍", value=(date(2026, 6, 26),))

# ==========================================
# 3. 執行邏輯
# ==========================================
async def main_engine():
    d1_s, d1_e = (d1_range[0], d1_range[-1]) if isinstance(d1_range, (list, tuple)) else (d1_range, d1_range)
    d4_s, d4_e = (d4_range[0], d4_range[-1]) if isinstance(d4_range, (list, tuple)) else (d4_range, d4_range)
    d1_list = [d1_s + timedelta(days=i) for i in range((d1_e-d1_s).days + 1)]
    d4_list = [d4_s + timedelta(days=i) for i in range((d4_e-d4_s).days + 1)]
    
    target_str = f"{d2_o_code}➔{d2_d_code} | {d3_o_code}➔{d3_d_code}"
    tasks = []
    sem = asyncio.Semaphore(25)
    
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        # 1. 校準直飛
        ref_val = manual_ref
        if auto_ref:
            with st.spinner("🎯 正在同步核心路徑市場價..."):
                d_legs = [{"fromId": f"{d2_o_code}.AIRPORT", "toId": f"{d2_d_code}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                          {"fromId": f"{d3_o_code}.AIRPORT", "toId": f"{d3_d_code}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")}]
                res = await fetch_flight_async(client, asyncio.Semaphore(1), d_legs, cabin_opt[cabin])
                if res: ref_val = res['total']; st.session_state.ref_price = ref_val

        # 2. 生成外站任務
        for h1_r in d1_hubs_sel:
            for h4_r in d1_hubs_sel:
                if strict_sync and h1_r != h4_r: continue
                h1, h4 = h1_r.split(" ")[0], h4_r.split(" ")[0]
                for d1, d4 in product(d1_list, d4_list):
                    if d1 <= d2_dt and d4 >= d3_dt:
                        l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2_o_code}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                             {"fromId": f"{d2_o_code}.AIRPORT", "toId": f"{d2_d_code}.AIRPORT", "date": d2_dt.strftime("%Y-%m-%d")},
                             {"fromId": f"{d3_o_code}.AIRPORT", "toId": f"{d3_d_code}.AIRPORT", "date": d3_dt.strftime("%Y-%m-%d")},
                             {"fromId": f"{d3_d_code}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                        tasks.append(fetch_flight_async(client, sem, l, cabin_opt[cabin], h1_r, h4_r, d1.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))

        if tasks:
            bar = st.progress(0, text=f"🚀 啟動 {len(tasks)} 組異步獵殺...")
            results = []
            for i, coro in enumerate(asyncio.as_completed(tasks)):
                res = await coro
                if res and (show_all or (ref_val - res['total'] >= 0)):
                    res['ref'] = ref_val
                    results.append(res)
                bar.progress((i + 1) / len(tasks), text=f"⚡ 捕捉中: {i+1}/{len(tasks)}")
            
            st.session_state.valid_offers = results
            if email_on: send_email_report(results, ref_val, target_str)
            st.rerun()
        else: st.error("⚠️ 配置衝突，未生成任何任務。")

if st.button("🚀 啟動完整獵殺", use_container_width=True):
    asyncio.run(main_engine())

# ==========================================
# 📊 戰果展示區
# ==========================================
if st.session_state.valid_offers:
    st.markdown("---")
    res = sorted(st.session_state.valid_offers, key=lambda x: x['total'])
    routes = sorted(list(set(f"{r['h1']} ➔ {r['h4']}" for r in res)))
    tabs = st.tabs(["🏆 綜合最優"] + routes)
    
    with tabs[0]:
        st.markdown(render_matrix_html(res, st.session_state.ref_price, "🌍 全球獲利組合"), unsafe_allow_html=True)
        for r in res[:20]:
            save = st.session_state.ref_price - r['total']
            h1c, h4c = r['h1'].split(' ')[0], r['h4'].split(' ')[0]
            with st.expander(f"💰 {r['total']:,} | {'🔥 省' if save>=0 else '📉 貴'} {abs(save):,} ({h1c}➔{h4c})"):
                st.write(f"日期: {r['d1']} / {r['d4']} | 航班: {' | '.join(r['legs'])}")

    for i, route in enumerate(routes):
        with tabs[i+1]:
            st.markdown(render_matrix_html([r for r in res if f"{r['h1']} ➔ {r['h4']}" == route], st.session_state.ref_price, f"📍 {route}"), unsafe_allow_html=True)
