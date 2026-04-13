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
        st.session_state.engine_running = False
        st.rerun()
else:
    c_toggles = st.columns(3)
    with c_toggles[0]: strict_ci_toggle = st.checkbox("🔒 嚴格鎖定純華航 (CI)", value=True)
    with c_toggles[1]: hide_loss_toggle = st.checkbox("🙈 隱藏虧損票 (賠錢不存)", value=True)
    
    st.subheader("📌 核心行程 (D2 / D3)")
    trip_type = st.radio("行程模式", ["🔄 單純來回 (Round-trip)", "🔀 多點進出 (Multi-city)"], horizontal=True, label_visibility="collapsed")
    
    c_d2, c_d3 = st.columns(2)
    if "來回" in trip_type:
        with c_d2:
            base_org = st.text_input("🛫 D2起點 / D3終點 (通常為 TPE)", value="TPE").upper()
            d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
        with c_d3:
            base_dst = st.text_input("🛬 D2終點 / D3起點 (如 PRG, FRA)", value="PRG").upper()
            d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))
        d2_org, d3_dst = base_org, base_org
        d2_dst, d3_org = base_dst, base_dst
    else:
        with c_d2:
            d2_org = st.text_input("D2 出發", value="TPE").upper()
            d2_dst = st.text_input("D2 抵達", value="PRG").upper()
            d2_date = st.date_input("D2 去程日期", value=date(2026, 6, 11))
        with c_d3:
            d3_org = st.text_input("D3 出發", value="FRA").upper()
            d3_dst = st.text_input("D3 抵達", value="TPE").upper()
            d3_date = st.date_input("D3 回程日期", value=date(2026, 6, 25))

    st.markdown("#### 🎯 基準預算設定")
    c_ref1, c_ref2 = st.columns(2)
    with c_ref1: fallback_d2d3 = st.number_input("保底 D2/D3 直飛預算", value=175000, step=1000)
    with c_ref2: fallback_d1d4 = st.number_input("保底 D1/D4 外站預算", value=25000, step=1000)

    st.subheader("🌍 外站雷達 (D1 / D4) - 支援華航全球站點")
    c_d1, c_d4 = st.columns(2)
    with c_d1:
        st.multiselect("🗂️ 區域 (D1)", ["全部"] + list(CI_GLOBAL_HUBS.keys()), default=["港澳大陸"], key="d1_reg", on_change=sync_d1)
        d1_hubs_raw = st.multiselect("📍 D1 起點庫", ALL_FORMATTED_CITIES, key="d1_city")
        d1_date_range = st.date_input("📅 D1 日期 (單日或區間)", value=(date(2026, 6, 10),)) # 預設 tuple 啟用區間功能
    with c_d4:
        st.multiselect("🗂️ 區域 (D4)", ["全部"] + list(CI_GLOBAL_HUBS.keys()), default=["港澳大陸"], key="d4_reg", on_change=sync_d4)
        d4_hubs_raw = st.multiselect("📍 D4 終點庫", ALL_FORMATTED_CITIES, key="d4_city")
        d4_date_range = st.date_input("📅 D4 日期 (單日或區間)", value=(date(2026, 6, 26),))

    cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])

    if st.button("🚀 啟動【全球無死角】外站聯程獵殺", use_container_width=True):
        d1_s, d1_e = parse_date_range(d1_date_range)
        d4_s, d4_e = parse_date_range(d4_date_range)
        if not d1_s or not d4_s: st.error("日期格式錯誤"); st.stop()
        
        d1_dates = [d1_s + timedelta(days=i) for i in range((d1_e - d1_s).days + 1)]
        d4_dates = [d4_s + timedelta(days=i) for i in range((d4_e - d4_s).days + 1)]
        d1_codes, d4_codes = [h.split(" ")[0] for h in d1_hubs_raw], [h.split(" ")[0] for h in d4_hubs_raw]
        
        tasks = []
        for h1_raw, h4_raw in product(d1_hubs_raw, d4_hubs_raw):
            h1_c, h4_c = h1_raw.split(" ")[0], h4_raw.split(" ")[0]
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 <= d2_date and d4 >= d3_date: 
                    legs = [{"fromId": f"{h1_c}.AIRPORT", "toId": f"{d2_org}.AIRPORT", "date": d1.strftime("%Y-%m-%d")}, {"fromId": f"{d2_org}.AIRPORT", "toId": f"{d2_dst}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_org}.AIRPORT", "toId": f"{d3_dst}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")}, {"fromId": f"{d3_dst}.AIRPORT", "toId": f"{h4_c}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                    tasks.append((legs, cabin_choice, strict_ci_toggle, f"{h1_raw} ➔ {h4_raw}", d1, d4, h1_c, h4_c))

        if not tasks: st.warning("組合無效：請確認 D1 日期在 D2 之前，且 D4 日期在 D3 之後。"); st.stop()
        
        st.session_state.task_list = tasks
        st.session_state.task_idx = 0
        st.session_state.valid_offers = []
        st.session_state.quota_dead = False
        st.session_state.hide_loss = hide_loss_toggle
        st.session_state.core_price = fallback_d2d3
        st.session_state.base_cache = {f"{h1}_{h4}": fallback_d1d4 for h1, h4 in product(d1_codes, d4_codes)}
        st.session_state.engine_running = True
        
        if os.path.exists(BLACKBOX_FILE): os.remove(BLACKBOX_FILE)
        st.rerun()

# ==========================================
# 3. 接力執行核心 (State Machine Loop)
# ==========================================
if st.session_state.engine_running:
    total = len(st.session_state.task_list)
    curr = st.session_state.task_idx
    BATCH = 15 
    
    batch_tasks = st.session_state.task_list[curr : curr + BATCH]
    st.progress(min(curr / total, 1.0), text=f"核彈掃描進度: {curr}/{total} | 已收穫: {len(st.session_state.valid_offers)}")
    
    live = st.empty()
    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = {exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], t[4], t[5]): t for t in batch_tasks}
        for f in as_completed(futures):
            t_meta = futures[f]
            try:
                res = f.result()
                if res["status"] == "quota_exceeded": 
                    st.session_state.quota_dead = True; break
                elif res["status"] == "success" and res.get("offer"):
                    o = res["offer"]
                    o["ref"] = st.session_state.core_price + st.session_state.base_cache[f"{t_meta[6]}_{t_meta[7]}"]
                    diff = o["ref"] - o['total']
                    if st.session_state.hide_loss and diff <= 0: continue 
                    
                    st.session_state.valid_offers.append(o)
                    with open(BLACKBOX_FILE, "a", encoding="utf-8") as file:
                        file.write(json.dumps(o, ensure_ascii=False) + "\n")
                    if diff > 10000:
                        with live.container():
                            st.markdown(f"<div class='live-hit'>🔔 <b>捕獲神票：</b> {o['title']} | <span style='color:#00e676'>省 {diff:,}</span></div>", unsafe_allow_html=True)
            except: pass

    if st.session_state.quota_dead or (curr + BATCH >= total):
        st.session_state.engine_running = False
        st.rerun()
    else:
        st.session_state.task_idx += BATCH
        time.sleep(0.5) 
        st.rerun() 

# ==========================================
# 4. 戰果展示區與 CSV 下載
# ==========================================
if not st.session_state.engine_running and st.session_state.task_list:
    st.markdown("---")
    res = st.session_state.valid_offers
    if res:
        res.sort(key=lambda x: x['total'])
        st.success(f"🎉 獵殺完畢！成功抓取 {len(res)} 組精選機票：")
        
        # --- 產生 CSV 下載按鈕 ---
        df_export = pd.DataFrame([{
            "航線": r['title'],
            "聯程總價 (TWD)": r['total'],
            "省下金額 (TWD)": r['ref'] - r['total'],
            "D1 外站出發日": r['d1'],
            "D4 外站回程日": r['d4'],
            "詳細航班 (四段)": " | ".join(r['legs'])
        } for r in res])
        
        csv_data = df_export.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="📥 一鍵匯出本次戰果 (Excel CSV格式)",
            data=csv_data,
            file_name=f"Flight_Hunter_Result_{date.today()}.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True
        )
        st.markdown("---")

        for r in res[:100]:
            diff = r["ref"] - r['total']
            b_p = f"🔥 狂省 {diff:,}" if diff > 50000 else f"✨ 省下 {diff:,}" if diff > 0 else f"⚠️ 虧損 {abs(diff):,}"
            b_h = f"<span style='color:#00e676; font-weight:bold;'>🔥 狂省 {diff:,}</span>" if diff > 50000 else f"<span style='color:#b2ff59;'>✨ 省下 {diff:,}</span>" if diff > 0 else f"<span style='color:#ff5252;'>⚠️ 虧損 {abs(diff):,}</span>"
            with st.expander(f"💰 {r['total']:,} TWD | {b_p} | {r['title']} (D1:{r['d1']} / D4:{r['d4']})"):
                st.markdown(f"**💰 價差精算：** 基準底價 `{r['ref']:,}` ➔ 隱藏聯程價 `{r['total']:,}` ( {b_h} )", unsafe_allow_html=True)
                st.markdown("---")
                for j, leg in enumerate(r['legs'], 1): st.write(f"**航段 {j}** | {leg}")
    else: 
        if st.session_state.hide_loss:
            st.warning("📉 本次掃描結果皆為虧損票，已啟動潔癖模式全部濾除。建議更換日期或區域再戰！")
        else:
            st.error("❌ 本次掃描未尋獲符合條件之特價聯程票。")
