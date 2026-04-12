# ==========================================
# 3. 執行邏輯 (Pro 方案火力全開版)
# ==========================================
if st.button("🚀 啟動 Booking.com 聯程區間掃描", use_container_width=True):
    if len(d1_date_range) != 2 or len(d4_date_range) != 2:
        st.error("⚠️ 請確保 D1 和 D4 都選擇了完整的「開始」與「結束」日期！(需在日曆上點擊兩次)")
    elif not d1_hubs or not d4_hubs:
        st.error("⚠️ 請至少選擇一個外站！")
    else:
        msg = st.empty()
        
        def get_dates_from_range(date_tuple):
            start_date, end_date = date_tuple
            delta = end_date - start_date
            return [start_date + timedelta(days=i) for i in range(delta.days + 1)]
            
        d1_dates = get_dates_from_range(d1_date_range)
        d4_dates = get_dates_from_range(d4_date_range)
        
        tasks = []
        for h1, h4 in product(d1_hubs, d4_hubs):
            for d1, d4 in product(d1_dates, d4_dates):
                if d1 >= date.today() and d1 < d2_date and d4 > d3_date:
                    tasks.append((h1, d1, h4, d4))

        # 【Pro 方案專屬】解開單次掃描上限至 1500 組
        MAX_REQUESTS = 1500 
        
        if len(tasks) > MAX_REQUESTS:
            st.error(f"🚨 組合數 ({len(tasks)} 組) 超出單次掃描建議上限 ({MAX_REQUESTS})！\n雖然您有 Pro 方案，但為了避免單次等待過久或觸發 API 的「每秒防 DDOS 阻擋」，請稍微縮小日期或外站範圍。")
        elif len(tasks) == 0:
            st.warning("⚠️ 沒有產生任何有效的搜尋組合，請檢查日期邏輯 (例如 D1 必須早於 D2)。")
        else:
            msg.warning(f"🔥 Pro 方案火力展示！正在向 Booking.com 發送 {len(tasks)} 組連線請求，請稍候...")
            pb = st.progress(0)
            
            valid_results = []
            raw_debug_data = []

            # 引擎轉速提升：max_workers 從 3 提高到 5
            with ThreadPoolExecutor(max_workers=5) as exe:
                future_to_task = {
                    exe.submit(fetch_booking_bundle, t[0], t[1], t[2], t[3], d2_org, d2_dst, d2_date, d3_org, d3_dst, d3_date, cabin_choice, adult_count, strict_ci_toggle): t 
                    for t in tasks
                }
                
                for idx, f in enumerate(as_completed(future_to_task)):
                    pb.progress((idx + 1) / len(tasks), text=f"高速掃描中 ({idx+1}/{len(tasks)})...")
                    res = f.result()
                    
                    if res["status"] == "success":
                        if debug_mode:
                            raw_debug_data.append(res["raw"])
                        
                        if res["offer"]:
                            valid_results.append(res["offer"])
                    else:
                        # 將錯誤印在後台或顯示警告，方便掌握 API 狀態
                        st.toast(f"⚠️ 某組請求發生錯誤: {res.get('error')}")
                            
            pb.empty()
            msg.empty()

            if valid_results:
                st.success("🎉 獵殺完畢！以下為即時回傳之報價：")
                valid_results.sort(key=lambda x: x['total'])
                
                for r in valid_results[:20]: # 顯示結果數量也從 10 放寬到 20
                    with st.expander(f"✅ {r['title']} | D1: {r['d1']} & D4: {r['d4']} ➔ 總價: {r['total']:,} {r['currency']}"):
                        for i, leg in enumerate(r['legs'], 1): 
                            st.write(f"{i}️⃣ {leg}")
            else:
                st.error("❌ 查無符合條件的結果。建議先取消「嚴格鎖定純華航」，並查看下方 Debug 資料。")

            if debug_mode and raw_debug_data:
                st.markdown("---")
                st.subheader("🛠️ Debug 模式：API 原始回傳資料")
                st.caption("以下為第一組回傳的原始 JSON 資料，請複製裡面的結構給我，我們來完成最後的解析邏輯！")
                st.json(raw_debug_data[0])
