import streamlit as st
import random
from datetime import datetime, timedelta
from itertools import product

# --- 隱藏不必要的網頁元素,讓它看起來更像手機 App ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- 模擬資料與計算邏輯 (跟我們之前寫的一樣) ---
def fetch_base_flight_data(origin, dest, date):
    base_price = random.randint(3000, 8000) if origin in ["FUK", "KUL", "MNL"] or dest in ["FUK", "KUL", "MNL"] else random.randint(18000, 28000)
    miles = random.randint(500, 1500) if origin in ["FUK", "KUL", "MNL"] or dest in ["FUK", "KUL", "MNL"] else random.randint(2000, 4000)
    return {"base_price": base_price, "miles": miles}

def calculate_family_price(base_price, adults, children, infants):
    child_price = int(base_price * 0.75)
    infant_price = int(base_price * 0.10)
    return (base_price * adults) + (child_price * children) + (infant_price * infants), base_price, child_price, infant_price

# --- App 標題 ---
st.title("✈️ CI 外站四段票神器")

# --- UI 輸入區塊 ---
st.subheader("設定長程主行程")
col1, col2 = st.columns(2)
with col1:
    out_dest = st.text_input("去程目的地 (如 PRG)", value="PRG")
    date_out = st.date_input("去程日期", value=datetime(2026, 6, 10))
with col2:
    in_origin = st.text_input("回程出發地 (如 FRA)", value="ZRH")
    date_in = st.date_input("回程日期", value=datetime(2026, 6, 20))

st.subheader("👨‍👩‍👧‍👦 乘客人數")
col3, col4, col5 = st.columns(3)
with col3:
    adults = st.number_input("大人", min_value=1, value=2)
with col4:
    children = st.number_input("兒童", min_value=0, value=1)
with col5:
    infants = st.number_input("嬰兒", min_value=0, value=1)

# --- 搜尋按鈕與結果呈現 ---
if st.button("一鍵尋找最佳四段票", use_container_width=True):
    with st.spinner('正在為全家精算票價與排列組合...'):
        outstations = ["FUK", "KUL", "BKK"]
        strategies = [{"name": "完美中轉 (不入境)", "seg1_offset": -1, "seg4_offset": 1}]
        results = []

        for start_station, end_station in product(outstations, repeat=2):
            for strategy in strategies:
                seg1_date = date_out + timedelta(days=strategy['seg1_offset'])
                seg4_date = date_in + timedelta(days=strategy['seg4_offset'])
                
                segments = [
                    {"origin": start_station, "dest": "TPE", "date": seg1_date.strftime("%Y-%m-%d")},
                    {"origin": "TPE", "dest": out_dest, "date": date_out.strftime("%Y-%m-%d")},
                    {"origin": in_origin, "dest": "TPE", "date": date_in.strftime("%Y-%m-%d")},
                    {"origin": "TPE", "dest": end_station, "date": seg4_date.strftime("%Y-%m-%d")}
                ]
                
                family_total_price = 0
                detail_list = []

                for i, seg in enumerate(segments, 1):
                    raw = fetch_base_flight_data(seg['origin'], seg['dest'], seg['date'])
                    seg_total, adult_p, child_p, infant_p = calculate_family_price(raw['base_price'], adults, children, infants)
                    family_total_price += seg_total
                    detail_list.append(f"第 {i} 段 | {seg['date']} | {seg['origin']} ✈️ {seg['dest']} | 💰 {seg_total:,} (大{adult_p}/小{child_p}/嬰{infant_p})")
                
                results.append({
                    "title": f"{start_station} 進 / {end_station} 出",
                    "total_price": family_total_price,
                    "details": detail_list
                })
        
        # 排序並顯示前 5 名
        top_5 = sorted(results, key=lambda x: x['total_price'])[:5]
        
        st.success("🎉 計算完成!以下為最划算組合:")
        for i, ticket in enumerate(top_5, 1):
            # 這裡就是你想要的「摺疊卡片」 UI
            with st.expander(f"🏆 Top {i}: {ticket['title']} 👉 總價: NT$ {ticket['total_price']:,}"):
                for detail in ticket['details']:
                    st.write(detail)
