import streamlit as st
import requests
import json

st.set_page_config(page_title="API 診斷雷達", layout="wide")
st.title("📡 Booking.com API 診斷雷達")
st.markdown("這是一個純淨的測試環境，用來驗證 `searchFlights` 端點是否正常運作。")

# 1. 讀取與清洗金鑰
try:
    raw_key = st.secrets["BOOKING_API_KEY"]
    API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
    st.success("✅ 成功讀取 API 金鑰！")
except KeyError:
    st.error("🚨 找不到 BOOKING_API_KEY，請檢查 Streamlit Cloud 的 Secrets 設定。")
    st.stop()

st.markdown("---")
st.subheader("測試任務：台北 (TPE) ➔ 東京 (NRT) 經濟艙來回")

if st.button("🚀 發射測試請求 (Search Flights)", type="primary"):
    with st.spinner("正在呼叫 RapidAPI... 請稍候..."):
        # 這次我們打標準的 Search Flights 端點
        url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlights"

        headers = {
            "x-rapidapi-key": API_KEY,
            "x-rapidapi-host": "booking-com15.p.rapidapi.com"
        }

        # 標準來回票的參數
        querystring = {
            "fromId": "TPE.AIRPORT",
            "toId": "NRT.AIRPORT",
            "departDate": "2026-06-11",
            "returnDate": "2026-06-15",
            "pageNo": "1",
            "adults": "1",
            "cabinClass": "ECONOMY",
            "currency_code": "TWD"
        }

        try:
            res = requests.get(url, headers=headers, params=querystring)
            
            if res.status_code == 200:
                data = res.json()
                # 檢查 data 裡面是不是又是空的
                if data.get("data") and len(data.get("data", [])) > 0:
                    st.success("🎉 萬歲！API 活著，而且成功抓到航班資料了！")
                    st.balloons()
                else:
                    st.warning("⚠️ API 請求成功，但回傳的 data 陣列依然是空的 (查無航班)。")
                
                st.markdown("### 📦 原始 JSON 回傳結果")
                st.json(data)
                
            else:
                st.error(f"❌ 發生錯誤！HTTP 狀態碼: {res.status_code}")
                st.write("錯誤詳情：", res.text)
                
        except Exception as e:
            st.error(f"連線發生嚴重錯誤: {e}")
