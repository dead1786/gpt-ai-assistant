# -*- coding: utf-8 -*-
import streamlit as st
import gspread
import pandas as pd
import datetime
import re
import os
import random # 引入隨機碼套件
import google.generativeai as genai

# ==========================================
# 1. 系統設定與連線 (Configuration)
# ==========================================

# 您的 Google Sheet 名稱 (請確保與雲端名稱一致)
SHEET_NAME = "益恆科技_考核系統_DB" 

# 管理員密碼
ADMIN_PASSWORD = "abc123"

# 工作表名稱
EMPLOYEE_SHEET_TITLE = "員工名單" 
ASSESSMENT_SHEET_TITLE = "考核紀錄"

# ==========================================
# 2. 資料庫連線與功能
# ==========================================

@st.cache_resource(ttl=3600)
def get_db_connection():
    """連線 Google Sheets (支援 st.secrets)"""
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
    except Exception:
        if os.path.exists("secrets.json"):
             client = gspread.service_account("secrets.json")
        else:
             return None, None
        
    try:
        spreadsheet = client.open(SHEET_NAME)
        employee_sheet = spreadsheet.worksheet(EMPLOYEE_SHEET_TITLE)
        assessment_sheet = spreadsheet.worksheet(ASSESSMENT_SHEET_TITLE)
        return employee_sheet, assessment_sheet
    except Exception:
        return None, None


def get_employee_data(employee_sheet):
    """讀取所有員工資料，並轉為字典"""
    try:
        records = employee_sheet.get_all_records()
        # 處理資料，確保欄位名一致：[姓名, 到職日, 職稱, 年資, 職等, IsAuthorized]
        employee_data = {
            r['姓名']: {
                'name': r['姓名'],
                'startDate': r.get('到職日', 'N/A'),
                'title': r.get('職稱', 'N/A'),
                'years': r.get('年資', 'N/A'),
                'rank': r.get('職等', 'N/A'),
                'authorized': r.get('授權開關', 'FALSE').upper() == 'TRUE',
                'row_index': employee_sheet.find(r['姓名']).row
            } for r in records
        }
        return employee_data
    except Exception as e:
        st.error(f"⚠️ 讀取員工名單結構錯誤，請確認工作表標題是否為：姓名, 到職日, 職稱, 年資, 職等, 授權開關。錯誤: {e}")
        return {}


def get_latest_submission(name, assessment_sheet):
    """檢查該員工是否有未完成最終審核的考核"""
    try:
        cell_list = assessment_sheet.findall(name)
        if not cell_list:
            return None, None

        latest_row = assessment_sheet.row_values(cell_list[-1].row)
        
        # 假設 Final_Score 在最後一欄 (第 12 欄)，如果為空則代表未完成最終評定
        if latest_row and (len(latest_row) < 12 or latest_row[11] == 'N/A' or not latest_row[11]):
            return cell_list[-1].row, latest_row 
        
        return None, None # 已有提交且已完成最終評分
        
    except Exception:
        return None, None


def save_assessment(name, q1, q2, q3, rating, initial_ai, initial_score, assessment_sheet):
    """將考核結果寫入試算表 (新增一行)"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 寫入格式：時間, 姓名, Q1, Q2, Q3, 自評分數, AI評語, AI初評分, 管理員評語, 管理員分數, 最終AI評語, 最終分數
    # 這裡確保寫入 12 欄，未填入的部份留空
    row_data = [timestamp, name, q1, q2, q3, rating, initial_ai, initial_score] + [""] * 4
    assessment_sheet.append_row(row_data)


def update_final_assessment(row_index, review, score, final_ai_summary, final_score, assessment_sheet):
    """更新管理員評語和最終分數"""
    # 假設欄位索引：9=管理員評語, 10=管理員分數, 11=最終AI評語, 12=最終分數
    # 這是 gspread 專用，索引從 1 開始
    assessment_sheet.update_cell(row_index, 9, review) 
    assessment_sheet.update_cell(row_index, 10, score) 
    assessment_sheet.update_cell(row_index, 11, final_ai_summary) 
    assessment_sheet.update_cell(row_index, 12, final_score) 


@st.cache_data(ttl=60)
def get_assessment_records(_assessment_sheet):
    """讀取所有考核紀錄"""
    records = _assessment_sheet.get_all_records()
    return pd.DataFrame(records)


# ==========================================
# 3. AI 評估核心
# ==========================================
@st.cache_data(show_spinner=False)
def ai_get_summary(prompt_type, data):
    """呼叫 Gemini 進行評分或最終評定"""
    try:
        # 修正 Key 遺失的錯誤：讀取 [gemini_creds] 區塊下的 api_key
        api_key = st.secrets["gemini_creds"]["api_key"]
    except Exception:
        return "AI 連線錯誤：Gemini API Key 遺失或格式錯誤。"
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    if prompt_type == 'initial':
        q1, q2, q3 = data
        prompt = f"""
        你現在是一位嚴格且務實的技術主管，請根據以下員工回答，給出「初階評估」。
        
        Q1. 挑戰案例：{q1}
        Q2. SOP建議：{q2}
        Q3. 薪酬改革看法：{q3}
        
        請依照以下格式，簡潔地輸出結構化內容：
        1. 合格判定：(合格/不合格)
        2. 關鍵優點：(列點說明)
        3. 待改進處：(列點說明，需包含對薪酬改革的態度分析)
        4. 追問建議：(提出 2 個管理者應該追問該員工的問題)
        5. 綜合評分：(純數字，分數範圍 0-100)
        """
    elif prompt_type == 'final':
        employee_answer, initial_ai_summary, manager_review, manager_score = data
        
        prompt = f"""
        你現在是一位資深 HR 專家，請綜合「員工回答」、「AI 初評」與「管理員審核結果」，給出最終評定。
        
        --- 員工原始回答 ---
        挑戰案例: {employee_answer['Q1回答']}
        SOP建議: {employee_answer['Q2回答']}
        薪酬改革看法: {employee_answer['Q3回答']}
        
        --- AI 初評與管理員審核 ---
        AI初評：{initial_ai_summary}
        管理員評語: {manager_review}
        管理員評分: {manager_score}
        
        請給出最終評語與最終分數：
        1. 最終結論：(總結該員工是否達到晉升或留任標準)
        2. 發展建議：(列點建議未來成長方向)
        3. 最終分數：(純數字，分數範圍 0-100)
        """
        
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 服務連線失敗或格式錯誤: {e}"


# ==========================================
# 4. 前端介面 (Streamlit UI)
# ==========================================
st.set_page_config(page_title="職等考核系統", page_icon="📋")
st.title("⚙️ 益恆科技 - 維運部職等考核")

employee_sheet, assessment_sheet = get_db_connection()

# 檢查連線是否成功，若失敗則顯示錯誤訊息並停止
if employee_sheet is None or assessment_sheet is None:
    st.error(f"⚠️ 嚴重錯誤：資料庫連線失敗。請確認：1. Google Sheet 名稱正確。 2. Secrets 憑證 ([gcp_service_account]) 完整且權限已開。")
    st.stop()
    
# 讀取員工名單
ALL_EMPLOYEE_DATA = get_employee_data(employee_sheet)
st.session_state['ALL_EMPLOYEE_DATA'] = ALL_EMPLOYEE_DATA


# 初始化 session state
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_role' not in st.session_state:
    st.session_state['user_role'] = None


# --- 登入頁面 ---
if not st.session_state['logged_in']:
    st.markdown("---")
    
    login_mode = st.radio("請選擇身份", ["員工登入", "管理員登入"])
    
    if login_mode == "員工登入":
        name_input = st.text_input("請輸入您的姓名")
        user = st.session_state['ALL_EMPLOYEE_DATA'].get(name_input)
        
        if name_input and not user:
             st.error("查無此員工資料。")
        
        if user:
            # 檢查授權開關
            if not user['authorized']:
                st.error("❌ 抱歉，您的考核授權開關目前未開啟，請洽管理員。")
                st.stop() 
            
            # 檢查是否已提交過
            latest_row_index, latest_submission = get_latest_submission(user['name'], assessment_sheet)
            
            if latest_row_index:
                st.warning("⚠️ 您本次的考核已提交，管理員正在審核中。請勿重複作答。")
                st.stop()
            
            # --- 獨特驗證碼邏輯 ---
            if st.button("取得驗證碼"):
                # 生成獨特的 6 位數密碼
                unique_otp = str(random.randint(100000, 999999))
                st.session_state['temp_otp'] = unique_otp 
                st.session_state['temp_user'] = user
                
                # 顯示給管理者（您）看，但對員工來說這是從您那裡收到的
                st.success("✅ 驗證碼已發送給管理員。請向張凱傑副理索取！") 
                st.warning(f"🔑 獨特驗證碼（請轉發給員工）：{unique_otp}")
            
            
            if 'temp_user' in st.session_state:
                otp = st.text_input("請輸入驗證碼", type="password")
                if st.button("登入"):
                    if otp == st.session_state.get('temp_otp'):
                        st.session_state['logged_in'] = True
                        st.session_state['user_role'] = 'employee'
                        st.session_state['user_info'] = st.session_state['temp_user']
                        st.rerun()
                    else:
                        st.error("驗證碼錯誤")

    else: # 管理員
        admin_user = st.text_input("管理員帳號 (張凱傑)")
        admin_pass = st.text_input("密碼 (預設: abc123)", type="password")
        if st.button("管理員登入"):
            if admin_user == "張凱傑" and admin_pass == ADMIN_PASSWORD:
                st.session_state['logged_in'] = True
                st.session_state['user_role'] = 'admin'
                st.session_state['user_info'] = {'name': '張凱傑'}
                st.rerun()
            else:
                st.error("帳號或密碼錯誤")
        
        # 模擬 OTP 顯示給管理員
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔑 員工驗證碼提供區")
        if 'temp_otp' in st.session_state:
             st.sidebar.info(f"最近一次請求碼：**{st.session_state['temp_otp']}**")
        else:
             st.sidebar.caption("尚無員工請求驗證碼。")


# --- 員工考核頁面 ---
elif st.session_state['user_role'] == 'employee':
    user = st.session_state['user_info']
    st.subheader(f"早安，{user['name']}！")
    st.info(f"目前職等：{user['rank']} | 年資：{user['years']}")
    
    # 確認是否已經提交過，如果已經通過了登入，這裡就顯示一次提醒
    latest_row_index, latest_submission = get_latest_submission(user['name'], assessment_sheet)
    if latest_row_index:
        st.warning("⚠️ 您本次的考核已提交，管理員正在審核中。請勿重複作答。")
        st.stop()


    st.markdown("### 📋 考核問卷填寫")
    
    with st.form("assessment_form"):
        q1 = st.text_area("1. 實務挑戰：本季度最具挑戰的維修案例與您創新的解決過程？ (詳述診斷邏輯)", height=150)
        q2 = st.text_area("2. 流程優化：對於目前 SOP 或現場維運流程有何具體且可執行的優化建議？", height=100)
        q3 = st.text_area("3. 組織認知：對於公司「薪酬/排班」改革（公平輪值與津貼制）的看法與建議？", height=100)
        
        # Q4 改為 Slider
        rating = st.slider("4. 團隊協作自評：本季度配合度與團隊協作表現 (1-10分，請在 Q3 提供支持分數的案例)", 
                           min_value=1, max_value=10, value=7)
        
        submitted = st.form_submit_button("送出考核並啟動 AI 初評")
        
        if submitted:
            if not all([q1, q2, q3]):
                 st.warning("所有文字欄位皆為必填，請確認。")
            else:
                with st.spinner("AI 正在根據您的回答進行評估，請稍候..."):
                    # 1. 呼叫 AI 初評
                    ai_output = ai_get_summary('initial', (q1, q2, q3))
                    
                    # 2. 嘗試解析分數 (純數字)
                    score_match = re.search(r"綜合評分[：:]\s*(\d+)", ai_output)
                    initial_score = score_match.group(1) if score_match else "N/A"
                    
                    # 3. 存入 Google Sheet
                    save_assessment(user['name'], q1, q2, q3, rating, ai_output, initial_score, assessment_sheet)
                    
                    st.success("✅ 考核已送出！資料已同步至雲端資料庫，請等待管理員最終審核。")
                    st.balloons()
                    st.code(ai_output, language='markdown')


# --- 管理員後台 ---
elif st.session_state['user_role'] == 'admin':
    st.subheader("👨‍💼 管理員後台")
    
    if st.button("刷新數據"):
        st.cache_data.clear() # 清除緩存確保讀取最新數據
        st.rerun()
    
    if assessment_sheet:
        try:
            df_assess = get_assessment_records(assessment_sheet)
            
            # 篩選未完成最終評分的紀錄
            # 這裡檢查 '最終分數' 欄位是否為空 (對應 Google Sheet 的第 12 欄)
            pending_df = df_assess[df_assess['最終分數'] == '']
            
            st.info(f"待審核紀錄數量: {len(pending_df)}")

            if not pending_df.empty:
                st.subheader("📝 待審批列表")
                # 顯示待審核列表
                st.dataframe(pending_df[['姓名', '時間', 'AI初評分']], use_container_width=True)

                # 讓管理員選擇要審核的員工
                selected_name = st.selectbox("選擇要審核的員工", options=pending_df['姓名'].unique())
                
                if selected_name:
                    record = pending_df[pending_df['姓名'] == selected_name].iloc[0]
                    # 找出該筆紀錄在 Google Sheet 上的實際 Row Index
                    # (Google Sheet 行數 = DF index + 標題行 1 + 數據偏移 1 = DF index + 2)
                    record_index = df_assess[df_assess['時間'] == record['時間']].index[0] + 2 
                    
                    st.markdown(f"#### 審批員工：{selected_name} (GS Row Index: {record_index})")
                    
                    with st.expander("📝 員工原始回答與 AI 初評"):
                        st.code(f"Q1: {record['Q1回答']}\nQ2: {record['Q2回答']}\nQ3: {record['Q3回答']}", language='text')
                        st.info(f"員工自評分數 (1-10): {record['自評分數']}")
                        st.code(record['AI評語'], language='markdown')
                        st.info(f"AI 初評分數: {record['AI初評分']}")
                        
                    
                    # 管理員給予評語和分數
                    manager_review = st.text_area("管理員主管綜合評語 (必填)", height=150)
                    manager_score = st.slider("管理員主管初評分數 (0-100)", 
                                              min_value=0, max_value=100, value=75)
                    
                    if st.button("啟動 AI 最終評定"):
                        if not manager_review:
                            st.error("管理員評語不可為空。")
                        else:
                            with st.spinner("AI 正在綜合初評與您的意見，生成最終評定..."):
                                # 呼叫 AI 最終評定
                                final_ai_output = ai_get_summary('final', (record, record['AI評語'], manager_review, manager_score))
                                
                                # 解析最終分數
                                final_score_match = re.search(r"最終分數[：:]\s*(\d+)", final_ai_output)
                                final_score = final_score_match.group(1) if final_score_match else "N/A"
                                
                                # 更新 Google Sheet
                                update_final_assessment(
                                    row_index=record_index, 
                                    review=manager_review, 
                                    score=str(manager_score), 
                                    final_ai_summary=final_ai_output, 
                                    final_score=final_score,
                                    assessment_sheet=assessment_sheet
                                )
                                
                                st.success(f"✅ 最終評定完成！最終分數為 {final_score}。請點擊刷新數據查看結果。")
                                st.code(final_ai_output, language='markdown')


            else:
                st.info("所有考核紀錄皆已完成最終審核。")

        except Exception as e:
            st.error(f"讀取考核紀錄錯誤，請確認 '考核紀錄' 工作表標題是否正確：{e}")

    # 登出按鈕
    if st.button("登出"):
        st.session_state['logged_in'] = False
        st.rerun()
