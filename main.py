import os
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from contextlib import contextmanager

import telebot
from telebot import types
from telebot.types import BotCommand
from flask import Flask, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

TOKEN       = os.environ.get("BOT_TOKEN", "8505975357:AAEtUiLlhjg7joD-iJN2JPqj0fKmKyIYpw0")
SUPER_ADMIN = int(os.environ.get("ADMIN_ID", "5541008041"))
WEB_APP_URL = os.environ.get("WEB_APP_URL", "https://eshoonqulov-math-testbot.netlify.app/")
_domain     = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
RENDER_URL  = "https://mathbot-uame.onrender.com"
DB_PATH     = os.environ.get("DB_PATH", "testlar_bazasi.db")
PORT        = int(os.environ.get("PORT", 5000))

app = Flask(__name__)
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=20)

_states_lock = threading.Lock()
_user_states: dict = {}

# O'zbekiston vaqtini olish uchun yordamchi funksiya (UTC+5)
def get_uz_now():
    return datetime.utcnow() + timedelta(hours=5)

def get_state(chat_id):
    with _states_lock:
        return _user_states.get(chat_id, {})

def set_state(chat_id, data):
    with _states_lock:
        _user_states[chat_id] = data

def clear_state(chat_id):
    with _states_lock:
        _user_states.pop(chat_id, None)

def update_state(chat_id, **kwargs):
    with _states_lock:
        _user_states.setdefault(chat_id, {}).update(kwargs)

_db_lock = threading.Lock()

@contextmanager
def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def db_exec(query, params=()):
    try:
        with _db_lock, db_conn() as conn:
            conn.execute(query, params)
    except Exception as e:
        log.error("DB exec xato: %s", e)

def db_fetch(query, params=(), one=False):
    try:
        with db_conn() as conn:
            cur = conn.execute(query, params)
            if one:
                row = cur.fetchone()
                return tuple(row) if row else None
            return [tuple(r) for r in cur.fetchall()]
    except Exception as e:
        log.error("DB fetch xato: %s", e)
        return None if one else []

def init_db():
    db_exec("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        name    TEXT NOT NULL
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS tests (
        code     TEXT PRIMARY KEY,
        answers  TEXT,
        deadline TEXT DEFAULT '0',
        type     TEXT DEFAULT 'pdf',
        link     TEXT DEFAULT ''
    )""")
    # local time o'rniga UTC+5 ga moslab saqlash
    db_exec("""CREATE TABLE IF NOT EXISTS results (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id       INTEGER NOT NULL,
        name          TEXT    NOT NULL,
        code          TEXT    NOT NULL,
        score         INTEGER NOT NULL,
        total         INTEGER NOT NULL,
        analysis_text TEXT,
        created_at    TEXT DEFAULT (datetime('now','+5 hours'))
    )""")
    db_exec("""CREATE TABLE IF NOT EXISTS admins (
        user_id  INTEGER PRIMARY KEY,
        name     TEXT NOT NULL,
        added_at TEXT DEFAULT (datetime('now','+5 hours'))
    )""")
    log.info("Ma'lumotlar bazasi tayyor ✅")

init_db()

def is_admin(chat_id):
    if int(chat_id) == SUPER_ADMIN:
        return True
    row = db_fetch("SELECT user_id FROM admins WHERE user_id=?", (chat_id,), one=True)
    return row is not None

def is_super_admin(chat_id):
    return int(chat_id) == SUPER_ADMIN

def progress_bar(score, total):
    if total == 0:
        return ""
    pct   = score / total
    green = int(pct * 10)
    return "🟩" * green + "⬜" * (10 - green) + f"  {int(pct * 100)}%"

def main_menu(chat_id):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("📝 Test ishlash"),
        types.KeyboardButton("📊 Natijalarim"),
    )
    if is_admin(chat_id):
        kb.add(
            types.KeyboardButton("➕ Yangi test qo'shish"),
            types.KeyboardButton("➕ HTML test qo'shish"),
        )
        kb.add(types.KeyboardButton("📊 Natijalarni olish"))
    if is_super_admin(chat_id):
        kb.add(types.KeyboardButton("👥 Adminlar boshqaruvi"))
    return kb

def back_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton("🔙 Ortga qaytish"))
    return kb

def is_back(text):
    return text == "🔙 Ortga qaytish"

def safe_send(chat_id, text, **kwargs):
    try:
        return bot.send_message(chat_id, text, **kwargs)
    except Exception as e:
        log.warning("Xabar yuborishda xato (chat_id=%s): %s", chat_id, e)
        return None

def go_home(message):
    clear_state(message.chat.id)
    safe_send(message.chat.id, "🏠 Asosiy menyu:", reply_markup=main_menu(message.chat.id))

def set_commands():
    bot.set_my_commands([
        BotCommand("start",     "Botni qayta ishga tushirish"),
        BotCommand("test",      "Test ishlash"),
        BotCommand("testlarim", "Natijalarim"),
        BotCommand("edit",      "Ismni o'zgartirish"),
        BotCommand("info",      "Bot haqida"),
    ])

set_commands()

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    clear_state(msg.chat.id)
    user = db_fetch("SELECT name FROM users WHERE user_id=?", (msg.chat.id,), one=True)
    if user:
        safe_send(msg.chat.id, f"👋 Salom, *{user[0]}*!",
                  parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))
    else:
        m = safe_send(msg.chat.id, "🎉 Xush kelibsiz!\n\n✏️ Ism va familiyangizni kiriting:")
        if m:
            bot.register_next_step_handler(m, _register_user)

@bot.message_handler(commands=["edit"])
def cmd_edit(msg):
    m = safe_send(msg.chat.id, "✏️ Yangi ism va familiyangizni kiriting:", reply_markup=back_kb())
    if m:
        bot.register_next_step_handler(m, _register_user)

@bot.message_handler(commands=["info"])
def cmd_info(msg):
    safe_send(msg.chat.id,
        "ℹ️ *Math Test Bot*\n\n"
        "Bu bot orqali:\n"
        "• 📝 Test ishlashingiz\n"
        "• 📊 Natijalaringizni ko'rishingiz mumkin\n\n"
        "_Murojaat: @eshoonqulov_",
        parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))

def _register_user(msg):
    if is_back(msg.text):
        return go_home(msg)
    name = msg.text.strip()
    if not name or len(name) > 100:
        m = safe_send(msg.chat.id, "❌ Ism noto'g'ri. Qaytadan kiriting:")
        if m:
            bot.register_next_step_handler(m, _register_user)
        return
    db_exec("INSERT OR REPLACE INTO users (user_id, name) VALUES (?,?)", (msg.chat.id, name))
    safe_send(msg.chat.id, f"✅ Saqlandi! Xush kelibsiz, *{name}*!",
              parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))

@bot.message_handler(func=lambda m: m.text == "🔙 Ortga qaytish")
def handle_back(msg):
    go_home(msg)

@bot.message_handler(commands=["testlarim"])
@bot.message_handler(func=lambda m: m.text == "📊 Natijalarim")
def cmd_my_results(msg):
    rows = db_fetch(
        "SELECT code, score, total, created_at FROM results "
        "WHERE user_id=? ORDER BY id DESC LIMIT 25",
        (msg.chat.id,)
    )
    if not rows:
        safe_send(msg.chat.id, "❌ Siz hali hech qanday test ishlamadingiz.",
                  reply_markup=main_menu(msg.chat.id))
        return
    lines = ["📊 *Sizning natijalaringiz:*\n"]
    for i, (code, score, total, created_at) in enumerate(rows, 1):
        bar = progress_bar(score, total)
        lines.append(f"*{i}.* Kod: `{code}` — `{score}/{total}`\n{bar}\n_{created_at}_\n")
    safe_send(msg.chat.id, "\n".join(lines),
              parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))

# ─────────────────────────────────────────
#  TEST ISHLASH
# ─────────────────────────────────────────
@bot.message_handler(commands=["test"])
@bot.message_handler(func=lambda m: m.text == "📝 Test ishlash")
def cmd_student(msg):
    user = db_fetch("SELECT name FROM users WHERE user_id=?", (msg.chat.id,), one=True)
    if not user:
        return cmd_start(msg)
    set_state(msg.chat.id, {"action": "student_solve", "name": user[0]})
    m = safe_send(msg.chat.id, "🔢 Test kodini kiriting:", reply_markup=back_kb())
    if m:
        bot.register_next_step_handler(m, _student_code_entered)

def _student_code_entered(msg):
    if is_back(msg.text):
        return go_home(msg)
    code = msg.text.strip().upper()

    count = db_fetch(
        "SELECT COUNT(*) FROM results WHERE user_id=? AND code=?",
        (msg.chat.id, code), one=True
    )
    if count and count[0] >= 2:
        safe_send(msg.chat.id,
                  "⚠️ Siz bu testni allaqachon *2 marta* ishlagansiz!\n"
                  "Boshqa test kodini kiriting.",
                  parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))
        return

    row = db_fetch(
        "SELECT answers, deadline, type, link FROM tests WHERE code=?",
        (code,), one=True
    )
    if not row:
        m = safe_send(msg.chat.id,
                      "❌ Bunday kod topilmadi. Qaytadan kiriting:",
                      reply_markup=back_kb())
        if m:
            bot.register_next_step_handler(m, _student_code_entered)
        return

    answers, deadline, test_type, html_link = row
    deadline = deadline or "0"

    # Muddatni tekshirish (Toshkent vaqti bilan)
    if deadline != "0":
        try:
            if get_uz_now() > datetime.strptime(deadline, "%Y-%m-%d %H:%M"):
                safe_send(msg.chat.id,
                          f"⛔️ Test yopilgan!\n📅 Muddat: {deadline} gacha edi.",
                          reply_markup=main_menu(msg.chat.id))
                return
        except ValueError:
            pass

    update_state(msg.chat.id,
                 code=code,
                 correct=answers,
                 type=test_type,
                 html_link=html_link)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    if test_type == "html":
        kb.add(types.KeyboardButton(
            "📱 Testni boshlash",
            web_app=types.WebAppInfo(url=html_link)
        ))
    else:
        kb.add(types.KeyboardButton(
            "📱 Javoblarni belgilash",
            web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?count={len(answers)}")
        ))
    kb.add(types.KeyboardButton("🔙 Ortga qaytish"))

    safe_send(msg.chat.id,
              f"✅ *Test topildi!*\n🔢 Kod: `{code}`\n\n"
              "Boshlash uchun tugmani bosing 👇",
              parse_mode="Markdown", reply_markup=kb)

# ─────────────────────────────────────────
#  WEB APP NATIJALARNI QABUL QILISH
# ─────────────────────────────────────────
@bot.message_handler(content_types=["web_app_data"])
def handle_web_app(msg):
    try:
        state    = get_state(msg.chat.id)
        raw_data = msg.web_app_data.data.strip()
        action   = state.get("action")

        # ── ADMIN: PDF javoblarini saqlash ──
        if action == "admin_save":
            db_exec(
                "INSERT OR REPLACE INTO tests (code, answers, deadline, type, link) "
                "VALUES (?,?,?,?,?)",
                (state["code"], raw_data.lower(), state.get("deadline", "0"), "pdf", "")
            )
            clear_state(msg.chat.id)
            safe_send(msg.chat.id, "✅ Test muvaffaqiyatli saqlandi!",
                      reply_markup=main_menu(msg.chat.id))
            return

        # ── TALABA: natijalarni baholash ──
        if action == "student_solve":
            test_type = state.get("type", "pdf")
            name      = state.get("name", "Noma'lum")
            code      = state.get("code", "?")

            # ⛔️ MUHIM: Natijani saqlashdan oldin yana bir marta deadline'ni tekshiramiz.
            # (Agar talaba testni avval ochib olib, deadline o'tgandan so'ng javob yuborsa, uni to'xtatamiz)
            row = db_fetch("SELECT deadline FROM tests WHERE code=?", (code,), one=True)
            if row and row[0] != "0":
                try:
                    if get_uz_now() > datetime.strptime(row[0], "%Y-%m-%d %H:%M"):
                        safe_send(msg.chat.id,
                                  f"⛔️ Javoblar qabul qilinmadi!\n📅 Sababi: ishlash muddati ({row[0]}) tugagan.",
                                  reply_markup=main_menu(msg.chat.id))
                        clear_state(msg.chat.id)
                        return
                except ValueError:
                    pass

            if test_type == "pdf":
                correct  = state.get("correct", "").lower()
                received = raw_data.lower()
                total    = len(correct)
                score    = sum(1 for s, c in zip(received, correct) if s == c)
                analysis = []
                for i, (s, c) in enumerate(zip(received, correct), 1):
                    if s == c:
                        analysis.append(f"{i}✅")
                    else:
                        analysis.append(f"{i}❌({c.upper()})")
                grid = "\n".join(
                    " ".join(analysis[i:i+5]) for i in range(0, len(analysis), 5)
                )

            elif test_type == "html":
                parts = raw_data.split("|")
                if len(parts) >= 2:
                    try:
                        score = int(parts[0])
                        total = int(parts[1])
                    except ValueError:
                        score, total = 0, 0
                    grid = parts[2] if len(parts) > 2 else "✅ Test yakunlandi"
                else:
                    score, total, grid = 0, 0, "⚠️ Natija formati noto'g'ri"
            else:
                return

            bar = progress_bar(score, total)

            result_text = (
                f"👤 *{name}*\n"
                f"🔢 Kod: `{code}`\n"
                f"📊 Natija: *{score}/{total}*\n"
                f"{bar}\n\n"
                f"📋 *Tahlil:*\n{grid}"
            )

            db_exec(
                "INSERT INTO results (user_id, name, code, score, total, analysis_text) "
                "VALUES (?,?,?,?,?,?)",
                (msg.chat.id, name, code, score, total, result_text)
            )
            clear_state(msg.chat.id)

            safe_send(msg.chat.id, result_text,
                      parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))

            safe_send(SUPER_ADMIN, f"🔔 *Yangi natija!*\n\n{result_text}",
                      parse_mode="Markdown")

    except Exception as e:
        log.exception("web_app_data xatolik: %s", e)
        safe_send(msg.chat.id, "⚠️ Xatolik yuz berdi. Boshidan urinib ko'ring.",
                  reply_markup=main_menu(msg.chat.id))

# ─────────────────────────────────────────
#  ADMIN: PDF TEST QO'SHISH
# ─────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "➕ Yangi test qo'shish")
def admin_add_pdf(msg):
    if not is_admin(msg.chat.id):
        return
    m = safe_send(msg.chat.id,
                  "Kod va savol sonini kiriting\n_(Misol: 701 30)_",
                  parse_mode="Markdown", reply_markup=back_kb())
    if m:
        bot.register_next_step_handler(m, _admin_pdf_code)

def _admin_pdf_code(msg):
    if is_back(msg.text):
        return go_home(msg)
    try:
        parts = msg.text.strip().split()
        code  = parts[0].upper()
        count = int(parts[1])
        set_state(msg.chat.id, {"action": "admin_save_deadline", "code": code, "count": count})
        m = safe_send(msg.chat.id,
                      "📅 Yopilish vaqtini kiriting\n_(Misol: 2025-12-31 18:00)_ yoki *0* (cheksiz)",
                      parse_mode="Markdown", reply_markup=back_kb())
        if m:
            bot.register_next_step_handler(m, _admin_pdf_deadline)
    except (IndexError, ValueError):
        m = safe_send(msg.chat.id, "❌ Noto'g'ri format!\n_(Misol: 701 30)_",
                      parse_mode="Markdown")
        if m:
            bot.register_next_step_handler(m, _admin_pdf_code)

def _admin_pdf_deadline(msg):
    if is_back(msg.text):
        return go_home(msg)
    deadline = msg.text.strip()
    if deadline != "0":
        try:
            datetime.strptime(deadline, "%Y-%m-%d %H:%M")
        except ValueError:
            m = safe_send(msg.chat.id, "❌ Noto'g'ri format! (YYYY-MM-DD HH:MM) yoki 0:")
            if m:
                bot.register_next_step_handler(m, _admin_pdf_deadline)
            return

    update_state(msg.chat.id, deadline=deadline, action="admin_save")
    state = get_state(msg.chat.id)
    kb    = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(types.KeyboardButton(
        "🛠 Javoblarni kiritish",
        web_app=types.WebAppInfo(url=f"{WEB_APP_URL}?count={state['count']}")
    ))
    kb.add(types.KeyboardButton("🔙 Ortga qaytish"))
    safe_send(msg.chat.id,
              f"✅ *Kod:* `{state['code']}`\n📅 *Muddat:* {deadline}\n\n"
              "Tugmani bosib javoblarni kiriting 👇",
              parse_mode="Markdown", reply_markup=kb)

# ─────────────────────────────────────────
#  ADMIN: HTML TEST QO'SHISH
# ─────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "➕ HTML test qo'shish")
def admin_add_html(msg):
    if not is_admin(msg.chat.id):
        return
    m = safe_send(msg.chat.id,
                  "Kod va havolani kiriting\n_(Misol: 901 https://example.com)_\n\n"
                  "⚠️ Havola Netlify yoki boshqa saytdan olingan to'liq URL bo'lishi kerak",
                  parse_mode="Markdown", reply_markup=back_kb())
    if m:
        bot.register_next_step_handler(m, _admin_html_link)

def _admin_html_link(msg):
    if is_back(msg.text):
        return go_home(msg)
    try:
        parts = msg.text.strip().split(maxsplit=1)
        code  = parts[0].upper()
        link  = parts[1].strip()
        if not link.startswith("http"):
            raise ValueError("URL noto'g'ri")
        set_state(msg.chat.id, {"code": code, "link": link})
        m = safe_send(msg.chat.id,
                      "📅 Yopilish vaqti _(YYYY-MM-DD HH:MM)_ yoki *0*:",
                      parse_mode="Markdown", reply_markup=back_kb())
        if m:
            bot.register_next_step_handler(m, _admin_html_save)
    except (IndexError, ValueError):
        m = safe_send(msg.chat.id,
                      "❌ Noto'g'ri format!\n_(Misol: 901 https://example.netlify.app)_",
                      parse_mode="Markdown")
        if m:
            bot.register_next_step_handler(m, _admin_html_link)

def _admin_html_save(msg):
    if is_back(msg.text):
        return go_home(msg)
    state    = get_state(msg.chat.id)
    deadline = msg.text.strip()
    if deadline != "0":
        try:
            datetime.strptime(deadline, "%Y-%m-%d %H:%M")
        except ValueError:
            m = safe_send(msg.chat.id, "❌ Noto'g'ri format! (YYYY-MM-DD HH:MM) yoki 0:")
            if m:
                bot.register_next_step_handler(m, _admin_html_save)
            return
    db_exec(
        "INSERT OR REPLACE INTO tests (code, answers, deadline, type, link) VALUES (?,?,?,?,?)",
        (state["code"], "", deadline, "html", state["link"])
    )
    clear_state(msg.chat.id)
    safe_send(msg.chat.id,
              f"✅ HTML test saqlandi!\n🔢 Kod: `{state['code']}`\n🔗 Link: {state['link']}",
              parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))

# ─────────────────────────────────────────
#  ADMIN: NATIJALARNI KO'RISH
# ─────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "📊 Natijalarni olish")
def admin_get_results(msg):
    if not is_admin(msg.chat.id):
        return
    m = safe_send(msg.chat.id, "🔢 Test kodini kiriting:", reply_markup=back_kb())
    if m:
        bot.register_next_step_handler(m, _admin_show_results)

def _admin_show_results(msg):
    if is_back(msg.text):
        return go_home(msg)
    code = msg.text.strip().upper()
    rows = db_fetch(
        "SELECT name, score, total FROM results WHERE code=? ORDER BY score DESC",
        (code,)
    )
    if not rows:
        safe_send(msg.chat.id, f"❌ `{code}` kodi bo'yicha natija topilmadi.",
                  parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))
        return

    lines = [f"📊 *{code}* natijalari — jami: {len(rows)} ta\n"]
    for i, (name, score, total) in enumerate(rows, 1):
        bar = progress_bar(score, total)
        lines.append(f"{i}. *{name}* — `{score}/{total}`\n{bar}\n")

    full = "\n".join(lines)
    for chunk in [full[i:i+4000] for i in range(0, len(full), 4000)]:
        safe_send(msg.chat.id, chunk, parse_mode="Markdown",
                  reply_markup=main_menu(msg.chat.id))

# ─────────────────────────────────────────
#  SUPER ADMIN: ADMINLAR BOSHQARUVI
# ─────────────────────────────────────────
@bot.message_handler(func=lambda m: m.text == "👥 Adminlar boshqaruvi")
def admin_management(msg):
    if not is_super_admin(msg.chat.id):
        return
    admins = db_fetch("SELECT user_id, name, added_at FROM admins ORDER BY added_at DESC")
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("➕ Admin qo'shish"),
        types.KeyboardButton("❌ Admin o'chirish"),
    )
    kb.add(types.KeyboardButton("🔙 Ortga qaytish"))

    if not admins:
        text = "👥 *Adminlar ro'yxati*\n\nHozircha qo'shimcha admin yo'q."
    else:
        lines = ["👥 *Adminlar ro'yxati:*\n"]
        for i, (uid, name, added_at) in enumerate(admins, 1):
            lines.append(f"{i}. *{name}*\n   ID: `{uid}`\n   📅 {added_at}\n")
        text = "\n".join(lines)

    safe_send(msg.chat.id, text, parse_mode="Markdown", reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "➕ Admin qo'shish")
def add_admin_start(msg):
    if not is_super_admin(msg.chat.id):
        return
    m = safe_send(msg.chat.id,
                  "👤 Yangi admin *Telegram ID* sini kiriting:\n\n"
                  "_(Foydalanuvchi @userinfobot ga /start yuborsа ID ni oladi)_",
                  parse_mode="Markdown", reply_markup=back_kb())
    if m:
        set_state(msg.chat.id, {"action": "add_admin_id"})
        bot.register_next_step_handler(m, _add_admin_id)

def _add_admin_id(msg):
    if is_back(msg.text):
        return go_home(msg)
    try:
        new_id = int(msg.text.strip())
    except ValueError:
        m = safe_send(msg.chat.id, "❌ ID faqat raqamdan iborat bo'lishi kerak. Qaytadan:")
        if m:
            bot.register_next_step_handler(m, _add_admin_id)
        return
    if new_id == SUPER_ADMIN:
        safe_send(msg.chat.id, "⚠️ Bu asosiy admin ID si!",
                  reply_markup=main_menu(msg.chat.id))
        return
    existing = db_fetch("SELECT user_id FROM admins WHERE user_id=?", (new_id,), one=True)
    if existing:
        safe_send(msg.chat.id, "⚠️ Bu foydalanuvchi allaqachon admin!",
                  reply_markup=main_menu(msg.chat.id))
        return
    update_state(msg.chat.id, new_admin_id=new_id)
    m = safe_send(msg.chat.id,
                  f"ID: `{new_id}`\n\n✏️ Bu adminning ismini kiriting:",
                  parse_mode="Markdown", reply_markup=back_kb())
    if m:
        bot.register_next_step_handler(m, _add_admin_name)

def _add_admin_name(msg):
    if is_back(msg.text):
        return go_home(msg)
    state  = get_state(msg.chat.id)
    new_id = state.get("new_admin_id")
    name   = msg.text.strip()
    if not name or len(name) > 100:
        m = safe_send(msg.chat.id, "❌ Ism noto'g'ri. Qaytadan kiriting:")
        if m:
            bot.register_next_step_handler(m, _add_admin_name)
        return
    db_exec("INSERT OR REPLACE INTO admins (user_id, name) VALUES (?,?)", (new_id, name))
    clear_state(msg.chat.id)
    try:
        bot.send_message(new_id,
                         "🎉 Siz botga *admin* sifatida qo'shildingiz!\n"
                         "Endi test qo'shish va natijalarni ko'rish imkoniyatingiz bor.\n\n"
                         "/start bosing.",
                         parse_mode="Markdown")
    except Exception:
        pass
    safe_send(msg.chat.id,
              f"✅ *{name}* (ID: `{new_id}`) admin qilindi!",
              parse_mode="Markdown", reply_markup=main_menu(msg.chat.id))

@bot.message_handler(func=lambda m: m.text == "❌ Admin o'chirish")
def remove_admin_start(msg):
    if not is_super_admin(msg.chat.id):
        return
    admins = db_fetch("SELECT user_id, name FROM admins ORDER BY added_at DESC")
    if not admins:
        safe_send(msg.chat.id, "❌ O'chirish uchun admin yo'q.",
                  reply_markup=main_menu(msg.chat.id))
        return
    kb = types.InlineKeyboardMarkup()
    for uid, name in admins:
        kb.add(types.InlineKeyboardButton(
            f"❌ {name} (ID: {uid})",
            callback_data=f"del_admin:{uid}"
        ))
    safe_send(msg.chat.id, "👇 O'chirmoqchi bo'lgan adminni tanlang:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("del_admin:"))
def remove_admin_confirm(call):
    if not is_super_admin(call.message.chat.id):
        return
    uid = int(call.data.split(":")[1])
    row = db_fetch("SELECT name FROM admins WHERE user_id=?", (uid,), one=True)
    if not row:
        bot.answer_callback_query(call.id, "Admin topilmadi!")
        return
    name = row[0]
    db_exec("DELETE FROM admins WHERE user_id=?", (uid,))
    try:
        bot.send_message(uid, "⚠️ Sizning admin huquqingiz bekor qilindi.")
    except Exception:
        pass
    bot.answer_callback_query(call.id, f"✅ {name} o'chirildi!")
    bot.edit_message_text(
        f"✅ *{name}* (ID: `{uid}`) admin ro'yxatidan o'chirildi.",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="Markdown"
    )
    safe_send(call.message.chat.id, "🏠 Asosiy menyu:",
              reply_markup=main_menu(call.message.chat.id))

# ─────────────────────────────────────────
#  WEBHOOK
# ─────────────────────────────────────────
@app.route(f"/{TOKEN}", methods=["POST"])
def telegram_webhook():
    if request.content_type == "application/json":
        update = telebot.types.Update.de_json(request.get_data(as_text=True))
        bot.process_new_updates([update])
        return "", 200
    return "", 403

@app.route("/")
def health_check():
    return "✅ Bot ishlayapti!", 200

def setup_webhook():
    if not RAILWAY_URL:
        log.warning("⚠️ RAILWAY_URL o'rnatilmagan — webhook o'rnatilmadi")
        return
    webhook_url = f"{RAILWAY_URL.rstrip('/')}/{TOKEN}"
    try:
        bot.remove_webhook()
        bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "web_app_data", "callback_query"]
        )
        log.info("✅ Webhook o'rnatildi: %s", webhook_url)
    except Exception as e:
        log.error("❌ Webhook o'rnatishda xato: %s", e)

setup_webhook()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)
    
