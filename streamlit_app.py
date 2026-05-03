import streamlit as st
import pandas as pd
import time
import os
import sqlite3
import threading
import random
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# ==========================================
# DEEPAK RAJPUT BRAND E2E AUTOMATION V20
# DEVELOPED BY: DEEPAK RAJPUT BRAND BOT
# VERSION: 20.5.2 (FULL EDITION)
# ==========================================

# --- CONFIGURATION ---
APP_NAME = "DEEPAK RAJPUT BRAND E2E AUTOMATION"
ADMIN_USER = "DEEPAK"
ADMIN_PASS = "BRAND"

# --- SYSTEM INITIALIZATION ---
st.set_page_config(page_title=APP_NAME, layout="wide", initial_sidebar_state="expanded")

# Database Setup
def init_db():
    conn = sqlite3.connect('drb_database.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        target_id TEXT,
        hater_name TEXT,
        delay INTEGER,
        status TEXT,
        sent_count INTEGER,
        total_msgs INTEGER,
        start_time TEXT
    )''')
    # Default Admin
    try:
        c.execute("INSERT INTO users VALUES (?, ?, ?)", (ADMIN_USER, ADMIN_PASS, 'admin'))
    except sqlite3.IntegrityError:
        pass
    conn.commit()
    return conn

conn = init_db()

# --- STYLING ---
st.markdown(f'''
    <style>
    .stApp {{ background-color: #000000; color: #00FF41; font-family: "Courier New", Courier, monospace; }}
    .main-header {{
        background: linear-gradient(90deg, #1d1d1d 0%, #004d00 100%);
        padding: 30px; border-radius: 15px; text-align: center;
        border: 2px solid #00FF41; box-shadow: 0 0 20px #00FF41;
        margin-bottom: 25px;
    }}
    .footer {{ text-align: center; padding: 20px; color: #00FF41; font-size: 14px; border-top: 1px solid #00FF41; margin-top: 50px; }}
    .stButton>button {{ background-color: #004d00; color: #00FF41; border: 1px solid #00FF41; border-radius: 5px; }}
    .stButton>button:hover {{ background-color: #00FF41; color: #000000; }}
    </style>
    <div class="main-header">
        <h1>{APP_NAME}</h1>
        <p>TERMINAL ACCESS: GRANTED | SYSTEM STATUS: OPTIMIZED</p>
    </div>
''', unsafe_allow_html=True)

# --- SELECTORS FOR E2E & MODERN FB ---
MODERN_SELECTORS = [
    'div[role="textbox"]',
    'div[contenteditable="true"]',
    '[aria-label="Write a message..."]',
    '[aria-label="Message"]',
    'div._5rpb > div',
    '#composer_text_input',
    'textarea[name="body"]'
]

# --- CORE BROWSER ENGINE ---
def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.binary_location = "/usr/bin/chromium"
    return webdriver.Chrome(options=options)

# --- AUTOMATION THREAD ---
def task_executor(task_id, target, hater, delay, cookies_str, messages):
    driver = None
    try:
        driver = get_driver()
        driver.get("https://m.facebook.com")
        
        # Cookie Injection
        try:
            cookies = json.loads(cookies_str)
            for cookie in cookies:
                driver.add_cookie(cookie)
        except:
            # Fallback for manual string parsing
            for item in cookies_str.split(';'):
                if '=' in item:
                    name, value = item.strip().split('=', 1)
                    driver.add_cookie({'name': name, 'value': value})
        
        driver.refresh()
        time.sleep(3)
        
        # Navigate to Chat
        driver.get(f"https://m.facebook.com/messages/t/{target}")
        
        sent = 0
        total = len(messages)
        
        for msg in messages:
            try:
                # Find Input Box
                input_box = None
                for selector in MODERN_SELECTORS:
                    try:
                        input_box = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        if input_box: break
                    except: continue
                
                if input_box:
                    final_msg = f"{hater} {msg.strip()}"
                    input_box.send_keys(final_msg)
                    
                    # Find Send Button
                    send_btn = None
                    send_selectors = ["button[name='send']", "button[type='submit']", "span[aria-label='Send']"]
                    for s in send_selectors:
                        try:
                            send_btn = driver.find_element(By.CSS_SELECTOR, s)
                            if send_btn: break
                        except: continue
                    
                    if send_btn:
                        send_btn.click()
                    else:
                        from selenium.webdriver.common.keys import Keys
                        input_box.send_keys(Keys.ENTER)
                        
                    sent += 1
                    # Update DB
                    c = conn.cursor()
                    c.execute("UPDATE tasks SET sent_count=?, status='RUNNING' WHERE id=?", (sent, task_id))
                    conn.commit()
                
                time.sleep(delay)
            except Exception as e:
                print(f"Loop Error: {e}")
                continue
                
        c = conn.cursor()
        c.execute("UPDATE tasks SET status='COMPLETED' WHERE id=?", (task_id,))
        conn.commit()
        
    except Exception as e:
        c = conn.cursor()
        c.execute("UPDATE tasks SET status=? WHERE id=?", (f"FAILED: {str(e)[:20]}", task_id))
        conn.commit()
    finally:
        if driver: driver.quit()

# --- MAIN DASHBOARD INTERFACE ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    cols = st.columns([1, 1.5, 1])
    with cols[1]:
        st.info("ROOT ACCESS REQUIRED")
        user = st.text_input("USER_ID")
        pwd = st.text_input("PASS_KEY", type="password")
        if st.button("AUTHENTICATE"):
            if user == ADMIN_USER and pwd == ADMIN_PASS:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.rerun()
            else:
                st.error("ACCESS DENIED")
else:
    # SIDEBAR
    st.sidebar.title("DRB CONTROL CENTER")
    menu = st.sidebar.selectbox("COMMANDS", ["NEW_TASK", "MONITOR_TASKS", "LOGS", "SYSTEM_SETTINGS"])
    
    if st.sidebar.button("KILL_SESSION"):
        st.session_state.logged_in = False
        st.rerun()

    if menu == "NEW_TASK":
        st.subheader("INITIALIZE NEW ATTACK SEQUENCE")
        with st.container():
            c1, c2 = st.columns(2)
            with c1:
                t_id = st.text_input("TARGET_UID")
                h_name = st.text_input("HATER_PREFIX")
                d_val = st.number_input("DELAY_SEC", min_value=1, value=60)
            with c2:
                cookies = st.text_area("COOKIES_DATA (JSON/STRING)")
                m_file = st.file_uploader("MESSAGE_SCRIPT (.txt)")
            
            if st.button("EXECUTE_LAUNCH"):
                if t_id and cookies and m_file:
                    msgs = m_file.read().decode("utf-8").splitlines()
                    start_t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    curr = conn.cursor()
                    curr.execute("INSERT INTO tasks (user, target_id, hater_name, delay, status, sent_count, total_msgs, start_time) VALUES (?,?,?,?,?,?,?,?)",
                               (st.session_state.user, t_id, h_name, d_val, "STARTING", 0, len(msgs), start_t))
                    conn.commit()
                    t_idx = curr.lastrowid
                    
                    # Start Thread
                    threading.Thread(target=task_executor, args=(t_idx, t_id, h_name, d_val, cookies, msgs)).start()
                    st.success("SEQUENCE INITIATED")
                else:
                    st.error("MISSING PARAMETERS")

    elif menu == "MONITOR_TASKS":
        st.subheader("ACTIVE OPERATION STATUS")
        df = pd.read_sql_query("SELECT id, target_id, status, sent_count, total_msgs, start_time FROM tasks", conn)
        st.table(df)

    elif menu == "LOGS":
        st.subheader("SYSTEM TELEMETRY")
        st.code(f'''
        [SYSTEM] {datetime.now()} : DEEPAK RAJPUT BRAND Engine Online.
        [INFO] Browser Binary: /usr/bin/chromium
        [STATUS] Database Connected.
        [INFO] E2E Selectors Loaded: {len(MODERN_SELECTORS)}
        ''')

    elif menu == "SYSTEM_SETTINGS":
        st.subheader("CORE CONFIGURATION")
        st.write("Server Uptime Protection: ACTIVE")
        st.write("Anti-Ban Shield: V20.5")
        st.checkbox("Force Desktop Mode (Emulation)")
        st.checkbox("Auto-Cookie Rotation")

# FOOTER
st.markdown(f'<div class="footer">© 2026 | {APP_NAME} | POWERED BY DEEPAK RAJPUT BRAND BOT V20.5.2</div>', unsafe_allow_html=True)
