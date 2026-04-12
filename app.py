try:
    # 1. 先讀取原始金鑰
    raw_key = st.secrets["BOOKING_API_KEY"]
    
    # 2. 暴力消毒：將字串轉為純 ASCII，強制濾除所有中文、全形空白與隱藏字元，並去掉前後空白
    BOOKING_API_KEY = raw_key.encode('ascii', 'ignore').decode('ascii').strip()
    
except KeyError:
    st.error("🚨 系統找不到 Booking API 金鑰！請確認您已在 Streamlit 後台的 Secrets 中設定了 BOOKING_API_KEY。")
    st.stop()
