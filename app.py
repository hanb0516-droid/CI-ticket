import streamlit as st
import requests

st.title("🛠️ API 連線診斷工具 (終極測試)")
st.write("這個工具只發送 1 次請求，用來測試正確的網址與參數。")

api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
# 👇 換成剛剛截圖中找到的正確網址！
url = "https://flights-sky.p.rapidapi.com/flights/search-one-way"

if st.button("🚀 測試單筆連線 (TPE ✈️ PRG)", use_container_width=True):
    with st.spinner("發送 1 筆請求測試中..."):
        # 這是最通用的參數寫法，測試看看這家 API 吃不吃這套
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
            res = requests.get(url, headers=headers, params=params)
            
            if res.status_code == 200:
                st.success("✅ 連線大成功！伺服器有正常回應資料：")
                st.json(res.json())
            else:
                st.error(f"❌ 發生錯誤！錯誤碼：{res.status_code}")
                st.write("伺服器給的詳細原因 (可能是參數名稱不同)：")
                st.code(res.text)
                
        except Exception as e:
            st.error(f"發生未知的系統錯誤：{e}")
