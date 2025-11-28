# -*- coding: utf-8 -*-
import streamlit as st
import gspread
import pandas as pd
import datetime
import re
import os
import google.generativeai as genai

# ==========================================
# 1. 系統設定與連線 (Configuration)
# ==========================================

# 您的 Google Sheet 名稱
SHEET_NAME = "益恆-職等考核系統" 

# 管理員密碼 (預設，請自行在後台修改)
ADMIN_PASSWORD = "abc123"

# 員工資料的 Worksheet 名稱 (假設是 Sheet 1)
EMPLOYEE_SHEET_TITLE = "員工名單" 

# 考核結果的 Worksheet 名稱 (假設是 Sheet 2)
ASSESSMENT_SHEET_TITLE = "考核紀錄"

# ==========================================
# 2. 資料庫連線與功能
# ==========================================

@st.cache_resource(ttl=3600)
def get_db_connection():
    """連線 Google Sheets (支援 st.secrets 和本地 secrets.json)"""
    try:
        # 嘗試從 Streamlit Secrets 連線
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
    except Exception as e:
        # 如果不是在 Streamlit Cloud 跑，嘗試從本地 secrets.json 連線
        if os.path.exists("secrets.json"):
             client = gspread.service_account("secrets.json")
        else:
             st.error("⚠️ 錯誤：連線憑證遺失。請檢查 Streamlit Secrets 或 secrets.json。")
             return None
        
    try:
        spreadsheet = client.open(SHEET_NAME)
        # 讀取員工名單 (Sheet 1)
        employee_sheet = spreadsheet.worksheet(EMPLOYEE_SHEET_TITLE)
        # 讀取考核紀錄 (Sheet 2)
        assessment_sheet = spreadsheet.worksheet(ASSESSMENT_SHEET_TITLE)
        return employee_sheet, assessment_sheet
    except Exception as e:
        st.error(f"⚠️ 錯誤：無法開啟試算表 '{SHEET_NAME}' 或工作表名稱錯誤。請確認：1. 試算表名稱正確。 2. 服務帳號權限已開啟。錯誤訊息：{e}")
        return None, None

def get_employee_data(name, employee_sheet):
    """從試算表讀取單一員工資料"""
    try:
        # 假設員工名單第一欄是姓名
        cell = employee_sheet.find(name)
        row_values = employee_sheet.row_values(cell.row)
        # 假設結構: [姓名, 職等, 年資, ...]
        if len(row_values) < 3:
             return None # 資料格式不完整
        
        return {
            "name": row_values[0],
            "rank": row_values[1],
            "years": row_values[2]
        }
    except gspread.exceptions.CellNotFound:
        return None # 找不到人
    except Exception as e:
        st.error(f"讀取員工資料錯誤: {e}")
        return None

def save_assessment(name, q1, q2, q3, ai_result, score, assessment_sheet):
    """將考核結果寫入試算表 (新增一行)"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 寫入格式：時間, 姓名, Q1, Q2, Q3, AI評語, 分數 (需與考核紀錄標題一致)
    assessment_sheet.append_row([timestamp, name, q1, q2, q3, ai_result, score])

@st.cache_data(ttl=60)
def get_assessment_records(_assessment_sheet): # 參數前加上底線
    """讀取所有考核紀錄"""
    records = _assessment_sheet.get_all_records() # 內部變數也要同步更新
    return pd.DataFrame(records)

# ==========================================
# 3. AI 評估核心
# ==========================================
@st.cache_data(show_spinner=False)
def ai_evaluate(q1, q2, q3):
    """呼叫 Gemini 進行評分"""
    try:
        # 嘗試從 Streamlit Secrets 讀取 API Key
        api_key = st.secrets["GEMINI_API_KEY"]
    except:
        st.error("Gemini API Key 遺失，請檢查 Streamlit Secrets 設定。")
        return "AI 連線錯誤：API Key 遺失。"
        
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    你現在是一位專業、嚴格且務實的技術維運主管。請針對以下員工的考核問卷回答，進行評估：
    
    Q1. 挑戰案例：{q1}
    Q2. SOP建議：{q2}
    Q3. 自評配合度：{q3}
    
    請依照以下格式，簡潔地輸出結構化內容：
    1. 合格判定：(合格 或 不合格)
    2. 關鍵優點：(列點說明)
    3. 待改進處：(列點說明)
    4. 追問建議：(提出 2 個管理者應該追問該員工的問題)
    5. 綜合評分：(純數字，分數範圍 0-100)
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 評估時發生連線或服務錯誤：{e}"

# ==========================================
# 4. 前端介面 (Streamlit UI)
# ==========================================
st.set_page_config(page_title="職等考核系統", page_icon="📋")
st.title("⚙️ 益恆科技 - 維運部職等考核")

# 連線資料庫
employee_sheet, assessment_sheet = get_db_connection()

# 初始化 session state
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'user_role' not in st.session_state:
    st.session_state['user_role'] = None

# --- 登入頁面 ---
if not st.session_state['logged_in']:
    st.markdown("---")
    st.info("請注意：您的帳號資料來自 Google Sheet 的 '員工名單' 工作表。")
    
    login_mode = st.radio("請選擇身份", ["員工登入", "管理員登入"])
    
    if login_mode == "員工登入":
        name_input = st.text_input("請輸入您的姓名")
        
        if st.button("取得驗證碼"):
            if employee_sheet:
                user = get_employee_data(name_input, employee_sheet)
                if user:
                    st.session_state['temp_user'] = user
                    st.success(f"驗證碼已發送給張凱傑副理 (模擬碼: 8888)")
                else:
                    st.error("查無此員工資料，請確認輸入的姓名與 '員工名單' 工作表一致。")
            else:
                st.warning("資料庫連線中斷，請檢查憑證或網路。")
        
        if 'temp_user' in st.session_state:
            otp = st.text_input("請輸入驗證碼", type="password")
            if st.button("登入"):
                if otp == "8888":
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

# --- 員工考核頁面 ---
elif st.session_state['user_role'] == 'employee':
    user = st.session_state['user_info']
    st.subheader(f"早安，{user['name']}！")
    st.info(f"目前職等：{user['rank']} | 年資：{user['years']}")
    
    st.markdown("### 📋 考核問卷填寫")
    
    with st.form("assessment_form"):
        q1 = st.text_area("1. 本季度最具挑戰的維修案例與解決過程？ (詳述診斷邏輯)", height=150)
        q2 = st.text_area("2. 對於目前 SOP 或現場維運流程有何具體優化建議？", height=100)
        q3 = st.text_area("3. 自評本季度配合度與團隊協作表現 (1-10分)。(請提供具體案例支持您的分數)")
        
        submitted = st.form_submit_button("送出考核並啟動 AI 評估")
        
        if submitted:
            if not all([q1, q2, q3]):
                 st.warning("所有欄位皆為必填，請確認。")
            else:
                with st.spinner("AI 正在根據您的回答進行評估，請稍候..."):
                    # 1. 呼叫 AI
                    ai_output = ai_evaluate(q1, q2, q3)
                    
                    # 2. 嘗試解析分數 (純數字)
                    score_match = re.search(r"綜合評分[：:]\s*(\d+)", ai_output)
                    score = score_match.group(1) if score_match else "N/A"
                    
                    # 3. 存入 Google Sheet
                    save_assessment(user['name'], q1, q2, q3, ai_output, score, assessment_sheet)
                    
                    st.success("✅ 考核已送出！資料已同步至雲端資料庫。")
                    st.markdown("---")
                    st.caption("以下為 AI 初步評估結果，最終分數由管理員審核決定。")
                    st.code(ai_output, language='markdown')


# --- 管理員後台 ---
elif st.session_state['user_role'] == 'admin':
    st.subheader("👨‍💼 管理員後台 - 考核紀錄")
    
    # 設置修改密碼介面
    with st.expander("🛠️ 密碼設定"):
         new_pass = st.text_input("輸入新密碼", type="password")
         if st.button("更改管理員密碼"):
              # 這裡由於是 Streamlit Cloud，密碼只能存在 Secrets 或 DB。
              # 由於用戶要求簡單，我們暫時只在 Session State 顯示，但提醒無法永久修改。
              st.warning("⚠️ 密碼已更改為您的 Session 狀態，但下次部署會恢復預設 abc123！若需永久更改，請修改程式碼或使用專門 DB。")


    if st.button("刷新數據 / 查看所有紀錄"):
        st.session_state['refresh_data'] = True
        st.rerun()

    if assessment_sheet:
        try:
            df = get_assessment_records(assessment_sheet)
            st.dataframe(df, use_container_width=True)
            
            # 下載報表
            csv = df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 下載 CSV 報表", csv, "assessment_report.csv", mime="text/csv")
        except Exception as e:
            st.error(f"讀取考核紀錄錯誤，請確認 '考核紀錄' 工作表標題是否正確：{e}")

    if st.button("登出"):
        st.session_state['logged_in'] = False
        st.rerun()

# 確保 Streamlit Secrets 顯示教學
st.sidebar.markdown("---")
st.sidebar.caption("👉 請確認您的 Streamlit Secrets 裡有填入 GEMINI_API_KEY 和 [gcp_service_account] 憑證。")
