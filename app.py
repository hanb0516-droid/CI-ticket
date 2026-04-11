import streamlit as st
import requests

st.title("🛠️ API 連線診斷工具")
st.write("這個工具只發送 1 次請求，用來測試你的 API 鑰匙與參數是否正確。")

api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
url = "https://flights-sky.p.rapidapi.com/api/v1/flights/searchFlights"

if st.button("🚀 測試單筆連線 (TPE ✈️ PRG)", use_container_width=True):
    with st.spinner("發送 1 筆請求測試中..."):
        params = {
            "origin": "TPE", 
            "destination": "PRG", 
            "date": "2026-06-11", 
            "adults": "1", 
            "currency": "TWD", 
            "cabinClass": "economy"
        }
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": "flights-sky.p.rapidapi.com"
        }
        
        try:
            # 發送請求
            res = requests.get(url, headers=headers, params=params)
            
            # 如果成功 (狀態碼 200)
            if res.status_code == 200:
                st.success("✅ 連線成功！伺服器有正常回應資料：")
                # 印出最原始的資料結構
                st.json(res.json())
            else:
                st.error(f"❌ 被擋下來了！錯誤碼：{res.status_code}")
                st.write("伺服器給的詳細拒絕原因：")
                st.code(res.text)
                
        except Exception as e:
            st.error(f"發生未知的系統錯誤：{e}")
