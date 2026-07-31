import logging
import os
import sys
import asyncio
import sqlite3
import time
from datetime import datetime
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    ChatJoinRequestHandler, 
    CommandHandler, 
    ContextTypes,
    MessageHandler,
    filters
)
from telegram.error import TelegramError, Forbidden, BadRequest, RetryAfter

# Environment Variables
TOKEN = os.getenv("BOT_TOKEN", "8919865202:AAFfW5bDcrIypxKfJWiLJHfZRH4at8HiB_c")
ADMIN_ID = int(os.getenv("ADMIN_ID", "6518835352"))

# Flask Web Server
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is Alive and Running with SQLite3!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

# 🗄️ SQLite Database Setup
DB_FILE = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            joined_at TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Default Values setup
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('backup_link', 'https://t.me/+zBROkdncuC5iMzdl'))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('welcome_text', "🌟 **Welcome to the family, {name}!**\n\n🔓 **Access Granted!** You're all set to dive in.\n🍿 Stay tuned for amazing content ahead!"))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', ('welcome_photo', ''))
    conn.commit()
    conn.close()

init_db()

def db_get_setting(key):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else ""

def db_set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def db_add_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('INSERT OR IGNORE INTO users (user_id, joined_at) VALUES (?, ?)', (user_id, now))
    conn.commit()
    conn.close()

def db_remove_user(user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def db_get_all_users():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def db_get_user_count():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

# State for /setwelcome
AWAITING_WELCOME = {}

# 🤝 Auto Accept Request Handler
async def auto_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    user_id = request.from_user.id
    user_name = request.from_user.first_name

    # १. Approve Request
    try:
        await context.bot.approve_chat_join_request(chat_id=request.chat.id, user_id=user_id)
    except Exception as e:
        print(f"Error approving request: {e}")

    # Database मध्ये User Save करणे
    db_add_user(user_id)

    # २. मेसेज तयार करणे
    backup_link = db_get_setting("backup_link")
    welcome_text = db_get_setting("welcome_text").format(name=user_name)
    welcome_photo = db_get_setting("welcome_photo")

    keyboard = [[InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # ३. मेसेज थेट USER च्या Private DM मध्ये पाठवणे (चॅनेलवर नाही)
    try:
        if welcome_photo:
            await context.bot.send_photo(
                chat_id=user_id,  # 👈 इथे user_id दिल्यामुळे मेसेज डायरेक्ट युझरला जाईल
                photo=welcome_photo,
                caption=welcome_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,  # 👈 इथे user_id दिल्यामुळे मेसेज डायरेक्ट युझरला जाईल
                text=welcome_text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
    except Exception as e:
        print(f"Could not send PM to user {user_id}: {e}")

# 🎮 Admin Commands
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_add_user(user_id)
    await update.message.reply_text("👋 **Hello! Bot is Active and Ready.**", parse_mode="Markdown")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    msg = await update.message.reply_text("⚡ Pinging...")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000)
    await msg.edit_text(f"🏓 **Pong!** Response Time: `{latency} ms`", parse_mode="Markdown")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    count = db_get_user_count()
    await update.message.reply_text(f"👥 **Total Users :** `{count:,}`", parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    count = db_get_user_count()
    backup_link = db_get_setting("backup_link")
    await update.message.reply_text(
        f"📊 **Bot Analytics & Settings:**\n\n"
        f"👥 Total Users: `{count:,}`\n"
        f"🔗 Backup Link: {backup_link}\n"
        f"🗄️ Database: `SQLite3`\n"
        f"🟢 Status: `Online (24/7)`", 
        parse_mode="Markdown"
    )

async def set_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/backup https://t.me/yourlink`", parse_mode="Markdown")
        return
    new_link = context.args[0]
    db_set_setting("backup_link", new_link)
    await update.message.reply_text(f"✅ **Backup Link Updated Successfully!**\n\n🔗 New Link: {new_link}", parse_mode="Markdown")

async def set_welcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    AWAITING_WELCOME[ADMIN_ID] = True
    await update.message.reply_text(
        "📝 **Send me the new Welcome Message now.**\n\n"
        "• You can send Text, Photo, or GIF.\n"
        "• Use `{name}` in text to auto-tag the user.\n"
        "• Type /cancel to abort.",
        parse_mode="Markdown"
    )

async def handle_welcome_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID or not AWAITING_WELCOME.get(ADMIN_ID):
        return

    if update.message.text and update.message.text.startswith("/cancel"):
        AWAITING_WELCOME[ADMIN_ID] = False
        await update.message.reply_text("❌ Welcome message update cancelled.")
        return

    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
        caption = update.message.caption if update.message.caption else ""
        db_set_setting("welcome_photo", photo_id)
        db_set_setting("welcome_text", caption)
    elif update.message.text:
        db_set_setting("welcome_photo", "")
        db_set_setting("welcome_text", update.message.text)

    AWAITING_WELCOME[ADMIN_ID] = False
    await update.message.reply_text("✅ **New Welcome Message Saved Successfully!**", parse_mode="Markdown")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/broadcast Your message here`", parse_mode="Markdown")
        return

    message_text = " ".join(context.args)
    all_users = db_get_all_users()
    total = len(all_users)
    success, failed = 0, 0

    status_msg = await update.message.reply_text(f"🚀 **Broadcast Started...**\nProgress: `0/{total}`", parse_mode="Markdown")

    for i, user in enumerate(all_users, start=1):
        try:
            await context.bot.send_message(chat_id=user, text=message_text, parse_mode="Markdown")
            success += 1
        except (Forbidden, BadRequest):
            db_remove_user(user)
            failed += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await context.bot.send_message(chat_id=user, text=message_text, parse_mode="Markdown")
                success += 1
            except Exception:
                db_remove_user(user)
                failed += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.08)

        if i % 50 == 0 or i == total:
            try:
                await status_msg.edit_text(
                    f"🚀 **Sending...**\n"
                    f"`{i}/{total}` Users\n\n"
                    f"✅ Success: `{success}`\n"
                    f"❌ Failed/Removed: `{failed}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await status_msg.edit_text(
        f"✅ **Broadcast Completed!**\n\n"
        f"✅ Success : `{success}`\n"
        f"❌ Failed/Removed Dead Users : `{failed}`",
        parse_mode="Markdown"
    )

async def forward_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ **Forward/Reply to a message and type `/fbroadcast`**", parse_mode="Markdown")
        return

    replied_msg = update.message.reply_to_message
    all_users = db_get_all_users()
    total = len(all_users)
    success, failed = 0, 0

    status_msg = await update.message.reply_text(f"🚀 **Forward Broadcast Started...**\nProgress: `0/{total}`", parse_mode="Markdown")
    backup_link = db_get_setting("backup_link")
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]])

    for i, user in enumerate(all_users, start=1):
        try:
            if replied_msg.photo:
                await context.bot.send_photo(
                    chat_id=user,
                    photo=replied_msg.photo[-1].file_id,
                    caption=replied_msg.caption if replied_msg.caption else "",
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            elif replied_msg.text:
                await context.bot.send_message(
                    chat_id=user,
                    text=replied_msg.text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )
            success += 1
        except (Forbidden, BadRequest):
            db_remove_user(user)
            failed += 1
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                if replied_msg.photo:
                    await context.bot.send_photo(chat_id=user, photo=replied_msg.photo[-1].file_id, caption=replied_msg.caption or "", reply_markup=reply_markup, parse_mode="Markdown")
                elif replied_msg.text:
                    await context.bot.send_message(chat_id=user, text=replied_msg.text, reply_markup=reply_markup, parse_mode="Markdown")
                success += 1
            except Exception:
                db_remove_user(user)
                failed += 1
        except Exception:
            failed += 1

        await asyncio.sleep(0.08)

        if i % 50 == 0 or i == total:
            try:
                await status_msg.edit_text(
                    f"🚀 **Sending...**\n"
                    f"`{i}/{total}` Users\n\n"
                    f"✅ Success: `{success}`\n"
                    f"❌ Failed: `{failed}`",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await status_msg.edit_text(
        f"✅ **Broadcast Completed!**\n\n"
        f"✅ Success : `{success}`\n"
        f"❌ Failed : `{failed}`",
        parse_mode="Markdown"
    )

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("🔄 **Restarting Bot...**", parse_mode="Markdown")
    os.execl(sys.executable, sys.executable, *sys.argv)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    help_text = (
        "🛠️ **Admin Panel & Commands:**\n\n"
        "• `/stats` - View Statistics & Config\n"
        "• `/users` - Total User Count\n"
        "• `/ping` - Response Latency\n"
        "• `/backup <link>` - Change Backup Link\n"
        "• `/setwelcome` - Change Welcome Msg/Photo\n"
        "• `/broadcast <text>` - Send Text Broadcast\n"
        "• `/fbroadcast` - Forward Broadcast (Reply to post)\n"
        "• `/restart` - Reboot Bot\n"
        "• `/help` - Show Help"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

def main():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("backup", set_backup))
    app.add_handler(CommandHandler("setwelcome", set_welcome_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("fbroadcast", forward_broadcast))
    app.add_handler(CommandHandler("restart", restart_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_welcome_input))
    app.add_handler(ChatJoinRequestHandler(auto_accept_request))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
