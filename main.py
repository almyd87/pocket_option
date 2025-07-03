
import requests
import telebot
from telebot import types
import json
import os
import time
import threading
import schedule

TOKEN = "7869769364:AAGWDK4orRgxQDcjfEHScbfExgIt_Ti8ARs"
ADMIN_ID = 1125130202
PAIR = "EURUSD"

bot = telebot.TeleBot(TOKEN)

USERS_FILE = "users.json"
CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w") as f:
            json.dump({"price": 3, "wallet": "0x3a5db3aec7c262017af9423219eb64b5eb6643d7"}, f)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_user(user_id, username):
    users = get_users()
    if str(user_id) not in users:
        users[str(user_id)] = {"username": username, "status": "pending"}
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

def get_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def update_user_status(user_id, status):
    users = get_users()
    if str(user_id) in users:
        users[str(user_id)]["status"] = status
        with open(USERS_FILE, "w") as f:
            json.dump(users, f)

def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("توصية الآن")
    return markup

def calc_ema(prices, period):
    ema = prices[0]
    k = 2 / (period + 1)
    for price in prices[1:]:
        ema = price * k + ema * (1 - k)
    return ema

def calc_rsi(prices, period=14):
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_bollinger(prices, period=20):
    if len(prices) < period:
        return None, None
    sma = sum(prices[-period:]) / period
    std = (sum((p - sma) ** 2 for p in prices[-period:]) / period) ** 0.5
    return sma + 2 * std, sma - 2 * std

def fetch_data():
    url = "https://scanner.tradingview.com/forex/scan"
    payload = {
        "symbols": {"tickers": [f"OANDA:{PAIR}"], "query": {"types": []}},
        "columns": ["close"]
    }
    try:
        prices = []
        for _ in range(50):
            r = requests.post(url, json=payload, timeout=5)
            p = r.json()['data'][0]['d'][0]
            prices.append(p)
            time.sleep(0.05)
        return prices
    except Exception as e:
        print("Error:", e)
        return []

def generate_signal(prices):
    ema20 = calc_ema(prices[-20:], 20)
    ema50 = calc_ema(prices[-50:], 50)
    rsi = calc_rsi(prices, 14)
    upper, lower = calc_bollinger(prices)
    current = prices[-1]
    signal = "انتظار"
    if ema20 > ema50 and current > ema20 and rsi < 70:
        signal = "شراء (Call)"
    elif ema20 < ema50 and current < ema20 and rsi > 30:
        signal = "بيع (Put)"
    return f"توصية لحظية ({PAIR})\nالسعر الحالي: {round(current, 5)}\nEMA20: {round(ema20, 5)} | EMA50: {round(ema50, 5)}\nRSI(14): {round(rsi, 2)}\nالإشارة: {signal}"

def send_to_all():
    prices = fetch_data()
    if len(prices) >= 50:
        msg = generate_signal(prices)
        users = get_users()
        for uid, data in users.items():
            if data["status"] == "accepted":
                try:
                    bot.send_message(int(uid), msg)
                except:
                    continue

def run_schedule():
    schedule.every(60).seconds.do(send_to_all)
    while True:
        schedule.run_pending()
        time.sleep(1)

threading.Thread(target=run_schedule).start()

@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username or "لا يوجد"
    save_user(user_id, username)
    users = get_users()
    if users[str(user_id)]["status"] != "accepted":
        config = load_config()
        text = f"الاشتراك: {config['price']} دولار\nادفع إلى: {config['wallet']}\nأرسل إثبات الدفع"
        with open("payment_guide.png", "rb") as img:
            bot.send_photo(message.chat.id, img, caption=text)
    else:
        bot.send_message(message.chat.id, "تم التفعيل ✅", reply_markup=get_main_menu())

@bot.message_handler(func=lambda m: m.text == "توصية الآن")
def recommend(message):
    user_id = message.from_user.id
    users = get_users()
    if str(user_id) in users and users[str(user_id)]["status"] == "accepted":
        prices = fetch_data()
        if len(prices) >= 50:
            msg = generate_signal(prices)
            bot.send_message(user_id, msg)
        else:
            bot.send_message(user_id, "تعذر جلب البيانات.")
    else:
        bot.send_message(user_id, "يرجى تفعيل اشتراكك أولاً.")

@bot.message_handler(commands=["admin"])
def admin_panel(message):
    if message.from_user.id != ADMIN_ID:
        return
    users = get_users()
    pending = [uid for uid, data in users.items() if data["status"] == "pending"]
    for uid in pending:
        data = users[uid]
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("قبول", callback_data=f"accept_{uid}"))
        markup.add(types.InlineKeyboardButton("رفض", callback_data=f"reject_{uid}"))
        bot.send_message(message.chat.id, f"طلب جديد من @{data['username']}", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_") or call.data.startswith("reject_"))
def handle_decision(call):
    if call.from_user.id != ADMIN_ID:
        return
    action, uid = call.data.split("_")
    if action == "accept":
        update_user_status(uid, "accepted")
        bot.send_message(int(uid), "✅ تم تفعيل اشتراكك.")
    elif action == "reject":
        update_user_status(uid, "rejected")
        bot.send_message(int(uid), "❌ تم رفض اشتراكك.")

@bot.message_handler(content_types=['photo'])
def handle_payment_proof(message):
    user_id = message.from_user.id
    username = message.from_user.username or "لا يوجد"
    caption = f"إثبات دفع من @{username} (ID: {user_id})"
    bot.send_photo(ADMIN_ID, message.photo[-1].file_id, caption=caption)
    bot.send_message(user_id, "✅ تم استلام إثبات الدفع. سيتم مراجعته.")

print("Bot is running...")
bot.infinity_polling()
