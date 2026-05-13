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

# Render ssilkasi (Buni Render'dan ro'yxatdan o'tib URL olgach, shu yerga yozing!)
# Masalan: "https://mening-botim.onrender.com/"
RENDER_URL = "https://mathbot-uame.onrender.com"
# Botga ko'proq foydalanuvchiga bir vaqtda xizmat ko'rsatishiga ruxsat berish (num_threads=10)
bot = telebot.TeleBot(TOKEN, num_threads=10)
user_states = {}

# Veb-serverni yaratish (Webhook uchun)
app = Flask(__name__)

# --- BOT MENYUSINI O'RNATISH ---
def set_bot_menu():
    commands = [
        BotCommand("start", "Botni qayta ishga tushirish"),
        BotCommand("test", "Test ishlash (Test kodini kiritish)"),
        BotCommand("testlarim", "Mening natijalarim va tarix"),
        BotCommand("edit", "Ism-familiyamni o'zgartirish"),
        BotCommand("info", "Bot haqida ma'lumot")
    ]
    bot.set_my_commands(commands)

set_bot_menu()

# --- BAZA BILAN ISHLASH ---
def execute_query(query, params=()):
    try:
        with sqlite3.connect('testlar_bazasi.db', check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
    except Exception as e:
        print(f"Baza xatoligi (execute): {e}")

def fetch_query(query, params=(), fetchone=False):
    try:
        with sqlite3.connect('testlar_bazasi.db', check_same_thread=False) as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            if fetchone:
                return cursor.fetchone()
            return cursor.fetchall()
    except Exception as e:
        print(f"Baza xatoligi (fetch): {e}")
        return None

# --- TEZLIKNI OSHIRISH (WAL rejimi bazani qotishdan asraydi) ---
execute_query('PRAGMA journal_mode=WAL;')
execute_query('PRAGMA synchronous=NORMAL;')

# Jadvallarni yaratish va yangilash
execute_query('CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, name TEXT)')
# Testlar bazasiga type (pdf/html) va link (html havolasi uchun) qo'shildi
execute_query('CREATE TABLE IF NOT EXISTS tests (code TEXT PRIMARY KEY, answers TEXT, deadline TEXT, type TEXT DEFAULT "pdf", link TEXT)')
execute_query('CREATE TABLE IF NOT EXISTS results (user_id INTEGER, name TEXT, code TEXT, score INTEGER, total INTEGER, analysis_text TEXT)')

# Eski bazalarni xatosiz yangilash
try: execute_query('ALTER TABLE tests ADD COLUMN deadline TEXT')
except: pass
try: execute_query('ALTER TABLE tests ADD COLUMN type TEXT DEFAULT "pdf"')
except: pass
try: execute_query('ALTER TABLE tests ADD COLUMN link TEXT')
except: pass
try: execute_query('ALTER TABLE results ADD COLUMN analysis_text TEXT')
except: pass

# --- PROGRESS BAR GENERATOR (Gamifikatsiya) ---
def get_progress_bar(score, total):
    if total == 0: return ""
    percent = score / total
    filled = int(percent * 5)
    empty = 5 - filled
    return "🟩" * filled + "⬜" * empty + f" ({int(percent * 100)}%)"

# --- MENYULAR (Klaviatura) ---
def get_main_menu(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    # Barcha uchun ochiq tugmalar
    markup.add(
        types.KeyboardButton("📝 Test ishlash"),
        types.KeyboardButton("📊 Natijalarim")
    )
    # Faqat admin uchun ko'rinadigan tugmalar
    if int(chat_id) == ADMIN_ID:
        markup.add(
            types.KeyboardButton("➕ Yangi test qo'shish"),
            types.KeyboardButton("➕ HTML test qo'shish")
        )
        markup.add(types.KeyboardButton("📊 Natijalarni olish"))
    return markup

def back_markup():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("🔙 Ortga qaytish"))
    return markup

# --- COMMANDS VA ASOSIY BO'LIMLAR ---

@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_states[message.chat.id] = {}
    user = fetch_query("SELECT name FROM users WHERE user_id=?", (message.chat.id,), fetchone=True)

    if user:
        bot.send_message(message.chat.id, f"Qaytganingizdan xursandmiz, {user[0]}!\nKerakli bo'limni tanlang:", reply_markup=get_main_menu(message.chat.id))
    else:
        msg = bot.send_message(message.chat.id, "Xush kelibsiz! Iltimos, ism va familiyangizni kiriting:")
        bot.register_next_step_handler(msg, register_user)

def register_user(message):
    name = message.text.strip()
    execute_query("REPLACE INTO users (user_id, name) VALUES (?, ?)", (message.chat.id, name))
    bot.send_message(message.chat.id, f"Ajoyib, {name}! Endi test ishlashingiz mumkin.", reply_markup=get_main_menu(message.chat.id))

@bot.message_handler(func=lambda message: message.text == "🔙 Ortga qaytish")
def back_to_home(message):
    user_states[message.chat.id] = {}
    bot.send_message(message.chat.id, "Bosh menyu:", reply_markup=get_main_menu(message.chat.id))

@bot.message_handler(commands=['edit'])
def edit_cmd(message):
    msg = bot.send_message(message.chat.id, "Yangi ism va familiyangizni kiriting:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, update_name)

def update_name(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    name = message.text.strip()
    execute_query("REPLACE INTO users (user_id, name) VALUES (?, ?)", (message.chat.id, name))
    bot.send_message(message.chat.id, f"Ismingiz '{name}' ga muvaffaqiyatli o'zgartirildi! ✅", reply_markup=get_main_menu(message.chat.id))

@bot.message_handler(commands=['info'])
def info_cmd(message):
    text = ("ℹ️ **Bot haqida ma'lumot:**\n\n"
            "Bu bot orqali siz matematika fanidan testlarni ishlashingiz va natijalarni tahlil qilishingiz mumkin.\n\n"
            "Kanalimiz: [Eshonqulov Math](https://t.me/eshonqulov_math)")
    bot.send_message(message.chat.id, text, parse_mode='Markdown', disable_web_page_preview=True)

# --- O'QUVCHI: BARCHA NATIJALARIM (Tarixni ko'rish) ---
@bot.message_handler(commands=['testlarim'])
@bot.message_handler(func=lambda message: message.text == "📊 Natijalarim")
def my_all_results_cmd(message):
    # Optimallashtirilgan so'rov: Faqat kerakli ma'lumotlarni tortib olamiz
    rows = fetch_query("SELECT code, score, total FROM results WHERE user_id=? ORDER BY ROWID DESC", (message.chat.id,))

    if not rows:
        bot.send_message(message.chat.id, "❌ Siz hali test ishlamadingiz.", reply_markup=get_main_menu(message.chat.id))
        return

    text = "📊 **Sizning barcha test natijalaringiz:**\n\n"
    for i, r in enumerate(rows, 1):
        text += f"*{i}.* 🔢 **Test kodi:** {r[0]} ➖ **Natija:** {r[1]}/{r[2]}\n"

    # Xabar haddan tashqari uzun bo'lib ketsa, Telegram qoidasiga ko'ra bo'lib jo'natamiz
    if len(text) > 4000:
        for x in range(0, len(text), 4000):
            bot.send_message(message.chat.id, text[x:x+4000], parse_mode='Markdown')
    else:
        bot.send_message(message.chat.id, text, parse_mode='Markdown')

# --- O'QUVCHI: TEST ISHLASH ---
@bot.message_handler(commands=['test'])
@bot.message_handler(func=lambda message: message.text == "📝 Test ishlash")
def student_start(message):
    user = fetch_query("SELECT name FROM users WHERE user_id=?", (message.chat.id,), fetchone=True)
    if not user:
        return start_cmd(message) # Agar ro'yxatdan o'tmagan bo'lsa

    user_states[message.chat.id] = {'action': 'student_solve', 'name': user[0]}
    msg = bot.send_message(message.chat.id, "Ustozingiz bergan test kodini kiriting:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, student_open_app)

def student_open_app(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)

    try:
        code = message.text.strip()

        # Limit tekshirish: 1 ta testni faqat 2 marta ishlash mumkin
        count_data = fetch_query("SELECT COUNT(*) FROM results WHERE user_id=? AND code=?", (message.chat.id, code), fetchone=True)
        if count_data and count_data[0] >= 2:
            bot.send_message(message.chat.id, f"⚠️ Siz bu testni allaqachon 2 marta ishlagansiz!\nTest ishlash limiti tugagan.", reply_markup=get_main_menu(message.chat.id))
            return

        row = fetch_query("SELECT answers, deadline, type, link FROM tests WHERE code=?", (code,), fetchone=True)

        if row:
            answers = row[0]
            deadline = row[1] if row[1] else '0'
            test_type = row[2]
            html_link = row[3]

            # Vaqtni tekshirish
            if deadline != '0':
                deadline_dt = datetime.strptime(deadline, "%Y-%m-%d %H:%M")
                if datetime.now() > deadline_dt:
                    bot.send_message(message.chat.id, f"⛔️ Kechirasiz, ushbu test yopilgan.\n(Muddat: {deadline} gacha edi)", reply_markup=get_main_menu(message.chat.id))
                    return

            user_states[message.chat.id].update({'code': code, 'correct': answers, 'type': test_type})

            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            if test_type == 'html':
                markup.add(types.KeyboardButton(text="📱 Interaktiv testni ochish", web_app=types.WebAppInfo(url=html_link)))
            else:
                markup.add(types.KeyboardButton(text="📱 Javoblarni belgilash", web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?count={len(answers)}")))

            markup.add(types.KeyboardButton("🔙 Ortga qaytish"))
            bot.send_message(message.chat.id, f"✅ Test kodi: {code}\nTestni boshlash uchun pastdagi tugmani bosing:", reply_markup=markup)
        else:
            msg = bot.send_message(message.chat.id, "❌ Kod xato yoki bunday test yo'q!\nIltimos, qaytadan to'g'ri test kodini kiriting:", reply_markup=back_markup())
            bot.register_next_step_handler(msg, student_open_app)

    except Exception as e:
        print(f"Xato (student_open_app): {e}")
        bot.send_message(message.chat.id, "Kutilmagan xatolik yuz berdi.", reply_markup=get_main_menu(message.chat.id))

# --- WEB APP MA'LUMOTINI QABUL QILISH ---
@bot.message_handler(content_types=['web_app_data'])
def web_data_handler(message):
    try:
        state = user_states.get(message.chat.id, {})
        received_data = message.web_app_data.data

        # Admin PDF test saqlayotgan bo'lsa
        if state.get('action') == 'admin_save':
            deadline = state.get('deadline', '0')
            received_data = received_data.lower()
            execute_query("REPLACE INTO tests (code, answers, deadline, type, link) VALUES (?, ?, ?, ?, ?)",
                          (state['code'], received_data, deadline, 'pdf', ''))
            bot.send_message(message.chat.id, "✅ PDF Test bazaga saqlandi!", reply_markup=get_main_menu(message.chat.id))

        # O'quvchi test (PDF yoki HTML) ishlagan bo'lsa
        elif state.get('action') == 'student_solve':
            test_type = state.get('type', 'pdf')

            if test_type == 'pdf':
                correct = state.get('correct', '').lower()
                received_data = received_data.lower()
                if not correct: return
                score = sum(1 for s, c in zip(received_data, correct) if s == c)
                total = len(correct)

                # Tahlil
                analysis = []
                for i, (s, c) in enumerate(zip(received_data, correct), 1):
                    analysis.append(f"{i}✅" if s == c else f"{i}❌({c.upper()})")
                grid_analysis = "\n".join([" ".join(analysis[i:i+5]) for i in range(0, len(analysis), 5)])

            elif test_type == 'html':
                parts = received_data.split('|')
                if len(parts) >= 2:
                    score = int(parts[0])
                    total = int(parts[1])
                    grid_analysis = parts[2] if len(parts) > 2 else "(Batafsil tahlil interaktiv saytda ko'rsatildi)"
                else:
                    score, total, grid_analysis = 0, 0, "Xatolik: Tahlil ma'lumotlari kelmadi."

            p_bar = get_progress_bar(score, total)
            res_text = (f"👤 **O'quvchi:** {state['name']}\n"
                        f"🔢 **Test kodi:** {state['code']}\n"
                        f"📊 **Natija:** {score}/{total} {p_bar}\n\n"
                        f"**Tahlil:**\n{grid_analysis}")

            # Natijani bazaga saqlash
            execute_query("INSERT INTO results (user_id, name, code, score, total, analysis_text) VALUES (?, ?, ?, ?, ?, ?)",
                          (message.chat.id, state['name'], state['code'], score, total, res_text))

            bot.send_message(message.chat.id, res_text, parse_mode='Markdown', reply_markup=get_main_menu(message.chat.id))
            bot.send_message(ADMIN_ID, f"🔔 **Yangi natija:**\n\n{res_text}", parse_mode='Markdown')

            user_states[message.chat.id] = {}

    except Exception as e:
        print(f"Xato (web_data_handler): {e}")
        traceback.print_exc()

# --- ADMIN: YANGI PDF TEST QO'SHISH ---
@bot.message_handler(func=lambda message: message.text == "➕ Yangi test qo'shish")
def admin_add_start(message):
    if int(message.chat.id) != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "Test kodi va savollar sonini kiriting (Masalan: 701 30):", reply_markup=back_markup())
    bot.register_next_step_handler(msg, admin_prepare_app)

def admin_prepare_app(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    try:
        parts = message.text.split()
        t_code, t_count = parts[0], int(parts[1])
        user_states[message.chat.id] = {'action': 'admin_save_deadline', 'code': t_code, 'count': t_count}
        msg = bot.send_message(message.chat.id, "Test qachon yopilishini kiriting.\nFormat: YYYY-MM-DD HH:MM (masalan: 2026-05-05 20:00)\nCheksiz bo'lishi uchun 0 deb yuboring.", reply_markup=back_markup())
        bot.register_next_step_handler(msg, admin_get_deadline)
    except Exception:
        msg = bot.send_message(message.chat.id, "Xato format! Kod va savollar sonini to'g'ri kiriting (Masalan: 701 30):")
        bot.register_next_step_handler(msg, admin_prepare_app)

def admin_get_deadline(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    deadline = message.text.strip()

    if deadline != '0':
        try: datetime.strptime(deadline, "%Y-%m-%d %H:%M")
        except ValueError:
            msg = bot.send_message(message.chat.id, "Vaqt formati xato! YYYY-MM-DD HH:MM shaklida yozing yoki '0' yuboring:")
            bot.register_next_step_handler(msg, admin_get_deadline)
            return

    state = user_states.get(message.chat.id, {})
    state['deadline'] = deadline
    state['action'] = 'admin_save'

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton(text="🛠 Javoblarni kiritish", web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?count={state['count']}")))
    markup.add(types.KeyboardButton("🔙 Ortga qaytish"))

    bot.send_message(message.chat.id, f"Kodi: {state['code']}\nJavoblarni kiritish uchun pastdagi tugmani bosing:", reply_markup=markup)

# --- ADMIN: YANGI HTML TEST QO'SHISH ---
@bot.message_handler(func=lambda message: message.text == "➕ HTML test qo'shish")
def admin_add_html(message):
    if int(message.chat.id) != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "Test kodi va Netlify havolasini (Link) kiriting.\nMasalan: `901 https://interaktiv-test.netlify.app`", parse_mode='Markdown', reply_markup=back_markup())
    bot.register_next_step_handler(msg, admin_html_deadline)

def admin_html_deadline(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    try:
        parts = message.text.split(maxsplit=1)
        t_code, t_link = parts[0], parts[1].strip()
        user_states[message.chat.id] = {'code': t_code, 'link': t_link}
        msg = bot.send_message(message.chat.id, "Test qachon yopilishini kiriting.\nFormat: YYYY-MM-DD HH:MM\nCheksiz bo'lishi uchun 0 deb yuboring.", reply_markup=back_markup())
        bot.register_next_step_handler(msg, admin_html_save)
    except Exception:
        msg = bot.send_message(message.chat.id, "Xato! Format: Kod Link (orasi ochiq qoldirilsin)")
        bot.register_next_step_handler(msg, admin_html_deadline)

def admin_html_save(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    deadline = message.text.strip()
    if deadline != '0':
        try: datetime.strptime(deadline, "%Y-%m-%d %H:%M")
        except ValueError:
            msg = bot.send_message(message.chat.id, "Vaqt formati xato! YYYY-MM-DD HH:MM:")
            bot.register_next_step_handler(msg, admin_html_save)
            return

    state = user_states.get(message.chat.id, {})
    execute_query("REPLACE INTO tests (code, answers, deadline, type, link) VALUES (?, ?, ?, ?, ?)",
                  (state['code'], '', deadline, 'html', state['link']))

    bot.send_message(message.chat.id, f"✅ **HTML Test bazaga saqlandi!**\nKod: {state['code']}\nLink: {state['link']}", parse_mode='Markdown', reply_markup=get_main_menu(message.chat.id))

# --- ADMIN: BARCHA NATIJALAR ---
@bot.message_handler(func=lambda message: message.text == "📊 Natijalarni olish")
def show_results_cmd(message):
    if int(message.chat.id) != ADMIN_ID: return
    msg = bot.send_message(message.chat.id, "Test kodini kiriting:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, process_results)

def process_results(message):
    if message.text == "🔙 Ortga qaytish": return back_to_home(message)
    try:
        rows = fetch_query("SELECT name, score, total FROM results WHERE code=? ORDER BY score DESC", (message.text.strip(),))
        if rows:
            txt = f"📊 **{message.text}** testi natijalari:\n\n" + "\n".join([f"{i}. {r[0]} - {r[1]}/{r[2]}" for i, r in enumerate(rows, 1)])
            bot.send_message(message.chat.id, txt, parse_mode='Markdown', reply_markup=get_main_menu(message.chat.id))
        else:
            bot.send_message(message.chat.id, "Topilmadi yoki test kodi xato.", reply_markup=get_main_menu(message.chat.id))
    except Exception as e:
        bot.send_message(message.chat.id, "Xatolik yuz berdi.", reply_markup=get_main_menu(message.chat.id))

# --- WEBHOOK YO'LAKLARI (Render uchun qo'shilgan qism) ---
@app.route('/' + TOKEN, methods=['POST'])
def getMessage():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return "!", 200

@app.route("/")
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=RENDER_URL + TOKEN)
    return "Bot muvaffaqiyatli ishga tushdi va Webhook ulandi!", 200

if __name__ == "__main__":
    # Flask serverni ishga tushirish (Render avtomatik o'qiydigan port)
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))
