import telebot
from telebot import types
import sqlite3
import threading
import time
import re
import asyncio
import uuid
import json
import requests
import random
import string
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.sessions import StringSession
import telethon.errors

# ========= إعدادات =========
TOKEN = "8554455289:AAG5k980NAyzIxOGrEgRf0pM_Vd-K0j7t_g"
OWNER_ID = 1423822809
SUPPORT = "https://t.me/w_6z1"
ACTIVATION_CHANNEL_ID = -1003720698268
ACTIVATION_CHANNEL_URL = "https://t.me/NUBOT1"

MY_API_ID = 32218648
MY_API_HASH = 'ed4ae9c515983e710e823ae75b6e8c80'

bot = telebot.TeleBot(TOKEN)

# ========= إعداد حلقة asyncio =========
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# ========= قاعدة بيانات =========
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

def init_db():
    cur.execute("""CREATE TABLE IF NOT EXISTS users(
        user_id INTEGER PRIMARY KEY,
        points REAL DEFAULT 0,
        join_date TEXT,
        last_active TEXT,
        referred_by INTEGER,
        is_verified INTEGER DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY, added_by INTEGER, added_date TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS numbers(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT UNIQUE,
        code TEXT,
        price REAL DEFAULT 10,
        service TEXT DEFAULT 'تيليجرام',
        country TEXT DEFAULT 'دول أخرى',
        added_by INTEGER,
        added_date TEXT,
        status TEXT DEFAULT 'متاح',
        session_str TEXT,
        api_id INTEGER,
        api_hash TEXT,
        is_2fa INTEGER DEFAULT 0,
        two_factor TEXT,
        category_name TEXT DEFAULT '2026'
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        number TEXT,
        code TEXT,
        two_factor TEXT,
        price REAL,
        country TEXT,
        service TEXT,
        purchase_date TEXT,
        session_str TEXT,
        api_id INTEGER,
        api_hash TEXT,
        is_2fa INTEGER,
        code_received INTEGER DEFAULT 0,
        activation_sent INTEGER DEFAULT 0
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS mandatory_channels(channel_id TEXT PRIMARY KEY, channel_url TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS charge_codes(code TEXT PRIMARY KEY, amount REAL, created_by INTEGER, is_used INTEGER DEFAULT 0)""")
    
    try: cur.execute("ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0")
    except: pass
    try: cur.execute("ALTER TABLE numbers ADD COLUMN category_name TEXT DEFAULT '2026'")
    except: pass
    
    defaults = [
        ('star_price', '20'), ('ref_reward', '0.1'), ('asia_exchange_rate', '1300'),
        ('asia_admin_number', '07776326105'), ('external_api_profit', '0.2'),
        ('external_api_status', 'on'), ('asia_topup_hidden', 'off')
    ]
    for k, v in defaults: cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()

init_db()

# ========= دوال مساعدة =========
def get_setting(key, default=None):
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row[0] if row else default

def is_admin(uid):
    if uid == OWNER_ID: return True
    cur.execute("SELECT user_id FROM admins WHERE user_id=?", (uid,))
    return cur.fetchone() is not None

def get_user_points(uid):
    cur.execute("SELECT points FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    return row[0] if row else 0

def add_points_to_user(uid, amount):
    cur.execute("INSERT OR IGNORE INTO users (user_id, points, join_date) VALUES (?, 0, ?)", (uid, get_current_time()))
    cur.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (amount, uid))
    conn.commit()

def get_current_time(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def update_user_activity(uid):
    cur.execute("INSERT OR IGNORE INTO users (user_id, join_date, last_active) VALUES (?, ?, ?)", (uid, get_current_time(), get_current_time()))
    cur.execute("UPDATE users SET last_active=? WHERE user_id=?", (get_current_time(), uid))
    conn.commit()

def check_subscription(uid):
    cur.execute("SELECT channel_id, channel_url FROM mandatory_channels")
    channels = cur.fetchall()
    not_joined = []
    for ch_id, ch_url in channels:
        try:
            member = bot.get_chat_member(ch_id, uid)
            if member.status in ['left', 'kicked']: not_joined.append((ch_id, ch_url))
        except: continue
    return not_joined

def subscription_markup(not_joined):
    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, (ch_id, ch_url) in enumerate(not_joined, 1):
        url = ch_url if ch_url.startswith("http") else f"https://t.me/{ch_url.replace('@','')}"
        kb.add(types.InlineKeyboardButton(f"قنـاة الاشتـراك {i}", url=url))
    kb.add(types.InlineKeyboardButton("تـم الاشتـراك", callback_data="check_sub"))
    return kb

# ========= التحقق (Captcha) =========
captcha_data = {}
user_states = {}

def generate_captcha(uid):
    n1, n2 = random.randint(1, 10), random.randint(1, 10)
    captcha_data[uid] = n1 + n2
    return f"التحقـق مـن الأمـان\n\nيرجى حل المسألة التالية لمنع الرشق\n\nكم يساوي {n1} + {n2} ؟"

# ========= القوائم الرئيسية =========
def show_main_menu(uid, name):
    points = get_user_points(uid)
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("شـراء رقـم", callback_data="buy_menu"), 
           types.InlineKeyboardButton("أرقـام دوليـة", callback_data="buy_api_countries"))
    kb.add(types.InlineKeyboardButton("رصيـدك", callback_data="points"), 
           types.InlineKeyboardButton("شحـن الرصيـد", callback_data="auto_recharge"))
    kb.add(types.InlineKeyboardButton("دعـوة أصدقـاء", callback_data="referral"), 
           types.InlineKeyboardButton("الـدعم الفنـي", url=SUPPORT))
    if is_admin(uid): kb.add(types.InlineKeyboardButton("لوحـة التحكـم", callback_data="admin_panel"))
    
    text = f"مرحبـآ بـك يـا {name}\n\nرصيـدك الحـالي {points:.2f} نقطـة\nأيديـك {uid}\n\nاختر من الأزرار أدناه للبدء"
    bot.send_message(uid, text, reply_markup=kb)

# ========= /start =========
@bot.message_handler(commands=["start"])
def start(msg):
    uid = msg.from_user.id
    update_user_activity(uid)
    
    cur.execute("SELECT is_verified FROM users WHERE user_id=?", (uid,))
    row = cur.fetchone()
    if not row or not row[0]:
        bot.send_message(uid, generate_captcha(uid))
        return

    not_joined = check_subscription(uid)
    if not_joined:
        bot.send_message(uid, "يجب عليك الاشتراك في قنوات البوت أولاً لاستخدامه", reply_markup=subscription_markup(not_joined))
        return

    if len(msg.text.split()) > 1:
        ref_id = msg.text.split()[1]
        if ref_id.isdigit() and int(ref_id) != uid:
            cur.execute("SELECT referred_by FROM users WHERE user_id=?", (uid,))
            ref_row = cur.fetchone()
            if not ref_row or ref_row[0] is None:
                cur.execute("UPDATE users SET referred_by=? WHERE user_id=?", (ref_id, uid))
                conn.commit()

    show_main_menu(uid, msg.from_user.first_name)

# ========= معالج الرسائل النصية =========
@bot.message_handler(func=lambda m: True)
def handle_msg(msg):
    uid, text = msg.from_user.id, msg.text.strip()

    if uid in captcha_data:
        if text.isdigit() and int(text) == captcha_data[uid]:
            cur.execute("UPDATE users SET is_verified=1 WHERE user_id=?", (uid,))
            conn.commit()
            del captcha_data[uid]
            bot.send_message(uid, "تـم التحقـق بنجـاح")
            start(msg)
        else:
            bot.send_message(uid, "إجابـة خاطئـة حاول مجدداً\n" + generate_captcha(uid))
        return

    if uid in user_states and user_states[uid][0] == "redeem_code":
        cur.execute("SELECT amount, is_used FROM charge_codes WHERE code=?", (text.upper(),))
        r = cur.fetchone()
        if r and r[1] == 0:
            add_points_to_user(uid, r[0])
            cur.execute("UPDATE charge_codes SET is_used=1 WHERE code=?", (text.upper(),))
            conn.commit()
            bot.send_message(uid, f"تـم شحـن {r[0]} نقطـة بنجـاح")
        else:
            bot.send_message(uid, "الكـود غير صـالح أو مستخدم مسبقاً")
        del user_states[uid]
        return

# ========= Callback Handlers =========
@bot.callback_query_handler(func=lambda call: True)
def cb(call):
    uid = call.from_user.id
    
    if call.data == "check_sub":
        not_joined = check_subscription(uid)
        if not_joined:
            bot.answer_callback_query(call.id, "لم تشترك في جميع القنوات بعد", show_alert=True)
        else:
            cur.execute("SELECT referred_by, points FROM users WHERE user_id=?", (uid,))
            row = cur.fetchone()
            if row and row[0] and row[1] == 0:
                ref_id, reward = row[0], float(get_setting('ref_reward', 0.1))
                add_points_to_user(ref_id, reward)
                try: bot.send_message(ref_id, f"حصلت على {reward} نقطة لانضمام صديقك")
                except: pass
            bot.delete_message(uid, call.message.message_id)
            start(call.message)
        return

    if call.data == "main_menu":
        bot.delete_message(uid, call.message.message_id)
        start(call.message)
        return

    if call.data == "points":
        p = get_user_points(uid)
        bot.answer_callback_query(call.id, f"رصيـدك {p:.2f} نقطـة", show_alert=True)
        return

    if call.data == "auto_recharge":
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("شحـن آسيـا سيـل", callback_data="recharge_asia"),
               types.InlineKeyboardButton("شحـن نجـوم تيليجـرام", callback_data="recharge_stars"),
               types.InlineKeyboardButton("شحـن عبـر كـود", callback_data="charge_via_code"),
               types.InlineKeyboardButton("رجـوع", callback_data="main_menu"))
        bot.edit_message_text("قسـم شحـن الرصيـد\n\nاختر الوسيلة المناسبة لك", uid, call.message.message_id, reply_markup=kb)
        return

    if call.data == "charge_via_code":
        user_states[uid] = ("redeem_code",)
        bot.send_message(uid, "أرسـل كـود الشحـن الخـاص بـك", reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("إلغـاء", callback_data="main_menu")))
        return

    if call.data == "buy_menu":
        cur.execute("SELECT DISTINCT category_name FROM numbers WHERE status='متاح'")
        cats = cur.fetchall()
        kb = types.InlineKeyboardMarkup(row_width=2)
        for c in cats: kb.add(types.InlineKeyboardButton(f"فئـة {c[0]}", callback_data=f"show_cat_{c[0]}"))
        kb.add(types.InlineKeyboardButton("عرض كـافة الأرقـام", callback_data="show_all_nums"))
        kb.add(types.InlineKeyboardButton("رجـوع", callback_data="main_menu"))
        bot.edit_message_text("فئـات الأرقـام المتوفـرة", uid, call.message.message_id, reply_markup=kb)
        return

    if call.data == "referral":
        reward = get_setting('ref_reward', 0.1)
        link = f"https://t.me/{bot.get_me().username}?start={uid}"
        bot.edit_message_text(f"نظـام الإحـالة\n\nاحصل على {reward} نقطة عن كل شخص يشترك عبر رابطك\n\nرابطـك {link}", uid, call.message.message_id, 
                             reply_markup=types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("رجـوع", callback_data="main_menu")))
        return

    bot.answer_callback_query(call.id, "قيد التطوير أو الصيانة")

if __name__ == "__main__":
    def loop_start(): asyncio.set_event_loop(loop); loop.run_forever()
    threading.Thread(target=loop_start, daemon=True).start()
    print("Bot is running without Emojis and with Text Extension...")
    bot.infinity_polling()
