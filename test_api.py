import requests
import json

API_KEY = "在這裡貼上你的_RapidAPI_金鑰"

# 這次我們改打標準的 Search Flights 端點！
url = "https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlights"

headers = {
    "x-rapidapi-key": API_KEY,
    "x-rapidapi-host": "booking-com15.p.rapidapi.com"
}

# 根據一般 Booking API 的常規參數猜測
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

print("🚀 正在發送【標準 Search Flights】測試請求...")
res = requests.get(url, headers=headers, params=querystring)

if res.status_code == 200:
    data = res.json()
    print("✅ 請求成功！以下為回傳結果：\n")
    print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    print(f"❌ 發生錯誤，HTTP 狀態碼: {res.status_code}")
    print(res.text)
