import streamlit as st
import requests

st.title("🛠️ 多點搜尋 (Multi-City) X光診斷工具")
st.write("用來透視伺服器到底為什麼拒絕我們的 4 段票請求。")

api_key = "dce25cdb5amshe2e8ea332763a58p1ca56ajsna52ab815ea5a"
url = "https://flights-sky.p.rapidapi.com/flights/search-multi-city"

if st.button("🚀 發射 4 段票測試封包", use_container_width=True):
    with st.spinner("等待伺服器回應中..."):
        # 測試封包：先用最簡單的 1 個大人、不限轉機，看它吃不吃
        payload = {
            "market": "TW",
            "locale": "zh-TW",
            "currency": "TWD",
            "adults": 1,
            "children": 0,
            "infants": 0,
            "cabinClass": "business",
            "sort": "cheapest_first",
            "flights": [
                {"fromEntityId": "FUK", "toEntityId": "TPE", "departDate": "2026-04-27"},
                {"fromEntityId": "TPE", "toEntityId": "PRG", "departDate": "2026-06-11"},
                {"fromEntityId": "FRA", "toEntityId": "TPE", "departDate": "2026-06-25"},
                {"fromEntityId": "TPE", "toEntityId": "FUK", "departDate": "2026-08-09"}
            ]
        }
        
        headers = {
            "x-rapidapi-key": api_key,
            "x-rapidapi-host": "flights-sky.p.rapidapi.com",
            "Content-Type": "application/json"
        }

        try:
            res = requests.post(url, json=payload, headers=headers)
            
            if res.status_code == 200:
                st.success("✅ 連線大成功！伺服器沒有報錯，回傳了以下資料：")
                st.json(res.json())
            else:
                st.error(f"❌ 被伺服器退件了！錯誤碼：{res.status_code}")
                st.write("🚨 伺服器給的退件原因 (請截圖這個給我看)：")
                st.code(res.text)
                
        except Exception as e:
            st.error(f"連線直接斷線：{e}")
