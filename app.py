# 2. 外站接駁
st.subheader("🌍 外站接駁與精確打擊 (D1 / D4)")
st.info("💡 支援區間選擇！請點擊日期選擇「開始」與「結束」日。請注意 API 請求次數（組合數 = D1天數 × D4天數 × 樞紐數）。")

c_d1, c_d4 = st.columns(2)
with c_d1:
    d1_hubs = st.multiselect("D1 出發城市", ALL_HUBS, default=["KUL"])
    # 改為區間輸入：傳入 Tuple 作為預設值
    d1_date_range = st.date_input("D1 日期區間", value=(date(2026, 6, 8), date(2026, 6, 10)))

with c_d4:
    d4_hubs = st.multiselect("D4 抵達城市", ALL_HUBS, default=["KUL"])
    # 改為區間輸入
    d4_date_range = st.date_input("D4 日期區間", value=(date(2026, 6, 26), date(2026, 6, 28)))

c_cab, c_adt = st.columns(2)
with c_cab: cabin_choice = st.selectbox("艙等", ["商務艙", "豪經艙", "經濟艙"])
with c_adt: adult_count = st.number_input("人數", value=1, min_value=1)

if st.button("🚀 啟動 Booking.com 聯程區間掃描", use_container_width=True):
    # 檢查是否都有選好完整的「起迄日期」 (Streamlit 若只點擊一下，會回傳長度 1 的 tuple)
    if len(d1_date_range) != 2 or len(d4_date_range) != 2:
        st.error("⚠️ 請確保 D1 和 D4 都選擇了完整的「開始」與「結束」日期！(需在日曆上點擊兩次)")
    elif not d1_hubs or not d4_hubs:
        st.error("⚠️ 請至少選擇一個外站！")
    else:
        msg = st.empty()
        
        # 將區間展開成一天一天的 list
        def get_dates_from_range(date_tuple):
            start_date, end_date = date_tuple
            delta = end_date - start_date
            return [start_date + timedelta(days=i) for i in range(delta.days + 1)]
            
        d1_dates = get_dates_from_range(d1_date_range)
        d4_dates = get_dates_from_range(d4_date_range)
        
        # 準備所有組合任務
        tasks = []
        for h1, h4 in product(d1_hubs, d4_hubs):
            for d1, d4 in product(d1_dates, d4_dates):
                # 確保日期不回溯且邏輯正確
                if d1 >= date.today() and d1 < d2_date and d4 > d3_date:
                    tasks.append((h1, d1, h4, d4))

        # 【安全鎖機制】防止 API 額度瞬間乾枯
        MAX_REQUESTS = 50 
        if len(tasks) > MAX_REQUESTS:
            st.error(f"🚨 組合數過多 ({len(tasks)} 組)！這將會消耗大量 API 額度並可能被伺服器阻擋。請縮小日期區間或減少外站數量，將組合數控制在 {MAX_REQUESTS} 以內。")
        elif len(tasks) == 0:
            st.warning("⚠️ 沒有產生任何有效的搜尋組合，請檢查日期邏輯 (例如 D1 必須早於 D2)。")
        else:
            msg.warning(f"🔥 區間展開成功！正在向 Booking.com 發送 {len(tasks)} 組請求，請稍候...")
            pb = st.progress(0)
            
            valid_results = []
            raw_debug_data = []

            # 略微降低 max_workers 避免觸發 RapidAPI 的 RPS (每秒請求) 限制
            with ThreadPoolExecutor(max_workers=3) as exe:
                future_to_task = {
                    exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count, strict_ci_toggle): t 
                    for t in tasks
                }
                
                # ... (下方接續原本的迴圈與結果顯示代碼) ...
