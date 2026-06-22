import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, PreCheckoutQueryHandler, filters
import os

# ===== НАСТРОЙКИ =====
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
# =====================

DB_PATH = "bot.db"

# Тарифы
TARIFFS = {
    "1": {"days": 1, "price": 20, "name": "1 день"},
    "10": {"days": 10, "price": 150, "name": "10 дней"},
    "30": {"days": 30, "price": 300, "name": "30 дней"},
    "90": {"days": 90, "price": 700, "name": "90 дней"},
    "365": {"days": 365, "price": 1200, "name": "365 дней"},
    "forever": {"days": 99999, "price": 1700, "name": "Навсегда"}
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id TEXT PRIMARY KEY, sub_end TEXT,
                  reply_text TEXT DEFAULT 'Я сейчас занят, отвечу позже',
                  active INTEGER DEFAULT 0, tariff TEXT)''')
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id=?", (str(user_id),))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "sub_end": row[1], "reply_text": row[2], "active": bool(row[3]), "tariff": row[4]}
    return None

def save_user(user_id, data):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?)''',
              (str(user_id), data.get("sub_end"), data.get("reply_text", "Я сейчас занят, отвечу позже"),
               int(data.get("active", False)), data.get("tariff")))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    rows = c.fetchall()
    conn.close()
    return [{"user_id": r[0], "sub_end": r[1], "reply_text": r[2], "active": bool(r[3]), "tariff": r[4]} for r in rows]

class SimpleBot:
    def __init__(self, token):
        self.token = token
        init_db()
        self.app = Application.builder().token(token).build()
        self.setup_handlers()
        
    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("buy", self.buy))
        self.app.add_handler(CommandHandler("set", self.set_reply))
        self.app.add_handler(CommandHandler("on", self.turn_on))
        self.app.add_handler(CommandHandler("off", self.turn_off))
        self.app.add_handler(CommandHandler("status", self.status))
        self.app.add_handler(CommandHandler("id", self.get_id))
        self.app.add_handler(CommandHandler("admin", self.admin_panel))
        self.app.add_handler(CommandHandler("gift", self.gift_sub))
        self.app.add_handler(CallbackQueryHandler(self.handle_callback))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.auto_reply))
        self.app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment))
        self.app.add_handler(PreCheckoutQueryHandler(self.pre_checkout))
    
    async def get_id(self, update, context):
        await update.message.reply_text(f"Ваш Telegram ID: {update.effective_user.id}")
    
    async def start(self, update, context):
        user_id = str(update.effective_user.id)
        user = get_user(user_id)
        if not user:
            save_user(user_id, {})
            user = get_user(user_id)
        
        sub_status = "❌ Нет подписки"
        if user["sub_end"]:
            end_date = datetime.fromisoformat(user["sub_end"])
            if end_date > datetime.now():
                days_left = (end_date - datetime.now()).days
                sub_status = "♾️ Навсегда" if days_left > 36500 else f"✅ {days_left} дн."
        
        keyboard = [
            [InlineKeyboardButton("💳 Купить подписку", callback_data="show_tariffs")],
            [InlineKeyboardButton("📝 Задать текст", callback_data="set")],
        ]
        if user["active"]:
            keyboard.append([InlineKeyboardButton("🔴 Выключить", callback_data="off")])
        else:
            keyboard.append([InlineKeyboardButton("🟢 Включить", callback_data="on")])
        if update.effective_user.id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin")])
        
        text = "🤖 Бот-автоответчик\n\n"
        text += f"Статус: {sub_status}\nТариф: {user.get('tariff', '-')}\n"
        text += f"Автоответ: {'🟢' if user['active'] else '🔴'}\n"
        text += f"Текст: «{user['reply_text']}»"
        
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def buy(self, update, context):
        keyboard = []
        for key, tariff in TARIFFS.items():
            keyboard.append([InlineKeyboardButton(f"{tariff['name']} - {tariff['price']}⭐", callback_data=f"buy_{key}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
        await update.message.reply_text("💳 Выберите тариф:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def set_reply(self, update, context):
        user_id = str(update.effective_user.id)
        if not context.args:
            await update.message.reply_text("📝 /set ТЕКСТ\nПример: /set Привет, я занят")
            return
        text = " ".join(context.args)
        user = get_user(user_id) or {}
        user["reply_text"] = text
        save_user(user_id, user)
        await update.message.reply_text(f"✅ Текст: «{text}»")
    
    async def turn_on(self, update, context):
        user_id = str(update.effective_user.id)
        user = get_user(user_id)
        if not user or not user["sub_end"]:
            await update.message.reply_text("❌ Купите подписку: /buy")
            return
        if datetime.fromisoformat(user["sub_end"]) < datetime.now():
            await update.message.reply_text("❌ Подписка истекла: /buy")
            return
        user["active"] = True
        save_user(user_id, user)
        await update.message.reply_text("🟢 Включен!")
    
    async def turn_off(self, update, context):
        user_id = str(update.effective_user.id)
        user = get_user(user_id) or {}
        user["active"] = False
        save_user(user_id, user)
        await update.message.reply_text("🔴 Выключен")
    
    async def status(self, update, context):
        user_id = str(update.effective_user.id)
        user = get_user(user_id)
        if not user or not user["sub_end"]:
            await update.message.reply_text("❌ Нет подписки")
            return
        end_date = datetime.fromisoformat(user["sub_end"])
        if end_date > datetime.now():
            days_left = (end_date - datetime.now()).days
            time_left = "Навсегда ♾️" if days_left > 36500 else f"{days_left} дн."
        else:
            time_left = "Истекла ❌"
        text = f"📊 Статус:\nПодписка: {time_left}\nТариф: {user.get('tariff', '-')}\n"
        text += f"Автоответ: {'🟢' if user['active'] else '🔴'}\nТекст: «{user['reply_text']}»"
        await update.message.reply_text(text)
    
    async def admin_panel(self, update, context):
        if update.effective_user.id != ADMIN_ID:
            return
        keyboard = [
            [InlineKeyboardButton("🎁 Подарить", callback_data="admin_gift")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
        ]
        await update.message.reply_text("⚙️ Админ-панель", reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def gift_sub(self, update, context):
        if update.effective_user.id != ADMIN_ID:
            return
        if len(context.args) < 2:
            await update.message.reply_text("/gift USER_ID ТАРИФ\nТарифы: 1, 10, 30, 90, 365, forever")
            return
        target_id, tariff_key = str(context.args[0]), context.args[1]
        if tariff_key not in TARIFFS:
            await update.message.reply_text("❌ Неверный тариф")
            return
        tariff = TARIFFS[tariff_key]
        sub_end = datetime.now() + timedelta(days=tariff["days"])
        save_user(target_id, {"sub_end": sub_end.isoformat(), "reply_text": "Я сейчас занят, отвечу позже", "active": True, "tariff": tariff["name"]})
        await update.message.reply_text(f"🎁 Подарок!\nПользователь: {target_id}\nТариф: {tariff['name']}\nДо: {sub_end.strftime('%d.%m.%Y')}")
        try:
            await context.bot.send_message(int(target_id), f"🎁 Вам подарили подписку!\nТариф: {tariff['name']}\nДо: {sub_end.strftime('%d.%m.%Y')}\n/set ВАШ ТЕКСТ")
        except:
            pass
    
    async def auto_reply(self, update, context):
        # Не отвечаем ботам
        if update.effective_user.is_bot:
            return
        
        user_id = str(update.effective_user.id)
        user = get_user(user_id)
        if not user or not user["active"]:
            return
        if user["sub_end"] and datetime.fromisoformat(user["sub_end"]) < datetime.now():
            user["active"] = False
            save_user(user_id, user)
            return
        await update.message.reply_text(user["reply_text"])
    
    async def handle_callback(self, update, context):
        query = update.callback_query
        await query.answer()
        user_id = str(query.from_user.id)
        
        if query.data == "show_tariffs":
            keyboard = [[InlineKeyboardButton(f"{t['name']} - {t['price']}⭐", callback_data=f"buy_{k}")] for k, t in TARIFFS.items()]
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
            await query.message.edit_text("💳 Выберите тариф:", reply_markup=InlineKeyboardMarkup(keyboard))
        
        elif query.data.startswith("buy_"):
            tariff_key = query.data.replace("buy_", "")
            tariff = TARIFFS[tariff_key]
            
            # Админу — бесплатно
            if query.from_user.id == ADMIN_ID:
                sub_end = datetime.now() + timedelta(days=tariff["days"])
                save_user(user_id, {
                    "sub_end": sub_end.isoformat(),
                    "reply_text": "Я сейчас занят, отвечу позже",
                    "active": True,
                    "tariff": tariff["name"]
                })
                end_text = "Навсегда ♾️" if tariff["days"] > 36500 else sub_end.strftime("%d.%m.%Y")
                await query.message.reply_text(
                    f"✅ Админ-доступ!\nТариф: {tariff['name']}\nАктивен до: {end_text}\n\n"
                    f"Автоответчик включен!\n/set ВАШ ТЕКСТ"
                )
                return
            
            # Остальным — платно
            await query.message.reply_invoice(
                title=f"Автоответчик - {tariff['name']}",
                description=f"Подписка на {tariff['name']}",
                payload=f"sub_{tariff_key}",
                currency="XTR",
                prices=[LabeledPrice(tariff["name"], tariff["price"])]
            )
        
        elif query.data == "admin":
            if query.from_user.id != ADMIN_ID:
                return
            kb = [[InlineKeyboardButton("🎁 Подарить", callback_data="admin_gift")],
                  [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
                  [InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")],
                  [InlineKeyboardButton("🔙 Назад", callback_data="back")]]
            await query.message.edit_text("⚙️ Админ-панель", reply_markup=InlineKeyboardMarkup(kb))
        
        elif query.data == "admin_gift":
            await query.message.edit_text("🎁 /gift USER_ID ТАРИФ\nТарифы: 1, 10, 30, 90, 365, forever",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin")]]))
        
        elif query.data == "admin_stats":
            users = get_all_users()
            total, active = len(users), sum(1 for u in users if u["sub_end"] and datetime.fromisoformat(u["sub_end"]) > datetime.now())
            await query.message.edit_text(f"📊 Всего: {total}\n✅ Активных: {active}\n❌ Неактивных: {total-active}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin")]]))
        
        elif query.data == "admin_users":
            users = get_all_users()[:20]
            text = "👥 Пользователи:\n\n"
            for u in users:
                sub = "❌"
                if u["sub_end"] and datetime.fromisoformat(u["sub_end"]) > datetime.now():
                    d = (datetime.fromisoformat(u["sub_end"]) - datetime.now()).days
                    sub = "♾️" if d > 36500 else f"✅ {d}д"
                text += f"`{u['user_id']}` | {sub} | {u.get('tariff', '-')}\n"
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="admin")]]), parse_mode="Markdown")
        
        elif query.data == "on":
            user = get_user(user_id)
            if not user or not user["sub_end"] or datetime.fromisoformat(user["sub_end"]) < datetime.now():
                await query.message.reply_text("❌ Купите подписку")
                return
            user["active"] = True
            save_user(user_id, user)
            await query.message.reply_text("🟢 Включен!")
        
        elif query.data == "off":
            user = get_user(user_id) or {}
            user["active"] = False
            save_user(user_id, user)
            await query.message.reply_text("🔴 Выключен")
        
        elif query.data == "set":
            await query.message.reply_text("/set ВАШ ТЕКСТ")
        
        elif query.data == "back":
            user = get_user(user_id)
            sub_status = "❌ Нет подписки"
            if user and user["sub_end"]:
                end_date = datetime.fromisoformat(user["sub_end"])
                if end_date > datetime.now():
                    d = (end_date - datetime.now()).days
                    sub_status = "♾️ Навсегда" if d > 36500 else f"✅ {d} дн."
            keyboard = [
                [InlineKeyboardButton("💳 Купить подписку", callback_data="show_tariffs")],
                [InlineKeyboardButton("📝 Задать текст", callback_data="set")],
            ]
            if user and user["active"]:
                keyboard.append([InlineKeyboardButton("🔴 Выключить", callback_data="off")])
            else:
                keyboard.append([InlineKeyboardButton("🟢 Включить", callback_data="on")])
            if query.from_user.id == ADMIN_ID:
                keyboard.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin")])
            text = f"🤖 Бот-автоответчик\n\nСтатус: {sub_status}\nТариф: {user.get('tariff', '-') if user else '-'}\n"
            text += f"Автоответ: {'🟢' if user and user['active'] else '🔴'}\nТекст: «{user['reply_text'] if user else ''}»"
            await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def pre_checkout(self, update, context):
        await update.pre_checkout_query.answer(ok=True)
    
    async def successful_payment(self, update, context):
        user_id = str(update.effective_user.id)
        tariff_key = update.message.successful_payment.invoice_payload.replace("sub_", "")
        tariff = TARIFFS.get(tariff_key, TARIFFS["30"])
        sub_end = datetime.now() + timedelta(days=tariff["days"])
        save_user(user_id, {"sub_end": sub_end.isoformat(), "reply_text": "Я сейчас занят, отвечу позже", "active": True, "tariff": tariff["name"]})
        end_text = "Навсегда ♾️" if tariff["days"] > 36500 else sub_end.strftime("%d.%m.%Y")
        await update.message.reply_text(f"✅ Оплата прошла!\nТариф: {tariff['name']}\nАктивен до: {end_text}\n\nАвтоответчик включен!\n/set ВАШ ТЕКСТ")
    
    def run(self):
        print("Бот запущен!")
        self.app.run_polling()

if __name__ == "__main__":
    bot = SimpleBot(TOKEN)
    bot.run()
