import requests
import telebot
import time
import json
import re
import glob
import importlib
import random
import os
import threading
from datetime import datetime, timedelta
from telebot import types
from concurrent.futures import ThreadPoolExecutor, as_completed

# ===================================================================
#                           CONFIGURATION
# ===================================================================

TOKEN = '8982677734:AAEGiexTzR3gP4Hjt4xA-s9gK4WG5aIFAnM'
ADMIN_ID = 5831292144
RESULTS_DIR = "results"

if not os.path.exists(RESULTS_DIR):
    os.makedirs(RESULTS_DIR)

BANNED_FILE = 'banned.json'
PROXY_FILE = 'proxies.json'

# ===================================================================
#                          JSON HANDLERS
# ===================================================================

def load_json(file, default):
    try:
        if os.path.exists(file):
            with open(file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default
    except:
        return default

def save_json(file, data):
    try:
        with open(file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except:
        return False

# ===================================================================
#                           BAN SYSTEM
# ===================================================================

def load_banned():
    return load_json(BANNED_FILE, {})

def save_banned(data):
    save_json(BANNED_FILE, data)

def is_user_banned(user_id):
    banned = load_banned()
    user_id_str = str(user_id)
    if user_id_str in banned:
        banned_until = banned[user_id_str].get('banned_until')
        if banned_until:
            try:
                until = datetime.strptime(banned_until, '%Y-%m-%d %H:%M:%S')
                if datetime.now() < until:
                    return True, until
                else:
                    del banned[user_id_str]
                    save_banned(banned)
                    return False, None
            except:
                return True, None
        else:
            return True, None
    return False, None

def ban_user(user_id, hours, reason="Abuse detected"):
    user_id_str = str(user_id)
    banned = load_banned()
    
    if hours == 0:
        banned_until = None
        duration_text = "Permanent"
    else:
        banned_until = (datetime.now() + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
        duration_text = f"{hours} hours"
    
    banned[user_id_str] = {
        "banned_until": banned_until,
        "reason": reason,
        "banned_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "banned_by": ADMIN_ID
    }
    save_banned(banned)
    return duration_text

def unban_user(user_id):
    user_id_str = str(user_id)
    banned = load_banned()
    if user_id_str in banned:
        del banned[user_id_str]
        save_banned(banned)
        return True
    return False

# ===================================================================
#                          PROXY SYSTEM
# ===================================================================

def load_proxies():
    return load_json(PROXY_FILE, {})

def save_proxies(data):
    save_json(PROXY_FILE, data)

def get_user_proxy(user_id):
    proxies = load_proxies()
    user_id_str = str(user_id)
    if user_id_str in proxies:
        return proxies[user_id_str].get('proxy')
    return None

def set_user_proxy(user_id, proxy_url):
    proxies = load_proxies()
    user_id_str = str(user_id)
    proxies[user_id_str] = {
        "proxy": proxy_url,
        "set_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    save_proxies(proxies)

def remove_user_proxy(user_id):
    proxies = load_proxies()
    user_id_str = str(user_id)
    if user_id_str in proxies:
        del proxies[user_id_str]
        save_proxies(proxies)
        return True
    return False

# ===================================================================
#                        AUTHORIZATION CHECK
# ===================================================================

def is_authorized(user_id):
    return str(user_id) == str(ADMIN_ID)

def is_authorized_to_check(message):
    user_id = message.chat.id
    
    if str(user_id) == str(ADMIN_ID):
        return True, "admin"
    
    banned, until = is_user_banned(user_id)
    if banned:
        if until:
            return False, f"banned_until_{until}"
        return False, "banned_permanent"
    
    return False, "not_admin"

# ===================================================================
#                       SMART CC EXTRACTION
# ===================================================================

def extract_cc_from_text(text):
    if not text:
        return []
    
    results = []
    seen = set()
    
    # Pattern 1: Standard pipe/slash/colon format
    pattern1 = r'(\d{15,16})\s*[|\|:;/]\s*(\d{1,2})\s*[|\|:;/]\s*(\d{2,4})\s*[|\|:;/]\s*(\d{3,4})'
    matches = re.findall(pattern1, text, re.IGNORECASE)
    for match in matches:
        cc_num = match[0]
        month = match[1].zfill(2)
        year_raw = match[2]
        cvv = match[3].zfill(3)
        
        if len(year_raw) == 4:
            year = year_raw[2:4]
        else:
            year = year_raw.zfill(2)
        
        if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
            formatted = f"{cc_num}|{month}|{year}|{cvv}"
            if formatted not in seen:
                seen.add(formatted)
                results.append(formatted)
    
    # Pattern 2: Space separated
    if not results:
        pattern2 = r'(\d{15,16})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})'
        matches = re.findall(pattern2, text, re.IGNORECASE)
        for match in matches:
            cc_num = match[0]
            month = match[1].zfill(2)
            year_raw = match[2]
            cvv = match[3].zfill(3)
            
            if len(year_raw) == 4:
                year = year_raw[2:4]
            else:
                year = year_raw.zfill(2)
            
            if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
                formatted = f"{cc_num}|{month}|{year}|{cvv}"
                if formatted not in seen:
                    seen.add(formatted)
                    results.append(formatted)
    
    # Pattern 3: Dash separated
    if not results:
        text_no_dash = re.sub(r'(\d{4})-(\d{4})-(\d{4})-(\d{4})', r'\1\2\3\4', text)
        if text_no_dash != text:
            results = extract_cc_from_text(text_no_dash)
    
    return results

# ===================================================================
#                           GATE MODULES
# ===================================================================

GATE_MODULES = []
for gate_file in glob.glob('gate*.py'):
    module_name = gate_file.replace('.py', '')
    try:
        module = importlib.import_module(module_name)
        GATE_MODULES.append(module)
    except:
        pass

if not GATE_MODULES:
    class DummyGate:
        @staticmethod
        def Tele(cc, proxies=None):
            responses = [
                '{"status": "success", "message": "Payment successful"}',
                '{"status": "error", "error": {"message": "Insufficient funds"}}',
                '{"status": "error", "error": {"message": "Do not honor"}}'
            ]
            return random.choice(responses)
    GATE_MODULES.append(DummyGate)

# ===================================================================
#                          BOT INITIALIZATION
# ===================================================================

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
active_checks = {}
active_checks_lock = threading.Lock()

# ===================================================================
#                          HELPER FUNCTIONS
# ===================================================================

def is_card_expired(cc):
    try:
        parts = cc.split("|")
        if len(parts) >= 3:
            exp_month = parts[1].strip()
            exp_year_raw = parts[2].strip()
            if len(exp_year_raw) == 2:
                exp_year = 2000 + int(exp_year_raw)
            else:
                exp_year = int(exp_year_raw)
            exp_month_int = int(exp_month)
            current_date = datetime.now()
            current_year = current_date.year
            current_month = current_date.month
            if exp_year < current_year:
                return True
            elif exp_year == current_year and exp_month_int < current_month:
                return True
    except:
        pass
    return False

def get_bin_info(cc):
    """Get BIN information from API with retry"""
    try:
        for attempt in range(3):
            try:
                response = requests.get(
                    f'https://bins.antipublic.cc/bins/{cc[:6]}',
                    timeout=5
                )
                if response.status_code == 200:
                    data = response.json()
                    country = data.get('country_name', 'Unknown')
                    flag = data.get('country_flag', '')
                    bank = data.get('bank', 'Unknown')
                    brand = data.get('brand', 'Unknown')
                    type_card = data.get('type', 'Unknown')
                    level = data.get('level', '')
                    
                    bin_text = f"{bank} - {country} ({flag})" if flag else f"{bank} - {country}"
                    card_type = f"{brand} - {type_card} ({level})" if level else f"{brand} - {type_card}"
                    
                    return bin_text, card_type
            except:
                if attempt < 2:
                    time.sleep(1)
                    continue
    except:
        pass
    return "Unknown", "Unknown"

def check_cc_with_gates(cc, user_id=None):
    proxy = get_user_proxy(user_id)
    
    gate_name = "N/A"
    last = "Error"
    
    if GATE_MODULES:
        random_gate = random.choice(GATE_MODULES)
        gate_name = random_gate.__name__
        try:
            if proxy:
                proxies = {'http': proxy, 'https': proxy}
                last_raw = str(random_gate.Tele(cc, proxies=proxies))
            else:
                last_raw = str(random_gate.Tele(cc))
            
            if '"message":' in last_raw:
                try:
                    data = json.loads(last_raw)
                    if 'error' in data:
                        last = data['error'].get('message', last_raw)
                    else:
                        last = data.get('message', last_raw)
                except:
                    last = last_raw
            else:
                last = last_raw if last_raw != "0" else "Site Rejected"
        except Exception as e:
            last = f"Gateway Error: {str(e)[:50]}"
    
    return gate_name, last

def determine_status(last):
    last_lower = last.lower()
    
    hit_k = ['thank', 'success":true', 'thank-you', 'successful', 'confirmed', 'paid', 'transaction_id', 'approved', 'captured']
    low_k = ['insufficient funds', 'low funds', 'money', 'balance']
    three_k = ['authenticate', '3d_secure', 'verification required', 'challenge_required', 'client_secret', 'redirect']
    
    if any(k in last_lower for k in three_k):
        return "cvv", "💎 <b>CVV LIVE</b> 💎"
    elif any(k in last_lower for k in hit_k) and '"success":false' not in last_lower:
        return "charged", "✅ <b>PAYMENT SUCCESSFUL</b> ✅"
    elif any(k in last_lower for k in low_k):
        return "low", "💰 <b>LOW FUNDS</b> 💰"
    elif 'security code is incorrect' in last_lower:
        return "ccn", "⚠️ <b>CCN ONLY</b> ⚠️"
    else:
        return "declined", "❌ <b>DECLINED</b> ❌"

# ===================================================================
#                          UI MESSAGE BUILDERS
# ===================================================================

def build_single_check_response(cc, gate_name, status_text, bin_text, card_type, taken_time, user_name):
    return f"""
<b>Cc:</b>  <code>{cc}</code>
<b>Gate:</b> {gate_name}
<b>State:</b> {status_text}
<b>Bin:</b> {bin_text}
<b>{card_type}</b>

---------–----------------------------------
<b>Taken:</b> {taken_time}s
<b>Check By:</b> {user_name}
"""

def build_checking_line(cc):
    return f"""
<b>Cc:</b>  <code>{cc}</code>
<b>Gate:</b> <i>Checking...</i>
<b>State:</b> <i>Checking...</i>
<b>Bin:</b> <i>Checking...</i>
---------–---------------------------------"""

def build_waiting_line(cc):
    return f"""
<b>Cc:</b>  <code>{cc}</code>
<i>Waiting ...........🚴‍♂️🚴‍♀️</i>
---------–---------------------------------"""

def build_completed_line(cc, gate_name, status_text, bin_text, card_type, taken_time):
    return f"""
<b>Cc:</b>  <code>{cc}</code>
<b>Gate:</b> {gate_name}
<b>State:</b> {status_text}
<b>Bin:</b> {bin_text}
<b>{card_type}</b>
---------–---------------------------------"""

# ===================================================================
#                          SAVE RESULTS
# ===================================================================

def save_result_to_file(cc, status_type, bank, country, gate_name):
    try:
        file_path_hit = os.path.join(RESULTS_DIR, "hit.txt")
        file_path_low = os.path.join(RESULTS_DIR, "low.txt")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{cc}|{bank}|{country}|{gate_name}|{timestamp}\n"
        
        if status_type == "hit":
            with open(file_path_hit, 'a', encoding='utf-8') as f:
                f.write(line)
        elif status_type == "low":
            with open(file_path_low, 'a', encoding='utf-8') as f:
                f.write(line)
    except:
        pass

# ===================================================================
#                          MASS CHECK SESSION
# ===================================================================

class MassCheckSession:
    def __init__(self, chat_id, msg_id, ccs, user_id, user_name):
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.ccs = ccs
        self.user_id = user_id
        self.user_name = user_name
        self.results = []
        self.current_index = 0
        self.total = len(ccs)
        self.start_time = time.time()
        self.stop_event = False
        self.results_lock = threading.Lock()
        self.edit_lock = threading.Lock()

def update_mass_check_ui(session):
    if session.stop_event:
        return
    
    with session.edit_lock:
        lines = []
        for i, cc in enumerate(session.ccs):
            if i < session.current_index and i < len(session.results):
                r = session.results[i]
                lines.append(build_completed_line(
                    r['cc'], r['gate'], r['status_text'],
                    r['bin_text'], r['card_type'], r['taken']
                ))
            elif i == session.current_index:
                lines.append(build_checking_line(cc))
            else:
                lines.append(build_waiting_line(cc))
        
        taken_total = round(time.time() - session.start_time, 1)
        
        full_text = "".join(lines) + f"""
<b>Taken:</b> {taken_total}s
<b>Check By:</b> {session.user_name}"""
        
        try:
            bot.edit_message_text(full_text, chat_id=session.chat_id, message_id=session.msg_id, parse_mode="HTML")
        except Exception as e:
            if "message is not modified" not in str(e):
                pass

def process_cc_for_mass(session, index, cc):
    if session.stop_event:
        return
    
    # Rate limit - prevent flood
    time.sleep(random.uniform(0.3, 0.5))
    
    start_time = time.time()
    gate_name, last = check_cc_with_gates(cc, session.user_id)
    taken_time = round(time.time() - start_time, 1)
    status_key, status_text = determine_status(last)
    bin_text, card_type = get_bin_info(cc)
    
    with session.results_lock:
        session.results.append({
            'cc': cc,
            'gate': gate_name,
            'status_text': status_text,
            'bin_text': bin_text,
            'card_type': card_type,
            'taken': taken_time,
            'status_key': status_key
        })
        session.current_index += 1
    
    update_mass_check_ui(session)
    
    if status_key in ["charged", "cvv", "low"]:
        save_result_to_file(cc, "hit" if status_key == "charged" else "low", 
                          bin_text.split("-")[0].strip(), 
                          bin_text.split("-")[-1].strip() if "-" in bin_text else "Unknown", 
                          gate_name)

# ===================================================================
#                          COMMAND: START
# ===================================================================

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.chat.id
    
    if not is_authorized(user_id):
        bot.reply_to(message, "❌ <b>Access denied.</b>\nThis bot is private.", parse_mode="HTML")
        return
    
    banned, until = is_user_banned(user_id)
    if banned:
        if until:
            bot.reply_to(message, f"⛔ <b>BANNED UNTIL</b>\n{until}", parse_mode="HTML")
        else:
            bot.reply_to(message, "⛔ <b>PERMANENTLY BANNED</b>", parse_mode="HTML")
        return
    
    welcome_msg = f"""
━━━━━━━━━━━━━━━━━━━━━━━━
🚀 <b>GOOD HQ BOT</b> 🚀
━━━━━━━━━━━━━━━━━━━━━━━━

👑 <b>ADMIN MODE</b> (Private)

━━━━━━━━━━━━━━━━━━━━━━━━
🎮 <b>COMMANDS:</b>

• Send .txt file - Mass check
• <code>/v</code> or <code>.v</code> - Live mass check
• <code>/v1</code> - Single card check
• <code>/id</code> - Get user ID
• <code>/proxy</code> - Set your proxy
• <code>/stats</code> - Bot statistics
• <code>/ban</code> - Ban user
• <code>/unban</code> - Unban user
• <code>/bannedlist</code> - List banned users

━━━━━━━━━━━━━━━━━━━━━━━━
"""
    bot.reply_to(message, welcome_msg, parse_mode="HTML")

# ===================================================================
#                          COMMAND: SINGLE CHECK
# ===================================================================

@bot.message_handler(commands=["v1"])
def single_check(message):
    user_id = message.chat.id
    
    if not is_authorized(user_id):
        bot.reply_to(message, "❌ <b>Access denied.</b>", parse_mode="HTML")
        return
    
    auth_result, auth_msg = is_authorized_to_check(message)
    if not auth_result:
        if auth_msg.startswith("banned_until_"):
            until = auth_msg.replace("banned_until_", "")
            bot.reply_to(message, f"⛔ <b>BANNED UNTIL</b>\n{until}", parse_mode="HTML")
        else:
            bot.reply_to(message, "❌ <b>Access denied!</b>", parse_mode="HTML")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Usage: <code>/v1 cc|mm|yy|cvv</code>\nExample: <code>/v1 4744770173288524|12|26|213</code>", parse_mode="HTML")
        return
    
    ccs = extract_cc_from_text(args[1])
    if not ccs:
        bot.reply_to(message, "❌ <b>No valid CC found!</b>", parse_mode="HTML")
        return
    
    cc = ccs[0]
    
    status_msg = bot.reply_to(message, "🔄 <b>Checking...</b>", parse_mode="HTML")
    
    bin_text, card_type = get_bin_info(cc)
    start_time = time.time()
    gate_name, last = check_cc_with_gates(cc, user_id)
    taken_time = round(time.time() - start_time, 1)
    status_key, status_text = determine_status(last)
    
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    response = build_single_check_response(cc, gate_name, status_text, bin_text, card_type, taken_time, user_name)
    bot.edit_message_text(response, chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="HTML")
    
    if status_key in ["charged", "cvv", "low"]:
        save_result_to_file(cc, "hit" if status_key == "charged" else "low", 
                          bin_text.split("-")[0].strip(), 
                          bin_text.split("-")[-1].strip() if "-" in bin_text else "Unknown", 
                          gate_name)

# ===================================================================
#                          COMMAND: MASS CHECK
# ===================================================================

@bot.message_handler(commands=["v", ".v"])
def mass_check(message):
    user_id = message.chat.id
    
    if not is_authorized(user_id):
        bot.reply_to(message, "❌ <b>Access denied.</b>", parse_mode="HTML")
        return
    
    auth_result, auth_msg = is_authorized_to_check(message)
    if not auth_result:
        if auth_msg.startswith("banned_until_"):
            until = auth_msg.replace("banned_until_", "")
            bot.reply_to(message, f"⛔ <b>BANNED UNTIL</b>\n{until}", parse_mode="HTML")
        else:
            bot.reply_to(message, "❌ <b>Access denied!</b>", parse_mode="HTML")
        return
    
    ccs = []
    
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption or ""
        ccs = extract_cc_from_text(replied_text)
    
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and not ccs:
        ccs = extract_cc_from_text(args[1])
    
    if not ccs:
        bot.reply_to(message, "❌ <b>No valid CC found!</b>\nUsage: <code>/v cc|mm|yy|cvv</code>", parse_mode="HTML")
        return
    
    # Filter expired cards
    valid_ccs = []
    for cc in ccs:
        if not is_card_expired(cc):
            valid_ccs.append(cc)
    
    if not valid_ccs:
        bot.reply_to(message, "⚠️ <b>All cards are expired!</b>", parse_mode="HTML")
        return
    
    user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    # Build initial waiting UI
    waiting_lines = []
    for cc in valid_ccs:
        waiting_lines.append(build_waiting_line(cc))
    
    initial_text = "".join(waiting_lines) + f"""
<b>Taken:</b> 0s
<b>Check By:</b> {user_name}"""
    
    status_msg = bot.reply_to(message, initial_text, parse_mode="HTML")
    
    session = MassCheckSession(
        chat_id=message.chat.id,
        msg_id=status_msg.message_id,
        ccs=valid_ccs,
        user_id=user_id,
        user_name=user_name
    )
    
    with active_checks_lock:
        active_checks[user_id] = session
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = []
        for i, cc in enumerate(valid_ccs):
            if session.stop_event:
                for f in futures:
                    f.cancel()
                break
            futures.append(executor.submit(process_cc_for_mass, session, i, cc))
            time.sleep(0.1)
        
        for f in futures:
            try:
                f.result(timeout=30)
            except:
                pass
    
    with active_checks_lock:
        active_checks.pop(user_id, None)

# ===================================================================
#                          COMMAND: GET ID
# ===================================================================

@bot.message_handler(commands=["id"])
def get_id(message):
    user_id = message.chat.id
    
    if not is_authorized(user_id):
        bot.reply_to(message, "❌ <b>Access denied.</b>", parse_mode="HTML")
        return
    
    user = message.from_user
    
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        first_name = target.first_name or ""
        username = f"@{target.username}" if target.username else "No username"
        target_id = target.id
        
        response = f"""
━━━━━━━━━━━━━━━━━━━━━━━━
🆔 <b>REPLIED USER ID INFO</b>
━━━━━━━━━━━━━━━━━━━━━━━━

👤 <b>Username:</b> {username}
🆔 <b>User ID:</b> <code>{target_id}</code>
📅 <b>Name:</b> {first_name}

━━━━━━━━━━━━━━━━━━━━━━━━
"""
    else:
        first_name = user.first_name or ""
        username = f"@{user.username}" if user.username else "No username"
        
        response = f"""
━━━━━━━━━━━━━━━━━━━━━━━━
🆔 <b>YOUR ID INFO</b>
━━━━━━━━━━━━━━━━━━━━━━━━

👤 <b>Username:</b> {username}
🆔 <b>User ID:</b> <code>{message.chat.id}</code>
📅 <b>Name:</b> {first_name}

━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    bot.reply_to(message, response, parse_mode="HTML")

# ===================================================================
#                          COMMAND: PROXY
# ===================================================================

@bot.message_handler(commands=["proxy"])
def set_proxy(message):
    user_id = message.chat.id
    
    if not is_authorized(user_id):
        bot.reply_to(message, "❌ <b>Access denied.</b>", parse_mode="HTML")
        return
    
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        current = get_user_proxy(user_id)
        if current:
            bot.reply_to(message, f"🔗 <b>Your proxy:</b>\n<code>{current}</code>\n\nUse <code>/proxy off</code> to disable", parse_mode="HTML")
        else:
            bot.reply_to(message, "<b>📝 Proxy Commands:</b>\n<code>/proxy socks5://user:pass@ip:port</code>\n<code>/proxy off</code>\n<code>/proxy</code> - to view", parse_mode="HTML")
        return
    
    proxy_input = args[1].strip()
    
    if proxy_input.lower() == "off":
        if remove_user_proxy(user_id):
            bot.reply_to(message, "✅ <b>Proxy disabled!</b> Using direct connection.", parse_mode="HTML")
        else:
            bot.reply_to(message, "❌ <b>No active proxy to disable.</b>", parse_mode="HTML")
        return
    
    if not re.match(r'(socks5|http|https)://', proxy_input):
        bot.reply_to(message, "❌ <b>Invalid format!</b>\nUse: <code>socks5://user:pass@ip:port</code>", parse_mode="HTML")
        return
    
    set_user_proxy(user_id, proxy_input)
    bot.reply_to(message, f"✅ <b>Proxy set!</b>\n<code>{proxy_input}</code>\n\nUse <code>/proxy off</code> to disable", parse_mode="HTML")

# ===================================================================
#                          CALLBACK: STOP
# ===================================================================

@bot.callback_query_handler(func=lambda call: call.data == 'stop')
def stop_check(call):
    user_id = call.message.chat.id
    with active_checks_lock:
        if user_id in active_checks:
            active_checks[user_id].stop_event = True
            bot.answer_callback_query(call.id, "🛑 Stopping...")
        else:
            bot.answer_callback_query(call.id, "❌ No active check")

# ===================================================================
#                          FILE HANDLER
# ===================================================================

@bot.message_handler(content_types=["document"])
def handle_file(message):
    user_id = message.chat.id
    
    if not is_authorized(user_id):
        bot.reply_to(message, "❌ <b>Access denied.</b>", parse_mode="HTML")
        return
    
    auth_result, auth_msg = is_authorized_to_check(message)
    if not auth_result:
        if auth_msg.startswith("banned_until_"):
            until = auth_msg.replace("banned_until_", "")
            bot.reply_to(message, f"⛔ <b>BANNED UNTIL</b>\n{until}", parse_mode="HTML")
        else:
            bot.reply_to(message, "❌ <b>Access denied!</b>", parse_mode="HTML")
        return
    
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        content = downloaded.decode('utf-8', errors='ignore')
        
        ccs = extract_cc_from_text(content)
        
        if not ccs:
            bot.reply_to(message, "❌ <b>No valid CC found in file!</b>", parse_mode="HTML")
            return
        
        # Filter expired cards
        valid_ccs = []
        for cc in ccs:
            if not is_card_expired(cc):
                valid_ccs.append(cc)
        
        if not valid_ccs:
            bot.reply_to(message, "⚠️ <b>All cards are expired!</b>", parse_mode="HTML")
            return
        
        status_msg = bot.reply_to(message, f"🔄 <b>Checking {len(valid_ccs)} cards... (Showing hits only)</b>", parse_mode="HTML")
        
        user_name = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
        hits = []
        
        for i, cc in enumerate(valid_ccs):
            start_time = time.time()
            gate_name, last = check_cc_with_gates(cc, user_id)
            taken_time = round(time.time() - start_time, 1)
            status_key, status_text = determine_status(last)
            
            if status_key in ["charged", "cvv", "low"]:
                bin_text, card_type = get_bin_info(cc)
                result = build_single_check_response(
                    cc, gate_name, status_text, bin_text, card_type, 
                    taken_time, user_name
                )
                hits.append(result)
                
                save_result_to_file(cc, "hit" if status_key == "charged" else "low", 
                                  bin_text.split("-")[0].strip(), 
                                  bin_text.split("-")[-1].strip() if "-" in bin_text else "Unknown", 
                                  gate_name)
            
            # Rate limit
            if (i + 1) % 5 == 0:
                time.sleep(0.2)
            
            # Update progress
            if (i + 1) % 10 == 0 or (i + 1) == len(valid_ccs):
                try:
                    bot.edit_message_text(f"🔄 <b>Progress:</b> {i+1}/{len(valid_ccs)} | <b>Hits:</b> {len(hits)}", 
                                         chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="HTML")
                except:
                    pass
        
        if hits:
            final_msg = f"✅ <b>FILE CHECK COMPLETE</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n<b>Total Hits:</b> {len(hits)}\n\n" + "\n━━━━━━━━━━━━━━━━━━━━━━━━\n".join(hits)
            if len(final_msg) > 4000:
                for j in range(0, len(final_msg), 4000):
                    bot.send_message(message.chat.id, final_msg[j:j+4000], parse_mode="HTML")
            else:
                bot.edit_message_text(final_msg, chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="HTML")
        else:
            bot.edit_message_text(f"✅ <b>CHECK COMPLETE!</b>\nCards: {len(valid_ccs)}\nHits: 0", 
                                 chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="HTML")
    
    except Exception as e:
        bot.reply_to(message, f"❌ <b>Error:</b> {str(e)[:100]}", parse_mode="HTML")

# ===================================================================
#                          ADMIN COMMANDS
# ===================================================================

@bot.message_handler(commands=["ban"])
def ban_user_cmd(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: <code>/ban [user_id] [hours]</code>\nExample: <code>/ban 5831292144 24</code>\nUse 0 for permanent", parse_mode="HTML")
        return
    
    target_id = args[1]
    hours = int(args[2]) if len(args) > 2 else 24
    reason = " ".join(args[3:]) if len(args) > 3 else "Violation of rules"
    
    duration = ban_user(target_id, hours, reason)
    bot.reply_to(message, f"✅ <b>User {target_id} banned for {duration}</b>", parse_mode="HTML")
    
    try:
        bot.send_message(target_id, f"⛔ <b>BANNED</b>\nReason: {reason}\nDuration: {duration}", parse_mode="HTML")
    except:
        pass

@bot.message_handler(commands=["unban"])
def unban_user_cmd(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: <code>/unban [user_id]</code>", parse_mode="HTML")
        return
    
    target_id = args[1]
    if unban_user(target_id):
        bot.reply_to(message, f"✅ <b>User {target_id} unbanned!</b>", parse_mode="HTML")
    else:
        bot.reply_to(message, f"❌ <b>User {target_id} is not banned.</b>", parse_mode="HTML")

@bot.message_handler(commands=["bannedlist"])
def banned_list(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    banned = load_banned()
    if not banned:
        bot.reply_to(message, "📋 <b>No banned users.</b>", parse_mode="HTML")
        return
    
    text = "📋 <b>BANNED USERS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for uid, info in banned.items():
        until = info.get('banned_until', 'Permanent')
        text += f"👤 <b>ID:</b> {uid}\n⏰ <b>Until:</b> {until}\n📝 <b>Reason:</b> {info.get('reason', 'Unknown')}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    bot.reply_to(message, text[:4000], parse_mode="HTML")

@bot.message_handler(commands=["stats"])
def stats(message):
    if str(message.chat.id) != str(ADMIN_ID):
        return
    
    banned = load_banned()
    total_banned = len(banned)
    
    hit_count = 0
    low_count = 0
    try:
        hit_file = os.path.join(RESULTS_DIR, "hit.txt")
        low_file = os.path.join(RESULTS_DIR, "low.txt")
        if os.path.exists(hit_file):
            with open(hit_file, 'r') as f:
                hit_count = sum(1 for _ in f)
        if os.path.exists(low_file):
            with open(low_file, 'r') as f:
                low_count = sum(1 for _ in f)
    except:
        pass
    
    bot.reply_to(message, f"""
📊 <b>BOT STATISTICS</b>
━━━━━━━━━━━━━━━━━━━━━━━━
👑 <b>Admin ID:</b> <code>{ADMIN_ID}</code>
⛔ <b>Banned:</b> {total_banned}
⚙️ <b>Active Gates:</b> {len(GATE_MODULES)}
📈 <b>Total Hits:</b> {hit_count}
💰 <b>Low Funds:</b> {low_count}
━━━━━━━━━━━━━━━━━━━━━━━━
""", parse_mode="HTML")

# ===================================================================
#                              MAIN
# ===================================================================

if __name__ == "__main__":
    print("=" * 40)
    print("🤖 GOOD HQ BOT STARTED (ADMIN ONLY - FIXED)")
    print("=" * 40)
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"⚙️ Gates Loaded: {len(GATE_MODULES)}")
    print(f"📁 Results Dir: {RESULTS_DIR}")
    print(f"🔒 Mode: Private (Admin Only)")
    print("=" * 40)
    print("✅ Bot is running...")
    print("=" * 40)
    
    bot.delete_webhook()
    bot.infinity_polling()
