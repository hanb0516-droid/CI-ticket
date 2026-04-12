import streamlit as st
import requests

st.title("🛠️ API 連線診斷工具 (參數校正版)")
st.write("配合新伺服器的口味，調整了參數的名稱。")

api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"

if st.button("🚀 測試單筆連線 (TPE ✈️ PRG)", use_container_width=True):
    with st.spinner("發送 1 筆請求測試中..."):
        # 👇 這裡換成了這家 API 規定的專屬參數名稱
        params = {
            "fromEntityId": "TPE",     # 出發地
            "toEntityId": "PRG",       # 目的地
            "departDate": "2026-06-11",# 出發日期 (通常這家是用 departDate)
            "adults": "1", 
            "currency": "TWD", 
            "cabinClass": "economy"
        }
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": "flights-sky.p.rapidapi.com"
        }
        
        try:
            res = requests.get(url, headers=headers, params=params)
            
            if res.status_code == 200:
                st.success("✅ 連線大成功！伺服器有正常回應資料：")
                st.json(res.json())
            else:
                st.error(f"❌ 發生錯誤！錯誤碼：{res.status_code}")
                st.code(res.text)
                
        except Exception as e:
            st.error(f"發生未知的系統錯誤：{e}")
