import requests
import json

# 1. 貼上你的 RapidAPI 金鑰
API_KEY = "在這裡貼上你的_RapidAPI_金鑰"

url = "https://booking-com15.p.rapidapi.com/api/v1/flights/getMinPriceMultiStops"

headers = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "booking-com15.p.rapidapi.com"
}

# 2. 極度簡化的 2 段航程 (測試 API 是否活著)
legs = [
    {"fromId": "TPE.AIRPORT", "toId": "NRT.AIRPORT", "date": "2026-06-11"},
    {"fromId": "NRT.AIRPORT", "toId": "TPE.AIRPORT", "date": "2026-06-15"}
]

querystring = {
    "legs": json.dumps(legs),
    "cabinClass": "ECONOMY",
    "currency_code": "TWD"
}

print("🚀 正在發送純淨測試請求...")
res = requests.get(url, headers=headers, params=querystring)

if res.status_code == 200:
    data = res.json()
    print("✅ 請求成功！以下為回傳結果：\n")
    # 將結果漂亮地印出來
    print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    print(f"❌ 發生錯誤，HTTP 狀態碼: {res.status_code}")
