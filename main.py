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
RENDER_URL = "https://mathbot-uame.onrender.com"

# Botni yaratish (num_threads va threaded=True kechikishni oldini oladi)
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=20)
user_states = {}

app = Flask(__name__)

# --- BAZA BILAN ISHLASH (Yaxshilangan ulanish) ---
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
        print(f"Baza xatoligi (execute): {e}")

def fetch_query(query, params=(), fetchone=False):
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetchone:
                res = cursor.fetchone()
                return list(res) if res else None
            return cursor.fetchall()
    except Exception as e:
        print(f"Baza xatoligi (fetch): {e}")
        return None

# Baza sozlamalari
execute_query('PRAGMA journal_mode=WAL;')
execute_query('PRAGMA synchronous=NORMAL;')
execute_query('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT)')
execute_query('CREATE TABLE IF NOT EXISTS tests (code TEXT PRIMARY KEY, answers TEXT, deadline TEXT, type TEXT DEFAULT "pdf", link TEXT)')
execute_query('CREATE TABLE IF NOT EXISTS results (user_id INTEGER, name TEXT, code TEXT, score INTEGER, total INTEGER, analysis_text TEXT)')

# --- BOT KOMANDALARI ---
def set_bot_menu():
    commands = [
        BotCommand("start", "Qayta ishga tushirish"),
        BotCommand("test", "Test ishlash"),
        BotCommand("testlarim", "Natijalarim"),
        BotCommand("edit", "Ismni tahrirlash"),
        BotCommand("info", "Ma'lumot")
    ]
    bot.set_my_commands(commands)

set_bot_menu()

# --- INTERFEYS FUNKSIYALARI ---
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

def get_progress_bar(score, total):
    if total == 0: return ""
    percent = score / total
    filled = int(percent * 5)
    return "🟩" * filled + "⬜" * (5 - filled) + f" ({int(percent * 100)}%)"

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_states[message.chat.id] = {}
    user = fetch_query("SELECT name FROM users WHERE user_id=?", (message.chat.id,), fetchone=True)
    if user:
        bot.send_message(message.chat.id, f"Salom, {user[0]}!", reply_markup=get_main_menu(message.chat.id))
    else:
        msg = bot.send_message(message.chat.id, "Xush kelibsiz! Ism-familiyangizni kiriting:")
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
def my_results(message):
    rows = fetch_query("SELECT code, score, total FROM results WHERE user_id=? ORDER BY ROWID DESC LIMIT 20", (message.chat.id,))
    if not rows:
        bot.send_message(message.chat.id, "Hali test ishlamadingiz.")
        return
    text = "📊 **Natijalaringiz:**\n\n"
    for r in rows:
        text += f"🔹 Kod: `{r[0]}` | Natija: `{r[1]}/{r[2]}`\n"
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "📝 Test ishlash" or m.text == "/test")
def student_start(message):
    user = fetch_query("SELECT name FROM users WHERE user_id=?", (message.chat.id,), fetchone=True)
    if not user: return start_cmd(message)
    user_states[message.chat.id] = {'action': 'student_solve', 'name': user[0]}
    msg = bot.send_message(message.chat.id, "Test kodini kiriting:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, student_open_app)

def student_open_app(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    code = message.text.strip()
    row = fetch_query("SELECT answers, deadline, type, link FROM tests WHERE code=?", (code,), fetchone=True)
    if row:
        user_states[message.chat.id].update({'code': code, 'correct': row[0], 'type': row[2]})
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn_url = row[3] if row[2] == 'html' else f"{WEB_APP_URL}?count={len(row[0])}"
        markup.add(types.KeyboardButton(text="📱 Testni boshlash", web_app=types.WebAppInfo(url=btn_url)))
        markup.add(types.KeyboardButton("🔙 Ortga qaytish"))
        bot.send_message(message.chat.id, f"✅ Test kodi: {code}", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ Kod topilmadi.")

@bot.message_handler(content_types=['web_app_data'])
def web_data_handler(message):
    try:
        state = user_states.get(message.chat.id, {})
        received_data = message.web_app_data.data
        
        if state.get('action') == 'admin_save':
            execute_query("REPLACE INTO tests (code, answers, deadline, type, link) VALUES (?, ?, ?, ?, ?)",
                          (state['code'], received_data.lower(), state.get('deadline', '0'), 'pdf', ''))
            bot.send_message(message.chat.id, "✅ Test saqlandi!", reply_markup=get_main_menu(message.chat.id))
        
        elif state.get('action') == 'student_solve':
            # Natijani hisoblash qismi (PDF uchun)
            correct = state.get('correct', '').lower()
            received_data = received_data.lower()
            score = sum(1 for s, c in zip(received_data, correct) if s == c)
            total = len(correct)
            
            res_text = f"👤 {state['name']}\n🔢 Kod: {state['code']}\n📊 Natija: {score}/{total}"
            execute_query("INSERT INTO results (user_id, name, code, score, total, analysis_text) VALUES (?, ?, ?, ?, ?, ?)",
                          (message.chat.id, state['name'], state['code'], score, total, res_text))
            
            bot.send_message(message.chat.id, res_text, reply_markup=get_main_menu(message.chat.id))
            bot.send_message(ADMIN_ID, f"🔔 Yangi natija:\n{res_text}")
    except Exception as e:
        print(f"WebData Error: {e}")

# --- ADMIN FUNKSIYALAR (Qisqartirilgan) ---
@bot.message_handler(func=lambda message: message.text == "➕ Yangi test qo'shish")
def admin_add_start(message):
    if message.chat.id != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "Kod va savol soni (Masalan: 701 30):", reply_markup=back_markup())
    bot.register_next_step_handler(msg, admin_prepare_app)

def admin_prepare_app(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    try:
        parts = message.text.split()
        user_states[message.chat.id] = {'action': 'admin_save', 'code': parts[0], 'count': int(parts[1])}
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add(types.KeyboardButton(text="🛠 Javoblarni kiritish", web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?count={parts[1]}")))
        bot.send_message(message.chat.id, "Tugmani bosing:", reply_markup=markup)
    except: bot.send_message(message.chat.id, "Xato format.")

# --- WEBHOOK QISMI ---
@app.route('/' + TOKEN, methods=['POST'])
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
    bot.set_webhook(url=f"{RENDER_URL}/{TOKEN}")
    return "Bot ishlamoqda!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
            
