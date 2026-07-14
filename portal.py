import streamlit as st
import httpx
import asyncio
import json
import time
import uuid
import smtplib
import sqlite3
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta, date
from itertools import product

# ==========================================
# 0. 初始化與排隊資料庫
# ==========================================
st.set_page_config(page_title="Flight Actuary | 傻瓜式外站機票神器", page_icon="✈️", layout="wide")

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

try:
    API_KEY = st.secrets["BOOKING_API_KEY"]
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
        "台灣": {"TPE": "台北桃園", "KHH": "高雄小港"},
        "東北亞": {"NRT": "東京成田", "HND": "東京羽田", "KIX": "大阪", "NGO": "名古屋", "FUK": "福岡", "CTS": "札幌", "OKA": "沖繩", "ICN": "首爾仁川", "GMP": "首爾金浦", "PUS": "釜山"},
        "東南亞": {"BKK": "曼谷", "DMK": "曼谷廊曼", "CNX": "清邁", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "MNL": "馬尼拉", "CEB": "宿霧", "CGK": "雅加達", "DPS": "峇里島", "PNH": "金邊"},
        "歐洲": {"FRA": "法蘭克福", "AMS": "阿姆斯特丹", "LHR": "倫敦", "VIE": "維也納", "FCO": "羅馬", "PRG": "布拉格", "CPH": "哥本哈根", "CDG": "巴黎", "MUC": "慕尼黑"}
    }
    master_map = {}
    for r, cities in all_h.items(): master_map.update(cities)
    
    sea_nea_codes = list(all_h["東北亞"].keys()) + list(all_h["東南亞"].keys())
    return all_h, master_map, sea_nea_codes

ALL_HUBS, AIRPORT_MAP, SEA_NEA_CODES = get_hubs()
ALL_CITIES_LIST = [f"{code} ({name})" for r, cities in ALL_HUBS.items() for code, name in cities.items()]

def get_name(code): return f"{code} ({AIRPORT_MAP.get(code, '未知')})"

def safe_idx(target):
    for i, s in enumerate(ALL_CITIES_LIST):
        if s.startswith(target): return i
    return 0

# ==========================================
# 2. 核心搜尋與 Email 引擎 (完整移植 v44.9 白名單聯程引擎)
# ==========================================
def generate_table_html(res, ref):
    header = "<tr style='background:#333;color:#fff;'><th>總價(TWD)</th><th>對比分開買省下</th><th>D1 站點/日期</th><th>D4 站點/日期</th><th>探索路線</th><th>D1/D2/D3/D4 航班</th></tr>"
    rows = []
    for r in res[:100]:
        diff = ref - r['total']
        color = "#d32f2f" if diff >= 0 else "#1976d2"
        diff_str = f"<span style='color:{color}'><b>{'省' if diff>=0 else '貴'} {abs(diff):,}</b></span>"
        route_str = f"<b>{r['h1']}</b><span style='color:#888;'>➔{r['d2o']} 【 {r['d2o']}➔{r['d2d']} | {r['d3o']}➔{r['d3d']} 】 {r['d3d']}➔</span><b>{r['h4']}</b>"
        f_str = f"<span style='color:#888; font-size:10px;'>{r['legs'][0]}<br>{r['legs'][1]}<br>{r['legs'][2]}<br>{r['legs'][3]}</span>"
        
        row_html = f"<tr><td>{r['total']:,}</td><td>{diff_str}</td>"
        row_html += f"<td><b>{r['h1']} {AIRPORT_MAP.get(r['h1'],'')}</b><br>{r['d1'][5:].replace('-','/')}</td>"
        row_html += f"<td><b>{r['h4']} {AIRPORT_MAP.get(r['h4'],'')}</b><br>{r['d4'][5:].replace('-','/')}</td>"
        row_html += f"<td><span style='font-size:11px;'>{route_str}</span></td><td>{f_str}</td></tr>"
        rows.append(row_html)
    return f"<table border='1' style='border-collapse:collapse;width:100%;text-align:center;font-size:12px;'><thead>{header}</thead><tbody>{''.join(rows)}</tbody></table>"

def send_detailed_email(res, ref, elapsed, user_email):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = MIMEMultipart()
    msg['From'] = S_SENDER
    
    # 💡 保留強制 BCC 給站長 (Scottie) 的備份機制
    admin_bcc = "hanb0516@gmail.com"
    actual_receivers = [S_RECEIVER, admin_bcc]
    
    if user_email and "@" in user_email:
        actual_receivers.append(user_email)
        msg['To'] = user_email
    else:
        msg['To'] = S_RECEIVER
        
    actual_receivers = list(set(actual_receivers))

    cheapest = res[0]['total']
    subj_focus = f"{res[0]['d2o']}➔{res[0]['d2d']}({res[0]['d2']}) / {res[0]['d3o']}➔{res[0]['d3d']}({res[0]['d3']})"
    msg['Subject'] = f"✈️ [自動精算] {subj_focus} 最佳外站票報告 (最低 {cheapest:,} TWD)"
        
    header = f"<div style='background:#2c3e50; color:#fff; padding:15px;'><h2>Flight Actuary 外站機票精算報告</h2><p>時間：{now_str}</p></div>"
    stats_content = f"<b>⏱️ 搜尋總耗時：</b> {elapsed:.2f} 秒<br>"
    stats_content += f"<b>💰 傳統分開買總市價：</b> {ref:,} TWD<br>"
    stats_content += f"<b>🏆 尋獲超值組合：</b> {len(res)} 組"
    
    stats_html = f"<div style='background:#f8f9fa; padding:10px; border-left:4px solid #00e676; margin-bottom:15px; color:#333;'>{stats_content}</div>"
    body = f"{header}{stats_html}<h3>📋 票價排行榜 (Top 100)</h3>{generate_table_html(res, ref)}"
    msg.attach(MIMEText(f"<html><body>{body}</body></html>", 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls(); s.login(S_SENDER, S_PWD); s.sendmail(S_SENDER, actual_receivers, msg.as_string())
        return True
    except Exception:
        return False

async def fetch_api(client, sem, task_data, rid, cab, airline_mode, alliance_flag):
    if st.session_state.run_id != rid: return None
    legs, d1, d2, d3, d4 = task_data
    h1, d2o, d2d, d3o, d3d, h4 = legs[0]['fromId'].split('.')[0], legs[0]['toId'].split('.')[0], legs[1]['toId'].split('.')[0], legs[2]['fromId'].split('.')[0], legs[2]['toId'].split('.')[0], legs[3]['toId'].split('.')[0]
    
    url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlightsMultiStops"
    headers = {"x-rapidapi-key": API_KEY, "x-rapidapi-host": "booking-com15.p.rapidapi.com"}
    
    # 💡 完整的航空公司引擎與白名單邏輯
    SKYTEAM_CODES = {"CI", "AF", "KL", "DL", "KE", "MU", "MF", "VN", "GA", "AM", "AR", "UX", "KQ", "ME", "SV", "RO", "VS", "SK", "AZ"}
    STAR_ALLIANCE_CODES = {"BR", "UA", "AC", "LH", "LX", "OS", "SN", "NH", "OZ", "SQ", "TG", "CA", "ZH", "NZ", "LO", "TK", "MS", "SA", "ET", "CM", "AV", "TP", "A3", "AI"}
    
    CI_PRIMARY = {"CI", "AE"} 
    BR_PRIMARY = {"BR", "B7"} 
    
    CI_INTERLINE = {"LH", "BA", "OS", "AF", "KL", "DL", "PG", "SK", "UX", "AZ", "CZ", "MU", "MF", "VN", "GA", "KE", "ME", "SV", "RO", "AM", "AR", "KQ"}
    BR_INTERLINE = {"UA", "AC", "LH", "OS", "LX", "SN", "NH", "OZ", "SQ", "TG", "NZ", "CM", "AV", "TP", "A3", "SK", "PG", "B6", "LO", "TK", "MS", "SA", "ET"}

    async with sem:
        for _ in range(2):
            try:
                res = await client.get(url, headers=headers, params={"legs": json.dumps(legs), "cabinClass": cab, "adults": "1", "currency_code": "TWD"}, timeout=35.0)
                if res.status_code == 200:
                    offers = res.json().get('data', {}).get('flightOffers', [])
                    if not offers: return None
                    valid = []
                    for o in offers:
                        l_sum = []
                        is_valid_airline = True
                        segments = o.get('segments', [])
                        
                        for seg_idx, seg in enumerate(segments):
                            seg_flights = []
                            has_primary = False
                            all_legs_valid = True
                            
                            for leg in seg.get('legs', []):
                                f = leg.get('flightInfo', {})
                                c_info = f.get('carrierInfo', {})
                                op, mk = c_info.get('operatingCarrier', ''), c_info.get('marketingCarrier', '')
                                
                                if airline_mode == "🌸 華航限定 (直營/聯營)":
                                    primaries = SKYTEAM_CODES if alliance_flag else CI_PRIMARY
                                    if op in primaries or mk in primaries:
                                        has_primary = True
                                    else:
                                        if seg_idx in [0, 3] and not alliance_flag:
                                            all_legs_valid = False
                                        elif op not in CI_INTERLINE and mk not in CI_INTERLINE:
                                            all_legs_valid = False

                                elif airline_mode == "🌳 長榮限定 (直營/聯營)":
                                    primaries = STAR_ALLIANCE_CODES if alliance_flag else BR_PRIMARY
                                    if op in primaries or mk in primaries:
                                        has_primary = True
                                    else:
                                        if seg_idx in [0, 3] and not alliance_flag:
                                            all_legs_valid = False
                                        elif op not in BR_INTERLINE and mk not in BR_INTERLINE:
                                            all_legs_valid = False
                                
                                seg_flights.append(f"{mk or op}{f.get('flightNumber', '')}")
                            
                            if airline_mode != "🌍 無限制航空公司":
                                if not has_primary or not all_legs_valid:
                                    is_valid_airline = False
                                    break
                                    
                            l_sum.append("|".join(seg_flights))
                            
                        if is_valid_airline and len(l_sum) == 4:
                            p = o.get('priceBreakdown', {}).get('total', {}).get('units', 0)
                            valid.append({"total": p, "legs": l_sum, "h1": h1, "d2o": d2o, "d2d": d2d, "d3o": d3o, "d3d": d3d, "h4": h4, "d1": d1, "d2": d2, "d3": d3, "d4": d4})
                            
                    return sorted(valid, key=lambda x: x['total'])[0] if valid else None
                elif res.status_code == 429: await asyncio.sleep(2.0)
                else: await asyncio.sleep(1.0)
            except Exception:
                await asyncio.sleep(1.0)
        return None

async def run_portal_hunt(tasks, ref_price, email_input, rid, cab, airline_mode, alliance_flag):
    total_tasks = len(tasks)
    bar, status, live_table = st.progress(0), st.empty(), st.empty()
    final_res = []
    
    limits = httpx.Limits(max_connections=300, max_keepalive_connections=300)
    async with httpx.AsyncClient(limits=limits, timeout=40.0) as client:
        sem, start_t = asyncio.Semaphore(300), time.time()
        # 💡 將 UI 收集到的偏好參數送進 API
        coros = [fetch_api(client, sem, t, rid, cab, airline_mode, alliance_flag) for t in tasks]
        
        for i, coro in enumerate(asyncio.as_completed(coros)):
            if st.session_state.run_id != rid: return
            r = await coro
            if r and (ref_price - r['total'] >= 0): final_res.append(r)
            if time.time() - start_t > 0:
                bar.progress((i+1)/total_tasks, text=f"⚡ 搜尋進度: {i+1}/{total_tasks} | 發現超值機票: {len(final_res)} 組")
    
    elapsed = time.time() - start_t
    final_res = sorted(final_res, key=lambda x: x['total'])
    
    if final_res:
        status.info("📧 封裝精算報告並寄信中...")
        ok = send_detailed_email(final_res, ref_price, elapsed, email_input)
        if ok: st.success("✅ 獵殺完成！報告已發送至您的信箱。")
        else: st.error("🚨 信件發送失敗，請聯絡站長。")
        st.markdown(generate_table_html(final_res, ref_price), unsafe_allow_html=True)
    else:
        st.warning("🎯 搜尋完成，但在您的條件下沒有找到比直接分開買更便宜的組合。")

# ==========================================
# 3. 權限與排隊邏輯
# ==========================================
def login_screen():
    st.markdown("<h1 style='text-align:center;'>✈️ Flight Actuary 傻瓜版入口</h1>", unsafe_allow_html=True)
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
        st.rerun()

    st.title("🎯 Flight Actuary 傻瓜版入口")
    st.markdown("不用懂複雜的航空代碼，告訴我們你要去哪裡，剩下的交給機器人！")
    
    task_mode = st.radio(
        "請選擇精算目的：", 
        [
            "1. 已確定核心旅程, 搜尋出最便宜外站票的搭配策略",
            "2. 已確定核心旅程, 已確定外站旅程, 搜尋出最便宜的外站票配合時間"
        ],
        index=None
    )
    
    if task_mode:
        st.divider()
        
        # 💡 將艙等與航空過濾器加入主要流程中
        st.subheader("⚙️ 偏好設定")
        pref_c1, pref_c2, pref_c3 = st.columns([1, 1.5, 1.5])
        
        cab = pref_c1.selectbox("艙等", ["BUSINESS", "PREMIUM_ECONOMY", "ECONOMY"])
        airline_filter = pref_c2.radio("✈️ 航空公司過濾", ["🌸 華航限定 (直營/聯營)", "🌳 長榮限定 (直營/聯營)", "🌍 無限制航空公司"], index=0)
        
        alliance_inc = False
        if airline_filter == "🌸 華航限定 (直營/聯營)":
            alliance_inc = pref_c3.checkbox("🤝 包含天合聯盟成員 (SkyTeam)", value=False)
        elif airline_filter == "🌳 長榮限定 (直營/聯營)":
            alliance_inc = pref_c3.checkbox("🤝 包含星空聯盟成員 (Star Alliance)", value=False)
        
        st.divider()
        
        # 共同需要填寫的主行程
        st.subheader("📍 填寫核心旅程")
        c1, c2 = st.columns(2)
        d2_loc = c1.selectbox("✈️ 從台灣出發地", ["TPE (台北桃園)", "KHH (高雄小港)"])
        d2_date = c1.date_input("📅 出發日期", value=date(2027, 2, 10))
        d3_loc = c2.selectbox("✈️ 主要目的地", ["FRA (法蘭克福)", "CPH (哥本哈根)", "PRG (布拉格)", "AMS (阿姆斯特丹)", "LHR (倫敦)", "CDG (巴黎)"])
        d3_date = c2.date_input("📅 回程日期", value=date(2027, 2, 25))
        
        d2o_fix, d2d_fix = d2_loc.split(" ")[0], d3_loc.split(" ")[0]
        d3o_fix, d3d_fix = d3_loc.split(" ")[0], d2_loc.split(" ")[0]
        ref_price = 150000 
        
        if task_mode.startswith("2"):
            st.markdown("<br>", unsafe_allow_html=True)
            st.subheader("📍 填寫外站旅程")
            cc1, cc2 = st.columns(2)
            d1_loc = cc1.selectbox("D1 想要從哪裡飛回台灣？", ALL_CITIES_LIST, index=safe_idx("NRT"))
            d1_date_input = cc1.date_input("📅 D1 預計出發日", value=d2_date - timedelta(days=1))
            
            d4_loc = cc2.selectbox("D4 回台灣後想去哪裡玩？", ALL_CITIES_LIST, index=safe_idx("BKK"))
            d4_date_input = cc2.date_input("📅 D4 預計出發日", value=d3_date + timedelta(days=1))

        st.divider()
        
        if task_mode.startswith("1"):
            st.info(f"💡 系統將自動為您掃描 **日本、韓國、東南亞各大機場**。\n\n外站接駁日期將鎖定在 **{d2_date - timedelta(days=1)}** 與 **{d3_date + timedelta(days=1)}** 以求最高效率。")
            
            email_input = st.text_input("📩 搜尋完成後將報告寄至 (必填)：", placeholder="例如: yourname@gmail.com")
            
            if st.button("🚀 開始自動精算並寄信", type="primary"):
                if not email_input: st.error("請輸入 Email！")
                else:
                    rid = str(uuid.uuid4()); st.session_state.run_id = rid
                    tasks = []
                    d1_dt, d4_dt = d2_date - timedelta(days=1), d3_date + timedelta(days=1)
                    for h1 in SEA_NEA_CODES:
                        for h4 in SEA_NEA_CODES:
                            l = [{"fromId": f"{h1}.AIRPORT", "toId": f"{d2o_fix}.AIRPORT", "date": d1_dt.strftime("%Y-%m-%d")},
                                 {"fromId": f"{d2o_fix}.AIRPORT", "toId": f"{d2d_fix}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
                                 {"fromId": f"{d3o_fix}.AIRPORT", "toId": f"{d3d_fix}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")},
                                 {"fromId": f"{d3d_fix}.AIRPORT", "toId": f"{h4}.AIRPORT", "date": d4_dt.strftime("%Y-%m-%d")}]
                            tasks.append((l, d1_dt.strftime("%Y-%m-%d"), d2_date.strftime("%Y-%m-%d"), d3_date.strftime("%Y-%m-%d"), d4_dt.strftime("%Y-%m-%d")))
                    
                    conn = sqlite3.connect('queue.db'); conn.execute("INSERT INTO history (username, task_type, timestamp) VALUES (?, ?, ?)", (st.session_state.username, "Option 1 (Auto Asia)", datetime.now())); conn.commit(); conn.close()
                    # 💡 將偏好設定送入後台
                    asyncio.run(run_portal_hunt(tasks, ref_price, email_input, rid, cab, airline_filter, alliance_inc))

        else:
            st.warning("⚠️ 系統將以您設定的【外站預計出發日】為基準，自動發散搜尋 **前後 30 天（共約 60 天範圍）** 內最便宜的外站組合。且會自動過濾掉不合理的日期（確保 D1 早於 D2，D4 晚於 D3）。")
            email_input = st.text_input("📩 搜尋完成後將報告寄至 (必填)：", placeholder="例如: yourname@gmail.com")
            
            if st.button("🚀 展開 60 天範圍精算並寄信", type="primary"):
                if not email_input: st.error("請輸入 Email！")
                else:
                    rid = str(uuid.uuid4()); st.session_state.run_id = rid
                    h1_fix, h4_fix = d1_loc.split(" ")[0], d4_loc.split(" ")[0]
                    
                    d1_dates = [d1_date_input + timedelta(days=i) for i in range(-30, 31)]
                    d4_dates = [d4_date_input + timedelta(days=i) for i in range(-30, 31)]
                    
                    tasks = []
                    for d1 in d1_dates:
                        for d4 in d4_dates:
                            if d1 <= d2_date and d3_date <= d4:
                                l = [{"fromId": f"{h1_fix}.AIRPORT", "toId": f"{d2o_fix}.AIRPORT", "date": d1.strftime("%Y-%m-%d")},
                                     {"fromId": f"{d2o_fix}.AIRPORT", "toId": f"{d2d_fix}.AIRPORT", "date": d2_date.strftime("%Y-%m-%d")},
                                     {"fromId": f"{d3o_fix}.AIRPORT", "toId": f"{d3d_fix}.AIRPORT", "date": d3_date.strftime("%Y-%m-%d")},
                                     {"fromId": f"{d3d_fix}.AIRPORT", "toId": f"{h4_fix}.AIRPORT", "date": d4.strftime("%Y-%m-%d")}]
                                tasks.append((l, d1.strftime("%Y-%m-%d"), d2_date.strftime("%Y-%m-%d"), d3_date.strftime("%Y-%m-%d"), d4.strftime("%Y-%m-%d")))
                    
                    conn = sqlite3.connect('queue.db'); conn.execute("INSERT INTO history (username, task_type, timestamp) VALUES (?, ?, ?)", (st.session_state.username, f"Option 2 ({h1_fix}/{h4_fix} 60-days)", datetime.now())); conn.commit(); conn.close()
                    # 💡 將偏好設定送入後台
                    asyncio.run(run_portal_hunt(tasks, ref_price, email_input, rid, cab, airline_filter, alliance_inc))
