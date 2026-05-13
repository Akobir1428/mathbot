import os
import telebot
from telebot import types
from telebot.types import BotCommand
import sqlite3
import traceback
from datetime import datetime
from flask import Flask, request

# --- SOZLAMALAR ---
TOKEN = '8505975357:AAEtUiLlhjg7joD-iJN2JPqj0fKmKyIYpw0'
ADMIN_ID = 5541008041
WEB_APP_URL = "https://eshoonqulov-math-testbot.netlify.app/"
RENDER_URL = "https://mathbot-uame.onrender.com" # Oxirida / kerak emas, pastda o'zi to'g'rilanadi

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=20)
user_states = {}
app = Flask(__name__)

# --- BAZA BILAN ISHLASH ---
def get_db_connection():
    conn = sqlite3.connect('testlar_bazasi.db', check_same_thread=False, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def execute_query(query, params=()):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
    except Exception as e:
        print(f"Baza xatoligi: {e}")

def fetch_query(query, params=(), fetchone=False):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetchone:
                res = cursor.fetchone()
                return tuple(res) if res else None 
            return [tuple(row) for row in cursor.fetchall()]
    except Exception as e:
        return None

execute_query('PRAGMA journal_mode=WAL;')
execute_query('PRAGMA synchronous=NORMAL;')
execute_query('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT)')
execute_query('CREATE TABLE IF NOT EXISTS tests (code TEXT PRIMARY KEY, answers TEXT, deadline TEXT, type TEXT DEFAULT "pdf", link TEXT)')
execute_query('CREATE TABLE IF NOT EXISTS results (user_id INTEGER, name TEXT, code TEXT, score INTEGER, total INTEGER, analysis_text TEXT)')

def get_progress_bar(score, total):
    if total == 0: return ""
    percent = score / total
    filled = int(percent * 5)
    return "🟩" * filled + "⬜" * (5 - filled) + f" ({int(percent * 100)}%)"

def set_bot_menu():
    commands = [
        BotCommand("start", "Botni qayta ishga tushirish"),
        BotCommand("test", "Test ishlash"),
        BotCommand("testlarim", "Natijalarim"),
        BotCommand("edit", "Ismni o'zgartirish"),
        BotCommand("info", "Bot haqida")
    ]
    bot.set_my_commands(commands)

set_bot_menu()

def get_main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(types.KeyboardButton("📝 Test ishlash"), types.KeyboardButton("📊 Natijalarim"))
    if int(chat_id) == ADMIN_ID:
        markup.add(types.KeyboardButton("➕ Yangi test qo'shish"), types.KeyboardButton("➕ HTML test qo'shish"))
        markup.add(types.KeyboardButton("📊 Natijalarni olish"))
    return markup

def back_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔙 Ortga qaytish"))
    return markup

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_states[message.chat.id] = {}
    user = fetch_query("SELECT name FROM users WHERE user_id=?", (message.chat.id,), fetchone=True)
    if user:
        bot.send_message(message.chat.id, f"Salom, {user[0]}!", reply_markup=get_main_menu(message.chat.id))
    else:
        msg = bot.send_message(message.chat.id, "Xush kelibsiz! Ism va familiyangizni kiriting:")
        bot.register_next_step_handler(msg, register_user)

def register_user(message):
    name = message.text.strip()
    execute_query("REPLACE INTO users (user_id, name) VALUES (?, ?)", (message.chat.id, name))
    bot.send_message(message.chat.id, f"Tayyor, {name}!", reply_markup=get_main_menu(message.chat.id))

@bot.message_handler(func=lambda message: message.text == "🔙 Ortga qaytish")
def back_to_home(message):
    user_states[message.chat.id] = {}
    bot.send_message(message.chat.id, "Asosiy menyu:", reply_markup=get_main_menu(message.chat.id))

@bot.message_handler(commands=['testlarim'])
@bot.message_handler(func=lambda message: message.text == "📊 Natijalarim")
def my_all_results_cmd(message):
    rows = fetch_query("SELECT code, score, total FROM results WHERE user_id=? ORDER BY ROWID DESC LIMIT 20", (message.chat.id,))
    if not rows:
        bot.send_message(message.chat.id, "❌ Siz hali test ishlamadingiz.", reply_markup=get_main_menu(message.chat.id))
        return
    text = "📊 **Sizning test natijalaringiz:**\n\n"
    for i, r in enumerate(rows, 1):
        text += f"*{i}.* 🔢 **Kodi:** `{r[0]}` ➖ **Natija:** `{r[1]}/{r[2]}`\n"
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['test'])
@bot.message_handler(func=lambda message: message.text == "📝 Test ishlash")
def student_start(message):
    user = fetch_query("SELECT name FROM users WHERE user_id=?", (message.chat.id,), fetchone=True)
    if not user: return start_cmd(message)
    user_states[message.chat.id] = {'action': 'student_solve', 'name': user[0]}
    msg = bot.send_message(message.chat.id, "Test kodini kiriting:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, student_open_app)

def student_open_app(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    try:
        code = message.text.strip()
        count_data = fetch_query("SELECT COUNT(*) FROM results WHERE user_id=? AND code=?", (message.chat.id, code), fetchone=True)
        if count_data and count_data[0] >= 2:
            bot.send_message(message.chat.id, "⚠️ Siz bu testni allaqachon 2 marta ishlagansiz!", reply_markup=get_main_menu(message.chat.id))
            return
        row = fetch_query("SELECT answers, deadline, type, link FROM tests WHERE code=?", (code,), fetchone=True)
        if row:
            answers, deadline, test_type, html_link = row[0], (row[1] if row[1] else '0'), row[2], row[3]
            if deadline != '0' and datetime.now() > datetime.strptime(deadline, "%Y-%m-%d %H:%M"):
                bot.send_message(message.chat.id, f"⛔️ Test yopilgan. (Muddat: {deadline})", reply_markup=get_main_menu(message.chat.id))
                return
            user_states[message.chat.id].update({'code': code, 'correct': answers, 'type': test_type})
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            if test_type == 'html': markup.add(types.KeyboardButton(text="📱 Interaktiv test", web_app=types.WebAppInfo(url=html_link)))
            else: markup.add(types.KeyboardButton(text="📱 Javoblarni belgilash", web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?count={len(answers)}")))
            markup.add(types.KeyboardButton("🔙 Ortga qaytish"))
            bot.send_message(message.chat.id, f"✅ Test kodi: {code}\nBoshlash uchun bosing:", reply_markup=markup)
        else:
            msg = bot.send_message(message.chat.id, "❌ Kod xato! Qaytadan kiriting:", reply_markup=back_markup())
            bot.register_next_step_handler(msg, student_open_app)
    except: bot.send_message(message.chat.id, "Xatolik yuz berdi.", reply_markup=get_main_menu(message.chat.id))

@bot.message_handler(content_types=['web_app_data'])
def web_data_handler(message):
    try:
        state = user_states.get(message.chat.id, {})
        received_data = message.web_app_data.data
        if state.get('action') == 'admin_save':
            execute_query("REPLACE INTO tests (code, answers, deadline, type, link) VALUES (?, ?, ?, ?, ?)",
                          (state['code'], received_data.lower(), state.get('deadline', '0'), 'pdf', ''))
            bot.send_message(message.chat.id, "✅ Test bazaga saqlandi!", reply_markup=get_main_menu(message.chat.id))
        elif state.get('action') == 'student_solve':
            test_type = state.get('type', 'pdf')
            if test_type == 'pdf':
                correct = state.get('correct', '').lower()
                received_data = received_data.lower()
                if not correct: return
                score = sum(1 for s, c in zip(received_data, correct) if s == c)
                total = len(correct)
                analysis = [f"{i}✅" if s == c else f"{i}❌({c.upper()})" for i, (s, c) in enumerate(zip(received_data, correct), 1)]
                grid_analysis = "\n".join([" ".join(analysis[i:i+5]) for i in range(0, len(analysis), 5)])
            elif test_type == 'html':
                parts = received_data.split('|')
                if len(parts) >= 2:
                    score, total = int(parts[0]), int(parts[1])
                    grid_analysis = parts[2] if len(parts) > 2 else "(Saytda ko'rsatildi)"
                else: score, total, grid_analysis = 0, 0, "Xatolik"
            
            p_bar = get_progress_bar(score, total)
            res_text = f"👤 {state['name']}\n🔢 Kod: `{state['code']}`\n📊 Natija: {score}/{total} {p_bar}\n\n**Tahlil:**\n{grid_analysis}"
            execute_query("INSERT INTO results (user_id, name, code, score, total, analysis_text) VALUES (?, ?, ?, ?, ?, ?)",
                          (message.chat.id, state['name'], state['code'], score, total, res_text))
            bot.send_message(message.chat.id, res_text, parse_mode='Markdown', reply_markup=get_main_menu(message.chat.id))
            bot.send_message(ADMIN_ID, f"🔔 **Yangi natija:**\n\n{res_text}", parse_mode='Markdown')
            user_states[message.chat.id] = {}
    except: pass

@bot.message_handler(func=lambda message: message.text == "➕ Yangi test qo'shish")
def admin_add_start(message):
    if int(message.chat.id) != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "Kod va savol soni (Mas: 701 30):", reply_markup=back_markup())
    bot.register_next_step_handler(msg, admin_prepare_app)

def admin_prepare_app(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    try:
        parts = message.text.split()
        user_states[message.chat.id] = {'action': 'admin_save_deadline', 'code': parts[0], 'count': int(parts[1])}
        msg = bot.send_message(message.chat.id, "Yopilish vaqti (YYYY-MM-DD HH:MM) yoki 0:", reply_markup=back_markup())
        bot.register_next_step_handler(msg, admin_get_deadline)
    except:
        msg = bot.send_message(message.chat.id, "Xato format! Boshidan kiriting:")
        bot.register_next_step_handler(msg, admin_prepare_app)

def admin_get_deadline(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    state = user_states.get(message.chat.id, {})
    state['deadline'], state['action'] = message.text.strip(), 'admin_save'
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton(text="🛠 Javoblarni kiritish", web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?count={state['count']}")))
    markup.add(types.KeyboardButton("🔙 Ortga qaytish"))
    bot.send_message(message.chat.id, f"Kodi: {state['code']}\nTugmani bosing:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "➕ HTML test qo'shish")
def admin_add_html(message):
    if int(message.chat.id) != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "Kod va Link (Mas: 901 https://...):", reply_markup=back_markup())
    bot.register_next_step_handler(msg, admin_html_deadline)

def admin_html_deadline(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    try:
        parts = message.text.split(maxsplit=1)
        user_states[message.chat.id] = {'code': parts[0], 'link': parts[1].strip()}
        msg = bot.send_message(message.chat.id, "Yopilish vaqti yoki 0:", reply_markup=back_markup())
        bot.register_next_step_handler(msg, admin_html_save)
    except: pass

def admin_html_save(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    state = user_states.get(message.chat.id, {})
    execute_query("REPLACE INTO tests (code, answers, deadline, type, link) VALUES (?, ?, ?, ?, ?)",
                  (state['code'], '', message.text.strip(), 'html', state['link']))
    bot.send_message(message.chat.id, f"✅ HTML Test saqlandi!", reply_markup=get_main_menu(message.chat.id))

@bot.message_handler(func=lambda message: message.text == "📊 Natijalarni olish")
def show_results_cmd(message):
    if int(message.chat.id) != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "Test kodini kiriting:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, process_results)

def process_results(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    rows = fetch_query("SELECT name, score, total FROM results WHERE code=? ORDER BY score DESC", (message.text.strip(),))
    if rows:
        txt = f"📊 **{message.text}** natijalari:\n\n" + "\n".join([f"{i}. {r[0]} - {r[1]}/{r[2]}" for i, r in enumerate(rows, 1)])
        bot.send_message(message.chat.id, txt, parse_mode='Markdown', reply_markup=get_main_menu(message.chat.id))
    else: bot.send_message(message.chat.id, "Topilmadi.", reply_markup=get_main_menu(message.chat.id))

# --- WEBHOOK YO'LAKLARI (Xatosiz ulanish mexanizmi) ---
@app.route(f"/{TOKEN}", methods=['POST'])
def getMessage():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '', 403

@app.route("/")
def webhook():
    bot.remove_webhook()
    # Ssilka va tokenni aniq formatlash (hatolik yuz bermaydi)
    webhook_url = f"{RENDER_URL}/{TOKEN}"
    bot.set_webhook(url=webhook_url)
    return "Bot muvaffaqiyatli ishga tushdi va tezkor rejimda ishlamoqda!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))