import streamlit as st
import random
from datetime import datetime, timedelta
from itertools import product
import requests
import time

# --- 隱藏網頁元素 ---
st.markdown("<style>#MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}</style>", unsafe_allow_html=True)

# 🌟 快取記憶：查過的機票會記住 1 小時，幫你狂省 API 免費額度！
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_base_flight_data(origin, dest, date, cabin_class):
    time.sleep(1) # 煞車機制
    
    api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
    url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"
    
    cabin_mapping = {"經濟艙": "economy", "豪經艙": "premiumeconomy", "商務艙": "business"}
    
    # 使用新 API 專屬的參數名稱
    params = {
        "fromEntityId": origin, 
        "toEntityId": dest, 
        "departDate": date, 
        "adults": "1", 
        "currency": "TWD", 
        "cabinClass": cabin_mapping[cabin_class]
    }
    
    headers = {
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "flights-sky.p.rapidapi.com"
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=12)
        response.raise_for_status() 
        data = response.json()
        
        # 🎯 根據剛剛診斷工具抓到的精準路徑來提取價格
        real_price = data['data']['itineraries'][0]['price']['raw']
        
        miles = 4500 if "PRG" in [origin, dest] or "FRA" in [origin, dest] or "ZRH" in [origin, dest] else 1000
        return {"base_price": int(real_price), "miles": miles, "status": "✅ API 即時報價"}
        
    except Exception as e:
        err_msg = str(e)
        if "429" in err_msg:
            reason = "本月免費額度用盡"
        elif "IndexError" in str(type(e)) or "TypeError" in str(type(e)):
            reason = "該日無航班或售罄"
        else:
            reason = "連線異常"

        # 備案模擬價格
        multiplier = 1 if cabin_class == "經濟艙" else (1.8 if cabin_class == "豪經艙" else 3.5)
        long_haul_price = random.randint(18000, 2
