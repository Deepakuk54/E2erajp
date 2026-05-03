import streamlit as st
import streamlit.components.v1 as components
import time
import threading
import uuid
import hashlib
import os
import json
import pickle
from pathlib import Path
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException, WebDriverException
import sqlite3
from cryptography.fernet import Fernet

# ==================== CONFIGURATION ====================

DB_PATH = Path(__file__).parent / 'users.db'
ENCRYPTION_KEY_FILE = Path(__file__).parent / '.encryption_key'
SESSION_FILE = Path(__file__).parent / '.session_data'
UPLOAD_DIR = Path(__file__).parent / 'uploads'
HEARTBEAT_FILE = Path(__file__).parent / '.heartbeat'
UPLOAD_DIR.mkdir(exist_ok=True)

# Admin Credentials
ADMIN_USERNAME = "DEEPAK"
ADMIN_PASSWORD = "DEEPAK420"

# Failure tracking constants - 6 hours continuous failure across ALL cookies
FAILURE_THRESHOLD_HOURS = 6

# Heartbeat interval (2 minutes)
HEARTBEAT_INTERVAL = 120  # seconds

# ==================== HEARTBEAT MECHANISM ====================

class HeartbeatManager:
    """Manages heartbeat to prevent server from going to sleep"""
    def __init__(self):
        self.running = False
        self.thread = None
        self.last_beat = None
        
    def start(self):
        """Start heartbeat thread"""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self.thread.start()
            print(f"💓 Heartbeat started - will ping every {HEARTBEAT_INTERVAL} seconds")
    
    def stop(self):
        """Stop heartbeat thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("💓 Heartbeat stopped")
    
    def _heartbeat_loop(self):
        """Main heartbeat loop"""
        while self.running:
            try:
                # Update heartbeat file
                self.last_beat = datetime.now()
                with open(HEARTBEAT_FILE, 'w') as f:
                    f.write(f"HEARTBEAT: {self.last_beat.isoformat()}\n")
                    f.write(f"STATUS: ALIVE\n")
                
                # Also log to console
                print(f"💓 Heartbeat ping - {self.last_beat.strftime('%H:%M:%S')}")
                
                # Sleep for interval
                time.sleep(HEARTBEAT_INTERVAL)
            except Exception as e:
                print(f"❌ Heartbeat error: {str(e)}")
                time.sleep(HEARTBEAT_INTERVAL)
    
    def get_status(self):
        """Get heartbeat status"""
        if self.last_beat:
            elapsed = (datetime.now() - self.last_beat).total_seconds()
            return f"Last beat: {int(elapsed)}s ago"
        return "Not started"

# Global heartbeat manager
HEARTBEAT_MANAGER = HeartbeatManager()

# ==================== ENCRYPTION & SESSION ====================

def get_encryption_key():
    if ENCRYPTION_KEY_FILE.exists():
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(ENCRYPTION_KEY_FILE, 'wb') as f:
            f.write(key)
        return key

ENCRYPTION_KEY = get_encryption_key()
cipher_suite = Fernet(ENCRYPTION_KEY)

def save_session(user_id, username, is_admin):
    """Save session to file for persistence across refreshes"""
    session_data = {
        'user_id': user_id,
        'username': username,
        'is_admin': is_admin,
        'timestamp': datetime.now().isoformat()
    }
    with open(SESSION_FILE, 'wb') as f:
        pickle.dump(session_data, f)

def load_session():
    """Load session from file"""
    try:
        if SESSION_FILE.exists():
            with open(SESSION_FILE, 'rb') as f:
                session_data = pickle.load(f)
                return session_data
        return None
    except:
        return None

def clear_session():
    """Clear session file on logout"""
    try:
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
    except:
        pass

# ==================== DATABASE SECTION ====================

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_id TEXT UNIQUE NOT NULL,
            chat_id TEXT,
            name_prefix TEXT,
            delay INTEGER DEFAULT 30,
            cookie_type TEXT DEFAULT 'single',
            cookies_encrypted TEXT,
            messages TEXT,
            is_running INTEGER DEFAULT 0,
            messages_sent INTEGER DEFAULT 0,
            last_success_time TEXT,
            last_failure_time TEXT,
            last_working_cookie_index INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            log_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    ''')

    conn.commit()
    conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def encrypt_cookies(cookies):
    if not cookies:
        return None
    return cipher_suite.encrypt(cookies.encode()).decode()

def decrypt_cookies(encrypted_cookies):
    if not encrypted_cookies:
        return ""
    try:
        return cipher_suite.decrypt(encrypted_cookies.encode()).decode()
    except:
        return ""

def create_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        password_hash = hash_password(password)
        cursor.execute('INSERT INTO users (username, password_hash) VALUES (?, ?)',
                      (username, password_hash))
        conn.commit()
        conn.close()
        return True, "Account created successfully!"
    except sqlite3.IntegrityError:
        conn.close()
        return False, "Username already exists!"
    except Exception as e:
        conn.close()
        return False, f"Error: {str(e)}"

def verify_user(username, password):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT id FROM users WHERE username = ?', (ADMIN_USERNAME,))
        admin = cursor.fetchone()

        if not admin:
            password_hash = hash_password(ADMIN_PASSWORD)
            cursor.execute('INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)',
                         (ADMIN_USERNAME, password_hash, 1))
            conn.commit()
            admin_id = cursor.lastrowid
            conn.close()
            return admin_id, True
        conn.close()
        return admin[0], True

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, password_hash, is_admin FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()

    if user and user[1] == hash_password(password):
        return user[0], bool(user[2])
    return None, False

def generate_task_id():
    """Generate unique task ID in format TASK-abc123"""
    return f"TASK-{uuid.uuid4().hex[:6]}"

def create_task(user_id, chat_id, name_prefix, delay, cookie_type, cookies, messages):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    encrypted_cookies = encrypt_cookies(cookies)
    task_id = generate_task_id()
    current_time = datetime.now().isoformat()

    cursor.execute('''
        INSERT INTO tasks (user_id, task_id, chat_id, name_prefix, delay, cookie_type,
                          cookies_encrypted, messages, is_running, last_success_time,
                          last_working_cookie_index)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, 0)
    ''', (user_id, task_id, chat_id, name_prefix, delay, cookie_type, encrypted_cookies, messages, current_time))

    db_task_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return db_task_id, task_id

def get_user_tasks(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, task_id, chat_id, name_prefix, delay, cookie_type, cookies_encrypted,
               messages, is_running, messages_sent, created_at, last_success_time,
               last_failure_time, last_working_cookie_index
        FROM tasks WHERE user_id = ?
        ORDER BY created_at DESC
    ''', (user_id,))
    tasks = cursor.fetchall()
    conn.close()

    result = []
    for task in tasks:
        result.append({
            'id': task[0],
            'task_id': task[1],
            'chat_id': task[2],
            'name_prefix': task[3],
            'delay': task[4],
            'cookie_type': task[5],
            'cookies': decrypt_cookies(task[6]),
            'messages': task[7],
            'is_running': bool(task[8]),
            'messages_sent': task[9],
            'created_at': task[10],
            'last_success_time': task[11],
            'last_failure_time': task[12],
            'last_working_cookie_index': task[13]
        })
    return result

def get_all_tasks():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT t.id, t.task_id, t.chat_id, t.is_running, t.messages_sent,
               t.created_at, u.username, t.user_id, t.last_success_time,
               t.last_failure_time
        FROM tasks t
        JOIN users u ON t.user_id = u.id
        ORDER BY t.created_at DESC
    ''')
    tasks = cursor.fetchall()
    conn.close()

    result = []
    for task in tasks:
        result.append({
            'id': task[0],
            'task_id': task[1],
            'chat_id': task[2],
            'is_running': bool(task[3]),
            'messages_sent': task[4],
            'created_at': task[5],
            'username': task[6],
            'user_id': task[7],
            'last_success_time': task[8],
            'last_failure_time': task[9]
        })
    return result

def update_task_status(task_id, is_running):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET is_running = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                  (1 if is_running else 0, task_id))
    conn.commit()
    conn.close()

def update_task_message_count(task_id, count):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE tasks SET messages_sent = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                  (count, task_id))
    conn.commit()
    conn.close()

def update_task_success_time(task_id):
    """Update last success time when message sends successfully"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    current_time = datetime.now().isoformat()
    cursor.execute('''
        UPDATE tasks
        SET last_success_time = ?,
            last_failure_time = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (current_time, task_id))
    conn.commit()
    conn.close()

def update_task_failure_time(task_id):
    """Update last failure time"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    current_time = datetime.now().isoformat()
    cursor.execute('''
        UPDATE tasks
        SET last_failure_time = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (current_time, task_id))
    conn.commit()
    conn.close()

def update_working_cookie_index(task_id, cookie_index):
    """Update the last working cookie index"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tasks
        SET last_working_cookie_index = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    ''', (cookie_index, task_id))
    conn.commit()
    conn.close()

def get_task_by_id(task_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, user_id, task_id, chat_id, name_prefix, delay, cookie_type,
               cookies_encrypted, messages, is_running, messages_sent,
               last_success_time, last_failure_time, last_working_cookie_index
        FROM tasks WHERE id = ?
    ''', (task_id,))
    task = cursor.fetchone()
    conn.close()

    if task:
        return {
            'id': task[0],
            'user_id': task[1],
            'task_id': task[2],
            'chat_id': task[3],
            'name_prefix': task[4],
            'delay': task[5],
            'cookie_type': task[6],
            'cookies': decrypt_cookies(task[7]),
            'messages': task[8],
            'is_running': bool(task[9]),
            'messages_sent': task[10],
            'last_success_time': task[11],
            'last_failure_time': task[12],
            'last_working_cookie_index': task[13]
        }
    return None

def add_task_log(task_id, log_message):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT INTO task_logs (task_id, log_message) VALUES (?, ?)',
                  (task_id, log_message))
    conn.commit()
    conn.close()

def get_task_logs(task_id, limit=50):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT log_message, created_at
        FROM task_logs
        WHERE task_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    ''', (task_id, limit))
    logs = cursor.fetchall()
    conn.close()
    return [(log[0], log[1]) for log in logs]

def delete_task(task_id):
    """Complete task deletion - database and all related data"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM task_logs WHERE task_id = ?', (task_id,))
    cursor.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
    conn.commit()
    conn.close()

init_db()

# ==================== TASK AUTOMATION ====================

# Global dictionary to track running tasks
RUNNING_TASKS = {}
TASK_DRIVERS = {}  # Store driver references for cleanup
TASK_THREADS = {}  # Store thread references

class AutomationState:
    def __init__(self, task_id):
        self.task_id = task_id
        self.running = False
        self.message_count = 0
        self.message_rotation_index = 0
        self.cookie_index = 0
        self.last_success_time = datetime.now()
        self.last_failure_time = None
        self.stop_requested = False  # NEW: Explicit stop flag

def log_message(msg, task_id):
    timestamp = time.strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    add_task_log(task_id, formatted_msg)

def setup_browser(task_id):
    log_message('Setting up Chrome browser...', task_id)

    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-setuid-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-extensions')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36')

    # Add preferences to prevent detection
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    chromium_paths = ['/usr/bin/chromium', '/usr/bin/chromium-browser', '/usr/bin/google-chrome', '/usr/bin/chrome']
    for chromium_path in chromium_paths:
        if Path(chromium_path).exists():
            chrome_options.binary_location = chromium_path
            log_message(f'Found Chromium at: {chromium_path}', task_id)
            break

    try:
        from selenium.webdriver.chrome.service import Service
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_window_size(1920, 1080)

        # Remove webdriver property
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        log_message('Chrome browser setup completed successfully!', task_id)
        return driver
    except Exception as error:
        log_message(f'Browser setup failed: {error}', task_id)
        raise error

def check_stop_requested(automation_state, task_id):
    """Check if stop was requested and return True if should stop"""
    if not automation_state.running or automation_state.stop_requested:
        log_message(f'{task_id}: Stop requested detected - halting operations', task_id)
        return True
    return False

def check_page_validity(driver, task_id):
    """Check if page is still valid and not logged out"""
    try:
        # Check if we're on a valid Facebook page
        current_url = driver.current_url
        if 'login' in current_url.lower() or 'checkpoint' in current_url.lower():
            return False

        # Check if page body exists
        driver.find_element(By.TAG_NAME, 'body')
        return True
    except:
        return False

def find_message_input(driver, process_id, task_id, automation_state):
    """Find message input with stop checks"""
    log_message(f'{process_id}: Finding message input...', task_id)

    # Check stop before starting
    if check_stop_requested(automation_state, task_id):
        return None

    # Wait for page to load with stop checks
    for i in range(8):
        if check_stop_requested(automation_state, task_id):
            return None
        time.sleep(1)

    try:
        # Gentle scroll to load elements
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        if check_stop_requested(automation_state, task_id):
            return None
        driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(2)
    except Exception as e:
        log_message(f'{process_id}: Scroll error: {str(e)[:50]}', task_id)

    if check_stop_requested(automation_state, task_id):
        return None

    message_input_selectors = [
        'div[contenteditable="true"][role="textbox"]',
        'div[contenteditable="true"][data-lexical-editor="true"]',
        'div[aria-label*="message" i][contenteditable="true"]',
        'div[aria-label*="Message" i][contenteditable="true"]',
        'div[contenteditable="true"][spellcheck="true"]',
        '[role="textbox"][contenteditable="true"]',
        'textarea[placeholder*="message" i]',
        '[contenteditable="true"]'
    ]

    for idx, selector in enumerate(message_input_selectors):
        if check_stop_requested(automation_state, task_id):
            return None
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                try:
                    is_editable = driver.execute_script("""
                        return arguments[0].contentEditable === 'true' ||
                               arguments[0].tagName === 'TEXTAREA' ||
                               arguments[0].tagName === 'INPUT';
                    """, element)

                    if is_editable:
                        log_message(f'{process_id}: Found editable element!', task_id)
                        return element
                except Exception:
                    continue
        except Exception:
            continue

    return None

def get_next_message(messages, message_index):
    if not messages or len(messages) == 0:
        return 'Hello!', 0
    message = messages[message_index % len(messages)]
    return message, (message_index + 1) % len(messages)

def check_6_hour_continuous_failure(automation_state, task_id):
    """
    Check if ALL cookies have been continuously failing for 6 hours.
    Returns True if task should stop, False if task should continue.
    """
    # If we've had any success, we're good
    if automation_state.last_failure_time is None:
        return False
    
    try:
        last_failure = datetime.fromisoformat(automation_state.last_failure_time)
        time_since_last_failure = datetime.now() - last_failure
        
        # Check if 6 hours have passed since last failure started
        if time_since_last_failure >= timedelta(hours=FAILURE_THRESHOLD_HOURS):
            log_message(f'All cookies have been failing for {FAILURE_THRESHOLD_HOURS} hours continuously. Auto-stopping task.', task_id)
            return True
    except:
        pass
    
    return False

def apply_cookie_to_browser(driver, cookie_string, cookie_index, process_id, task_id, automation_state):
    """Apply cookie to browser with stop checks. Returns True if successful, False otherwise."""
    try:
        log_message(f'{process_id}: Applying cookie #{cookie_index + 1}...', task_id)
        
        if check_stop_requested(automation_state, task_id):
            return False
        
        # Clear existing cookies
        driver.delete_all_cookies()
        driver.get('https://www.facebook.com/')
        
        # Wait with stop checks
        for i in range(5):
            if check_stop_requested(automation_state, task_id):
                return False
            time.sleep(1)
        
        # Parse and add cookies
        cookie_array = cookie_string.split(';')
        cookies_added = 0
        
        for cookie in cookie_array:
            if check_stop_requested(automation_state, task_id):
                return False
            cookie_trimmed = cookie.strip()
            if cookie_trimmed and '=' in cookie_trimmed:
                first_equal_index = cookie_trimmed.find('=')
                name = cookie_trimmed[:first_equal_index].strip()
                value = cookie_trimmed[first_equal_index + 1:].strip()
                try:
                    driver.add_cookie({
                        'name': name,
                        'value': value,
                        'domain': '.facebook.com',
                        'path': '/'
                    })
                    cookies_added += 1
                except Exception:
                    pass
        
        log_message(f'{process_id}: Added {cookies_added} cookie parts', task_id)
        return True
        
    except Exception as e:
        log_message(f'{process_id}: Cookie application error: {str(e)[:100]}', task_id)
        return False

def send_single_message_with_cookie(driver, task, automation_state, process_id, 
                                   cookie_string, cookie_index, total_cookies,
                                   messages_list, delay):
    """
    CRITICAL FIX: Complete ONE full message send cycle with ONE cookie.
    Returns: ('success', message_sent) or ('failed', error_message)
    This ensures each cookie completes its work before moving to next.
    """
    task_id = task['id']
    
    # Check stop at start
    if check_stop_requested(automation_state, task_id):
        return ('stopped', 'Stop requested')
    
    try:
        # Step 1: Apply cookie
        log_message(f'{process_id}: [Cookie #{cookie_index + 1}/{total_cookies}] Starting message send cycle...', task_id)
        
        cookie_applied = apply_cookie_to_browser(driver, cookie_string, cookie_index, 
                                                 process_id, task_id, automation_state)
        if not cookie_applied:
            return ('failed', 'Cookie application failed')
        
        if check_stop_requested(automation_state, task_id):
            return ('stopped', 'Stop requested')
        
        # Step 2: Navigate to chat
        if task['chat_id']:
            chat_id = task['chat_id'].strip()
            driver.get(f'https://www.facebook.com/messages/e2ee/t/{chat_id}')
        else:
            driver.get('https://www.facebook.com/messages')
        
        # Wait for page load with stop checks
        for i in range(10):
            if check_stop_requested(automation_state, task_id):
                return ('stopped', 'Stop requested')
            time.sleep(1)
        
        # Step 3: Find message input
        message_input = find_message_input(driver, process_id, task_id, automation_state)
        
        if not message_input:
            return ('failed', 'Message input not found')
        
        if check_stop_requested(automation_state, task_id):
            return ('stopped', 'Stop requested')
        
        # Step 4: Prepare message
        base_message, automation_state.message_rotation_index = get_next_message(
            messages_list, automation_state.message_rotation_index
        )
        
        if task['name_prefix']:
            message_to_send = f"{task['name_prefix']} {base_message}"
        else:
            message_to_send = base_message
        
        # Step 5: Type message
        try:
            driver.execute_script("""
                const element = arguments[0];
                const message = arguments[1];

                if (!element) {
                    throw new Error('Element is null');
                }

                element.scrollIntoView({behavior: 'smooth', block: 'center'});
                element.focus();
                element.click();

                if (element.tagName === 'DIV') {
                    element.textContent = message;
                    element.innerHTML = message;
                } else {
                    element.value = message;
                }

                element.dispatchEvent(new Event('input', { bubbles: true }));
                element.dispatchEvent(new Event('change', { bubbles: true }));
                element.dispatchEvent(new InputEvent('input', { bubbles: true, data: message }));
            """, message_input, message_to_send)
        except Exception as js_error:
            return ('failed', f'Message typing error: {str(js_error)[:100]}')
        
        time.sleep(1)
        
        if check_stop_requested(automation_state, task_id):
            return ('stopped', 'Stop requested')
        
        # Step 6: Send message
        sent = driver.execute_script("""
            const sendButtons = document.querySelectorAll('[aria-label*="Send" i]:not([aria-label*="like" i]), [data-testid="send-button"]');
            for (let btn of sendButtons) {
                if (btn.offsetParent !== null) {
                    btn.click();
                    return 'button_clicked';
                }
            }
            return 'button_not_found';
        """)

        if sent == 'button_not_found':
            driver.execute_script("""
                const element = arguments[0];
                if (!element) throw new Error('Element is null');
                element.focus();
                const events = [
                    new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }),
                    new KeyboardEvent('keypress', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }),
                    new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true })
                ];
                events.forEach(event => element.dispatchEvent(event));
            """, message_input)
            log_message(f'{process_id}: Sent via Enter', task_id)
        else:
            log_message(f'{process_id}: Sent via button', task_id)
        
        # SUCCESS - Update everything
        automation_state.message_count += 1
        automation_state.last_success_time = datetime.now()
        automation_state.last_failure_time = None  # Reset failure time on success
        
        update_task_message_count(task_id, automation_state.message_count)
        update_task_success_time(task_id)
        update_working_cookie_index(task_id, cookie_index)
        
        log_message(f'{process_id}: ✓ Message #{automation_state.message_count} sent successfully with cookie #{cookie_index + 1}', task_id)
        
        # Step 7: Wait for delay period with stop checks
        log_message(f'{process_id}: Waiting {delay}s before next message...', task_id)
        for i in range(delay):
            if check_stop_requested(automation_state, task_id):
                return ('stopped', 'Stop requested during delay')
            time.sleep(1)
        
        return ('success', f'Message sent successfully')
        
    except Exception as e:
        error_msg = str(e)[:150]
        log_message(f'{process_id}: Error in message send cycle: {error_msg}', task_id)
        return ('failed', error_msg)

def send_messages(task_id):
    """
    MAIN AUTOMATION FUNCTION - COMPLETELY REWRITTEN FOR SEQUENTIAL PROCESSING
    Each cookie completes its full send/fail cycle within user delay before next cookie
    """
    driver = None
    try:
        task = get_task_by_id(task_id)
        if not task:
            return

        automation_state = RUNNING_TASKS.get(task_id)
        if not automation_state:
            return

        process_id = task['task_id']
        log_message(f'{process_id}: Starting automation with SEQUENTIAL cookie processing...', task_id)

        driver = setup_browser(task_id)
        TASK_DRIVERS[task_id] = driver

        if check_stop_requested(automation_state, task_id):
            return

        log_message(f'{process_id}: Navigating to Facebook...', task_id)
        driver.get('https://www.facebook.com/')
        time.sleep(8)

        # Parse cookies based on type
        cookies_list = []
        if task['cookie_type'] == 'single':
            cookies_list = [task['cookies']]
        else:
            cookies_list = [c.strip() for c in task['cookies'].split('\n') if c.strip()]

        if not cookies_list or not cookies_list[0]:
            log_message(f'{process_id}: No cookies found!', task_id)
            update_task_status(task_id, False)
            return

        total_cookies = len(cookies_list)
        log_message(f'{process_id}: Loaded {total_cookies} cookie(s) - SEQUENTIAL rotation mode', task_id)

        # Restore state from database
        if task.get('last_success_time'):
            try:
                automation_state.last_success_time = datetime.fromisoformat(task['last_success_time'])
            except:
                automation_state.last_success_time = datetime.now()
        
        if task.get('last_failure_time'):
            automation_state.last_failure_time = task['last_failure_time']
        
        automation_state.cookie_index = task.get('last_working_cookie_index', 0)

        delay = int(task['delay'])
        messages_list = [msg.strip() for msg in task['messages'].split('\n') if msg.strip()]

        if not messages_list:
            messages_list = ['Hello!']

        log_message(f'{process_id}: ═══ INFINITE LOOP STARTED - Will run until manual stop or 6hr failure ═══', task_id)

        # MAIN INFINITE LOOP - Sequential cookie processing
        while automation_state.running and not automation_state.stop_requested:
            
            # Check 6-hour failure condition
            if check_6_hour_continuous_failure(automation_state, task_id):
                log_message(f'{process_id}: AUTO-STOP - All cookies failed for 6 hours continuously', task_id)
                stop_automation_complete(task_id)
                delete_task(task_id)
                break
            
            # Get current cookie
            current_cookie_index = automation_state.message_count % total_cookies
            current_cookie = cookies_list[current_cookie_index]
            
            # CRITICAL: Send ONE message with ONE cookie - complete cycle
            result = send_single_message_with_cookie(
                driver=driver,
                task=task,
                automation_state=automation_state,
                process_id=process_id,
                cookie_string=current_cookie,
                cookie_index=current_cookie_index,
                total_cookies=total_cookies,
                messages_list=messages_list,
                delay=delay
            )
            
            status, message = result
            
            if status == 'stopped':
                log_message(f'{process_id}: Task stopped by user', task_id)
                break
            elif status == 'success':
                # Success - continue to next iteration (next cookie)
                log_message(f'{process_id}: Cookie #{current_cookie_index + 1} cycle completed successfully', task_id)
            elif status == 'failed':
                # Mark failure if this is first failure
                if automation_state.last_failure_time is None:
                    automation_state.last_failure_time = datetime.now().isoformat()
                    update_task_failure_time(task_id)
                    log_message(f'{process_id}: Starting failure timer - will auto-stop if all cookies fail for 6 hours', task_id)
                
                log_message(f'{process_id}: Cookie #{current_cookie_index + 1} failed: {message}', task_id)
                log_message(f'{process_id}: Moving to next cookie in rotation...', task_id)
                
                # Small delay before trying next cookie
                for i in range(5):
                    if check_stop_requested(automation_state, task_id):
                        break
                    time.sleep(1)

        log_message(f'{process_id}: ═══ AUTOMATION STOPPED ═══ Total messages: {automation_state.message_count}', task_id)

    except Exception as e:
        log_message(f'Fatal error: {str(e)[:200]}', task_id)
        update_task_status(task_id, False)
    finally:
        # Cleanup
        if driver:
            try:
                driver.quit()
                log_message('Browser closed', task_id)
            except:
                pass

        if task_id in RUNNING_TASKS:
            del RUNNING_TASKS[task_id]
        if task_id in TASK_DRIVERS:
            del TASK_DRIVERS[task_id]
        if task_id in TASK_THREADS:
            del TASK_THREADS[task_id]

def start_automation(task_id):
    """Start automation for a task"""
    if task_id in RUNNING_TASKS:
        return

    automation_state = AutomationState(task_id)
    automation_state.running = True
    automation_state.stop_requested = False
    RUNNING_TASKS[task_id] = automation_state

    thread = threading.Thread(target=send_messages, args=(task_id,))
    thread.daemon = True
    TASK_THREADS[task_id] = thread
    thread.start()
    
    # Ensure heartbeat is running
    HEARTBEAT_MANAGER.start()

def stop_automation_complete(task_id):
    """
    IMPROVED STOP MECHANISM - Immediately stops everything
    Sets stop flag, terminates thread, closes browser, cleanup everything
    """
    # Set stop flags
    if task_id in RUNNING_TASKS:
        RUNNING_TASKS[task_id].running = False
        RUNNING_TASKS[task_id].stop_requested = True  # NEW: Explicit stop
        log_message(f'STOP signal sent to task {task_id}', task_id)

    # Close browser immediately
    if task_id in TASK_DRIVERS:
        try:
            TASK_DRIVERS[task_id].quit()
            log_message(f'Browser force-closed for task {task_id}', task_id)
        except:
            pass
        del TASK_DRIVERS[task_id]

    # Wait for thread to finish (with timeout)
    if task_id in TASK_THREADS:
        thread = TASK_THREADS[task_id]
        thread.join(timeout=3)  # Wait max 3 seconds
        del TASK_THREADS[task_id]

    # Remove from running tasks
    if task_id in RUNNING_TASKS:
        del RUNNING_TASKS[task_id]

    # Update database
    update_task_status(task_id, False)
    log_message(f'Task {task_id} completely stopped and cleaned up', task_id)

# ==================== STREAMLIT UI ====================

st.set_page_config(
    page_title="ROYAL HEROSE KI MA KE BHOSDE ME E2EE Server",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded"
)

custom_css = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800;900&display=swap');
@import url('https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css');

* {
    font-family: 'Outfit', sans-serif !important;
}

.status-bar {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 12px 20px;
    z-index: 9999;
    box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-weight: 600;
    flex-wrap: wrap;
}

.status-bar > div {
    margin: 4px 8px;
}

@media (max-width: 768px) {
    .status-bar {
        padding: 10px 12px;
        font-size: 0.85rem;
    }
    .status-bar > div {
        margin: 2px 4px;
        font-size: 0.8rem;
    }
}

.stApp {
    padding-top: 70px;
    background: linear-gradient(135deg, #f4f9ff 0%, #e9f3ff 40%, #e1f0ff 100%);
    background-attachment: fixed;
}

@media (max-width: 768px) {
    .stApp {
        padding-top: 90px;
    }
}

.main .block-container {
    background: rgba(255, 255, 255, 0.90);
    border-radius: 28px;
    padding: 40px;
    box-shadow: 0 10px 40px rgba(0,0,0,0.12);
}

@media (max-width: 768px) {
    .main .block-container {
        padding: 20px;
        border-radius: 16px;
    }
}

.main-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border-radius: 25px;
    padding: 50px 25px;
    text-align: center;
    color: white;
    box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
}

@media (max-width: 768px) {
    .main-header {
        padding: 30px 15px;
        border-radius: 15px;
    }
    .main-header h1 {
        font-size: 1.5rem !important;
    }
    .main-header p {
        font-size: 0.9rem !important;
    }
}

.stButton>button {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    font-weight: 700;
    padding: 1rem 2rem;
    border-radius: 14px;
    border: none;
    transition: all 0.3s;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.3);
}

.stButton>button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
}

@media (max-width: 768px) {
    .stButton>button {
        padding: 0.8rem 1.5rem;
        font-size: 0.9rem;
    }
}

.task-card {
    background: white;
    border-radius: 15px;
    padding: 20px;
    margin: 15px 0;
    box-shadow: 0 5px 20px rgba(0,0,0,0.12);
    border-left: 5px solid #667eea;
    transition: all 0.3s;
}

.task-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(0,0,0,0.18);
}

@media (max-width: 768px) {
    .task-card {
        padding: 15px;
        margin: 10px 0;
        border-radius: 10px;
    }
    .task-card h3 {
        font-size: 1.1rem !important;
    }
    .task-card p {
        font-size: 0.85rem !important;
    }
}

.console-output {
    background: #1e293b;
    border-radius: 15px;
    padding: 20px;
    font-family: "Consolas", "Monaco", monospace !important;
    max-height: 400px;
    color: #10b981;
    overflow-y: auto;
    font-size: 0.9rem;
    box-shadow: inset 0 2px 10px rgba(0,0,0,0.3);
}

@media (max-width: 768px) {
    .console-output {
        padding: 12px;
        font-size: 0.75rem;
        max-height: 300px;
        border-radius: 10px;
    }
}

.console-line {
    background: #0f172a;
    padding: 8px;
    border-left: 3px solid #10b981;
    border-radius: 6px;
    margin-bottom: 8px;
    word-wrap: break-word;
}

@media (max-width: 768px) {
    .console-line {
        padding: 6px;
        font-size: 0.7rem;
        margin-bottom: 6px;
    }
}

.footer {
    text-align: center;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 2rem;
    border-radius: 15px;
    margin-top: 3rem;
    box-shadow: 0 8px 25px rgba(102, 126, 234, 0.4);
}

@media (max-width: 768px) {
    .footer {
        padding: 1.5rem;
        margin-top: 2rem;
        border-radius: 10px;
        font-size: 0.85rem;
    }
}

.heartbeat-indicator {
    background: rgba(16, 185, 129, 0.2);
    border: 2px solid #10b981;
    border-radius: 10px;
    padding: 8px 15px;
    display: inline-block;
    animation: pulse 2s ease-in-out infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

/* Mobile responsive tables and columns */
@media (max-width: 768px) {
    .row-widget.stHorizontalBlock {
        flex-direction: column !important;
    }

    div[data-testid="column"] {
        width: 100% !important;
        margin-bottom: 10px;
    }
}

/* Info boxes */
.stAlert {
    border-radius: 12px;
    border-left: 4px solid #667eea;
}
</style>
"""

st.markdown(custom_css, unsafe_allow_html=True)

# Session state initialization with persistence
if 'initialized' not in st.session_state:
    session_data = load_session()
    if session_data:
        st.session_state.logged_in = True
        st.session_state.user_id = session_data['user_id']
        st.session_state.username = session_data['username']
        st.session_state.is_admin = session_data['is_admin']
    else:
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.is_admin = False
    st.session_state.initialized = True
    
    # Start heartbeat on app initialization
    HEARTBEAT_MANAGER.start()

def show_status_bar():
    if st.session_state.logged_in:
        tasks = get_user_tasks(st.session_state.user_id) if not st.session_state.is_admin else get_all_tasks()
        running_tasks = sum(1 for t in tasks if t['is_running'])
        total_messages = sum(t.get('messages_sent', 0) for t in tasks)
        
        heartbeat_status = HEARTBEAT_MANAGER.get_status()

        st.markdown(f"""
        <div class="status-bar">
            <div><i class="fas fa-rocket"></i> <strong>ROYAL LODAROSE KI MA KE BHOSDE ME E2EE Server</strong></div>
            <div><i class="fas fa-tasks"></i> {len(tasks)} Tasks</div>
            <div><i class="fas fa-play-circle"></i> {running_tasks} Running</div>
            <div><i class="fas fa-envelope"></i> {total_messages} Messages</div>
            <div class="heartbeat-indicator"><i class="fas fa-heartbeat"></i> {heartbeat_status}</div>
            <div><i class="fas fa-user"></i> {st.session_state.username}</div>
        </div>
        """, unsafe_allow_html=True)

def login_page():
    st.markdown("""
    <div class="main-header">
        <h1><i class="fas fa-flag"></i> SURYAKANT MADRCHOD DANISH KA 300 RUPAY LEKR BHAGNE WALE GAREEB RKB<i class="fas fa-flag"></i></h1>
        <p>SURYAKANT KI MA KE BHOSDE ME E2EE AUTOMATION </p>
    </div>
    """, unsafe_allow_html=True)

    tab1, tab2 = st.tabs(["🔐 Login", "📝 Sign-up"])

    with tab1:
        st.markdown("### <i class='fas fa-sign-in-alt'></i> WELCOME BACK!", unsafe_allow_html=True)
        username = st.text_input("Username", key="login_username", placeholder="Enter username")
        password = st.text_input("Password", key="login_password", type="password", placeholder="Enter password")

        if st.button("🚀 LOGIN", key="login_btn", use_container_width=True):
            if username and password:
                user_result = verify_user(username, password)
                if user_result[0]:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user_result[0]
                    st.session_state.username = username
                    st.session_state.is_admin = user_result[1]
                    save_session(user_result[0], username, user_result[1])
                    st.success(f"✅ Welcome back, {username.upper()}!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password!")
            else:
                st.warning("⚠️ Please enter both username and password")

    with tab2:
        st.markdown("### <i class='fas fa-user-plus'></i> CREATE ACCOUNT", unsafe_allow_html=True)
        new_username = st.text_input("Username", key="signup_username", placeholder="Choose a username")
        new_password = st.text_input("Password", key="signup_password", type="password", placeholder="Choose a password")
        confirm_password = st.text_input("Confirm Password", key="confirm_password", type="password", placeholder="Confirm password")

        if st.button("✨ CREATE ACCOUNT", key="signup_btn", use_container_width=True):
            if new_username and new_password and confirm_password:
                if new_password == confirm_password:
                    success, message = create_user(new_username, new_password)
                    if success:
                        st.success(f"✅ {message} Please login now!")
                    else:
                        st.error(f"❌ {message}")
                else:
                    st.error("❌ Passwords do not match!")
            else:
                st.warning("⚠️ Please fill all fields")

def user_dashboard():
    show_status_bar()

    st.markdown("""
    <div class="main-header">
        <h1><i class="fas fa-server"></i> SURYAKANT MADRCHOD DANISH KA 300 RUPAY LEKR BHAGNE WALE GAREEB RKB<i class="fas fa-server"></i></h1>
        <p>SURYAKANT KI MA KE BHOSDE ME E2EE AUTOMATION </p>
    </div>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(f'<div style="text-align:center"><i class="fas fa-user-circle" style="font-size:3rem;color:#667eea"></i></div>', unsafe_allow_html=True)
    st.sidebar.markdown(f"### <i class='fas fa-user'></i> {st.session_state.username}", unsafe_allow_html=True)

    if st.sidebar.button("🚪 LOGOUT", use_container_width=True):
        clear_session()
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.is_admin = False
        st.success("✅ Logged out successfully!")
        time.sleep(1)
        st.rerun()

    tab1, tab2, tab3 = st.tabs(["<i class='fas fa-plus-circle'></i> Create Task", 
                                 "<i class='fas fa-list'></i> My Tasks", 
                                 "<i class='fas fa-terminal'></i> Console"])

    with tab1:
        st.markdown("### <i class='fas fa-plus-circle'></i> CREATE NEW TASK", unsafe_allow_html=True)
        st.info("ℹ️ SEQUENTIAL PROCESSING: Each cookie completes its message send/fail cycle within your delay time before moving to next cookie. Runs infinitely until manual stop or 6-hour continuous failure.")

        chat_id = st.text_input("📱 Chat ID (E2EE)", placeholder="e.g., 10000634210631", help="Enter Facebook E2EE chat ID")
        name_prefix = st.text_input("✏️ Name Prefix (Optional)", placeholder="e.g., Happy Birthday", help="Optional prefix to add before each message")
        delay = st.number_input("⏱️ Delay (seconds)", min_value=1, max_value=300, value=30, help="Delay between messages in seconds")

        cookie_type = st.radio("🍪 Cookie Type", ["single", "multiple"], horizontal=True, help="Choose single cookie or multiple cookies for rotation")

        col1, col2 = st.columns(2)

        with col1:
            if cookie_type == "single":
                cookies_input = st.text_area("🍪 Single Cookie", placeholder="Paste cookie here", height=150, help="Paste your Facebook cookie")
            else:
                cookies_file = st.file_uploader("📁 Upload Cookies File (.txt)", type=['txt'], key="cookies_file", help="Upload text file with one cookie per line")
                cookies_input = ""
                if cookies_file:
                    cookies_input = cookies_file.read().decode('utf-8')
                    cookie_count = len([c for c in cookies_input.split('\n') if c.strip()])
                    st.success(f"✅ Loaded {cookie_count} cookies")

        with col2:
            messages_file = st.file_uploader("📁 Upload Messages File (.txt)", type=['txt'], key="messages_file", help="Upload text file with one message per line")
            if messages_file:
                messages_input = messages_file.read().decode('utf-8')
                msg_count = len([m for m in messages_input.split('\n') if m.strip()])
                st.success(f"✅ Loaded {msg_count} messages")
            else:
                messages_input = st.text_area("💬 Messages (one per line)", placeholder="Enter messages", height=150, help="Enter messages, one per line")

        if st.button("🚀 CREATE & START TASK", use_container_width=True):
            if chat_id and cookies_input and messages_input:
                db_task_id, task_id = create_task(
                    st.session_state.user_id,
                    chat_id,
                    name_prefix,
                    delay,
                    cookie_type,
                    cookies_input,
                    messages_input
                )
                start_automation(db_task_id)
                st.success(f"✅ Task '{task_id}' created with sequential cookie processing!")
                time.sleep(1.5)
                st.rerun()
            else:
                st.error("❌ Please fill all required fields (Chat ID, Cookies, Messages)!")

    with tab2:
        st.markdown("### <i class='fas fa-list'></i> MY TASKS", unsafe_allow_html=True)

        tasks = get_user_tasks(st.session_state.user_id)

        if not tasks:
            st.info("📝 No tasks yet. Create your first task!")
        else:
            for task in tasks:
                status_color = '#10b981' if task['is_running'] else '#ef4444'
                status_text = 'RUNNING' if task['is_running'] else 'STOPPED'

                # Calculate time since last success
                time_info = ""
                if task.get('last_success_time'):
                    try:
                        last_success = datetime.fromisoformat(task['last_success_time'])
                        time_since = datetime.now() - last_success
                        hours = int(time_since.total_seconds() // 3600)
                        minutes = int((time_since.total_seconds() % 3600) // 60)
                        time_info = f"<br><span style='color:#10b981'>✅ Last success: {hours}h {minutes}m ago</span>"
                    except:
                        pass
                
                if task.get('last_failure_time'):
                    try:
                        last_failure = datetime.fromisoformat(task['last_failure_time'])
                        time_since = datetime.now() - last_failure
                        hours = int(time_since.total_seconds() // 3600)
                        minutes = int((time_since.total_seconds() % 3600) // 60)
                        remaining_hours = 6 - hours
                        if remaining_hours > 0:
                            time_info += f"<br><span style='color:#f59e0b'>⚠️ Failing for: {hours}h {minutes}m (Auto-stop in {remaining_hours}h)</span>"
                    except:
                        pass

                st.markdown(f"""
                <div class="task-card">
                    <h3><i class="fas fa-tasks"></i> {task['task_id']}</h3>
                    <p><i class="fas fa-comment"></i> Chat: {task['chat_id'][:20]}...</p>
                    <p><i class="fas fa-envelope"></i> Messages: {task['messages_sent']} |
                       <i class="fas fa-clock"></i> Delay: {task['delay']}s |
                       Status: <span style="color:{status_color}">● {status_text}</span>{time_info}</p>
                </div>
                """, unsafe_allow_html=True)

                col1, col2, col3 = st.columns([1, 1, 1])

                with col1:
                    if not task['is_running']:
                        if st.button(f"▶️ Start", key=f"start_{task['id']}", use_container_width=True):
                            update_task_status(task['id'], True)
                            start_automation(task['id'])
                            st.success("✅ Task started!")
                            time.sleep(1)
                            st.rerun()
                    else:
                        if st.button(f"⏹️ Stop", key=f"stop_{task['id']}", use_container_width=True):
                            stop_automation_complete(task['id'])
                            st.warning("⏹️ Task stopped!")
                            time.sleep(1)
                            st.rerun()

                with col2:
                    if st.button(f"📊 Logs", key=f"logs_{task['id']}", use_container_width=True):
                        st.session_state[f'show_logs_{task["id"]}'] = not st.session_state.get(f'show_logs_{task["id"]}', False)
                        st.rerun()

                with col3:
                    if st.button(f"🗑️ Delete", key=f"delete_{task['id']}", use_container_width=True):
                        if task['is_running']:
                            stop_automation_complete(task['id'])
                        delete_task(task['id'])
                        st.success("✅ Task deleted!")
                        time.sleep(1)
                        st.rerun()

                if st.session_state.get(f'show_logs_{task["id"]}', False):
                    logs = get_task_logs(task['id'], limit=30)
                    if logs:
                        logs_html = '<div class="console-output">'
                        for log, timestamp in reversed(logs):
                            logs_html += f'<div class="console-line">{log}</div>'
                        logs_html += '</div>'
                        st.markdown(logs_html, unsafe_allow_html=True)
                    else:
                        st.info("No logs available")

    with tab3:
        st.markdown("### <i class='fas fa-terminal'></i> CONSOLE", unsafe_allow_html=True)

        tasks = get_user_tasks(st.session_state.user_id)

        if tasks:
            task_names = [f"{t['task_id']} - Chat: {t['chat_id'][:15]}..." for t in tasks]
            selected_task_index = st.selectbox("🔍 Select Task", range(len(tasks)), format_func=lambda i: task_names[i])

            if selected_task_index is not None:
                selected_task = tasks[selected_task_index]

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**Task:** {selected_task['task_id']} | **Messages:** {selected_task['messages_sent']} | **Status:** {'🟢 Running' if selected_task['is_running'] else '🔴 Stopped'}")
                with col2:
                    if st.button("🔄 Refresh Logs", use_container_width=True):
                        st.rerun()

                logs = get_task_logs(selected_task['id'], limit=50)

                if logs:
                    logs_html = '<div class="console-output">'
                    for log, timestamp in reversed(logs):
                        logs_html += f'<div class="console-line">{log}</div>'
                    logs_html += '</div>'
                    st.markdown(logs_html, unsafe_allow_html=True)
                else:
                    st.info("📝 No logs yet")
        else:
            st.info("📝 No tasks available")

def admin_dashboard():
    show_status_bar()

    st.markdown("""
    <div class="main-header">
        <h1><i class="fas fa-crown"></i> ADMIN DASHBOARD <i class="fas fa-crown"></i></h1>
        <p>FULL SYSTEM CONTROL</p>
    </div>
    """, unsafe_allow_html=True)

    st.sidebar.markdown(f'<div style="text-align:center"><i class="fas fa-user-shield" style="font-size:3rem;color:#667eea"></i></div>', unsafe_allow_html=True)
    st.sidebar.markdown(f"### <i class='fas fa-crown'></i> ADMIN: {st.session_state.username}", unsafe_allow_html=True)

    if st.sidebar.button("🚪 LOGOUT", use_container_width=True):
        clear_session()
        st.session_state.logged_in = False
        st.session_state.user_id = None
        st.session_state.username = None
        st.session_state.is_admin = False
        st.success("✅ Logged out successfully!")
        time.sleep(1)
        st.rerun()

    st.markdown("### <i class='fas fa-globe'></i> ALL USERS TASKS", unsafe_allow_html=True)

    all_tasks = get_all_tasks()

    if not all_tasks:
        st.info("📝 No tasks in system")
    else:
        for task in all_tasks:
            status_color = '#10b981' if task['is_running'] else '#ef4444'
            status_text = 'RUNNING' if task['is_running'] else 'STOPPED'

            time_info = ""
            if task.get('last_success_time'):
                try:
                    last_success = datetime.fromisoformat(task['last_success_time'])
                    time_since = datetime.now() - last_success
                    hours = int(time_since.total_seconds() // 3600)
                    minutes = int((time_since.total_seconds() % 3600) // 60)
                    time_info = f"<br><span style='color:#10b981'>Last success: {hours}h {minutes}m ago</span>"
                except:
                    pass

            st.markdown(f"""
            <div class="task-card">
                <h3><i class="fas fa-tasks"></i> {task['task_id']}</h3>
                <p><i class="fas fa-user"></i> User: {task['username']} |
                   <i class="fas fa-comment"></i> Chat: {task['chat_id'][:15]}... |
                   <i class="fas fa-envelope"></i> Messages: {task['messages_sent']}</p>
                <p>Status: <span style="color:{status_color}">● {status_text}</span>{time_info}</p>
            </div>
            """, unsafe_allow_html=True)

            col1, col2 = st.columns([1, 1])

            with col1:
                if task['is_running']:
                    if st.button(f"⏹️ STOP", key=f"admin_stop_{task['id']}", use_container_width=True):
                        stop_automation_complete(task['id'])
                        st.warning("⏹️ Task stopped by admin!")
                        time.sleep(1)
                        st.rerun()

            with col2:
                if st.button(f"🗑️ DELETE", key=f"admin_delete_{task['id']}", use_container_width=True):
                    if task['is_running']:
                        stop_automation_complete(task['id'])
                    delete_task(task['id'])
                    st.success("✅ Task deleted by admin!")
                    time.sleep(1)
                    st.rerun()

def show_footer():
    st.markdown("""
    <div class="footer">
        <p><i class="fas fa-code"></i> Developer: Darkstar Boii Sahiil</p>
        <p><i class="fas fa-users"></i> Team: Darkstar</p>
        <p><a href="#" style="color:white; text-decoration:none;"><i class="fas fa-file-contract"></i> Terms of Condition</a></p>
        <p style="margin-top:10px;"><i class="fas fa-heartbeat"></i> Heartbeat Active - Server Sleep Prevention Enabled</p>
        <p style="margin-top:5px;font-size:0.9rem;"><i class="fas fa-sync-alt"></i> Sequential Cookie Processing - Each cookie completes send/fail cycle before next</p>
    </div>
    """, unsafe_allow_html=True)

# Main App Logic
if not st.session_state.logged_in:
    login_page()
else:
    if st.session_state.is_admin:
        admin_dashboard()
    else:
        user_dashboard()

show_footer()
