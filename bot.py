import os
import sys
import time
import asyncio
import logging
from threading import Thread
from flask import Flask
from telegram import Update, BotCommand, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatJoinRequestHandler,
    ContextTypes,
    filters,
)
from telegram.error import Forbidden, BadRequest, RetryAfter

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION & DATABASE STUB ---
ADMIN_ID = 12345678  # तुमचा Admin Telegram ID टाका
TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")  # तुमचा Bot Token टाका

# डेटाबेस डिक्शनरी (तुमचा मूळ डेटाबेस असला तर तो इथे कनेक्ट करा)
USERS_DB = set()
SETTINGS_DB = {"backup_link": ""}
BROADCAST_DB = {}

def db_add_user(user_id):
    USERS_DB.add(user_id)

def db_get_all_users():
    return list(USERS_DB)

def db_get_setting(key):
    return SETTINGS_DB.get(key, "")

def db_set_setting(key, value):
    SETTINGS_DB[key] = value

def db_create_broadcast():
    b_id = int(time.time())
    BROADCAST_DB[b_id] = []
    return b_id

def db_save_broadcast_msg(b_id, user_id, msg_id):
    if b_id in BROADCAST_DB:
        BROADCAST_DB[b_id].append((user_id, msg_id))

def db_get_last_broadcast():
    if BROADCAST_DB:
        return list(BROADCAST_DB.keys())[-1]
    return None

def db_get_broadcast_msgs(b_id):
    return BROADCAST_DB.get(b_id, [])

def db_clear_broadcast_msgs(b_id):
    if b_id in BROADCAST_DB:
        del BROADCAST_DB[b_id]

# --- FLASK SERVER (Uptime / Health Check) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running perfectly!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_add_user(user_id)
    await update.message.reply_text("👋 **Welcome to the Bot!**", parse_mode="Markdown")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    msg = await update.message.reply_text("🏓 Pinging...")
    end_time = time.time()
    latency = round((end_time - start_time) * 1000)
    await msg.edit_text(f"🏓 **Pong!**\nLatency: `{latency}ms`", parse_mode="Markdown")

async def users_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total_users = len(db_get_all_users())
    await update.message.reply_text(f"👥 **Total Users:** `{total_users}`", parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total_users = len(db_get_all_users())
    backup = db_get_setting("backup_link") or "Not Set"
    await update.message.reply_text(f"📊 **Stats:**\nUsers: `{total_users}`\nBackup Link: {backup}", parse_mode="Markdown")

async def set_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/backup https://t.me/your_link`", parse_mode="Markdown")
        return
    link = context.args[0]
    db_set_setting("backup_link", link)
    await update.message.reply_text(f"✅ **Backup Link successfully set to:**\n{link}", parse_mode="Markdown")

async def set_welcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("⚙️ Send the new welcome message text/photo.")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("⚠️ Usage: `/broadcast Your message here`", parse_mode="Markdown")
        return
    text = " ".join(context.args)
    all_users = db_get_all_users()
    for user in all_users:
        try:
            await context.bot.send_message(chat_id=user, text=text)
        except Exception:
            pass
    await update.message.reply_text("✅ Text Broadcast completed!")

async def handle_welcome_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pass

# --- AUTO ACCEPT CHAT JOIN REQUEST (FIXED) ---
async def auto_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_join_request = update.chat_join_request
    user_id = chat_join_request.from_user.id
    db_add_user(user_id)  # ID सेव्ह केली

    try:
        # १. चॅनेल जॉईन रिक्वेस्ट एक्सेप्ट करा
        await chat_join_request.approve()
        logger.info(f"Approved join request for user: {user_id}")
        
        # २. बॅकअप लिंक तपासा
        backup_link = db_get_setting("backup_link")
        
        if backup_link:
            reply_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]
            ])
            text = "✅ **Your join request has been approved!**\n\nJoin our backup channel to stay updated:"
            await context.bot.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="Markdown"
            )
            logger.info(f"Sent backup link to user: {user_id}")
        else:
            # बॅकअप लिंक सेट नसली तरी युझरला मेसेज पाठवणे
            await context.bot.send_message(
                chat_id=user_id,
                text="✅ **Your join request has been approved!** Welcome!",
                parse_mode="Markdown"
            )
            logger.warning("Backup link was not set in DB!")
            
    except Exception as e:
        logger.error(f"Error in auto_accept_request for {user_id}: {e}")

# --- BROADCAST HANDLERS ---
async def forward_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("⚠️ **Forward/Reply to a message and type /fbroadcast**", parse_mode="Markdown")
        return

    replied_msg = update.message.reply_to_message
    all_users = db_get_all_users()
    total = len(all_users)
    success, failed = 0, 0

    b_id = db_create_broadcast()
    status_msg = await update.message.reply_text(f"📢 **Forward Broadcast Started.....**\nProgress: 0/{total}", parse_mode="Markdown")
    backup_link = db_get_setting("backup_link")
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Join Backup Channel", url=backup_link)]]) if backup_link else None

    for i, user in enumerate(all_users, start=1):
        sent = False
        for attempt in range(3):
            try:
                if replied_msg.photo:
                    m = await context.bot.send_photo(
                        chat_id=user,
                        photo=replied_msg.photo[-1].file_id,
                        caption=replied_msg.caption if replied_msg.caption else "",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                elif replied_msg.text:
                    m = await context.bot.send_message(
                        chat_id=user,
                        text=replied_msg.text,
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
                db_save_broadcast_msg(b_id, user, m.message_id)
                success += 1
                sent = True
                break
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                continue
            except (Forbidden, BadRequest):
                break
            except Exception:
                await asyncio.sleep(1)
                continue

        if not sent:
            failed += 1

        await asyncio.sleep(0.08)

        if i % 50 == 0 or i == total:
            try:
                await status_msg.edit_text(
                    f"📢 **Sending.....**\n{i}/{total} Users\n\n✅ Success: {success}\n❌ Failed: {failed}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await status_msg.edit_text(
        f"✅ **Forward Broadcast Completed!**\n\n✅ Success : {success}\n❌ Failed : {failed}\n\n🗑️ *Use /delete to delete this broadcast manually.*",
        parse_mode="Markdown"
    )

async def delete_last_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    b_id = db_get_last_broadcast()
    if not b_id:
        await update.message.reply_text("❌ **No active broadcast found to delete.**", parse_mode="Markdown")
        return

    msgs = db_get_broadcast_msgs(b_id)
    total = len(msgs)
    deleted = 0

    status_msg = await update.message.reply_text(f"⏳ **Deleting Last Broadcast.....**\nProgress: 0/{total}", parse_mode="Markdown")

    for user_id, msg_id in msgs:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            deleted += 1
        except Exception:
            pass
        await asyncio.sleep(0.05)

    db_clear_broadcast_msgs(b_id)
    await status_msg.edit_text(f"✅ **Deleted Broadcast from {deleted}/{total} users successfully!**", parse_mode="Markdown")

async def restart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("🔄 **Restarting Bot.....**", parse_mode="Markdown")
    os.execl(sys.executable, sys.executable, *sys.argv)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    help_text = (
        "🛠️ **Admin Panel & Commands:**\n\n"
        "• /stats - View Statistics & Config\n"
        "• /users - Total User Count\n"
        "• /ping - Response Latency\n"
        "• /backup <link> - Change Backup Link\n"
        "• /setwelcome - Change Welcome Msg/Photo\n"
        "• /broadcast <text> - Send Text Broadcast\n"
        "• /fbroadcast - Forward Broadcast\n"
        "• /delete - Manually Delete Last Broadcast Now\n"
        "• /restart - Reboot Bot\n"
        "• /help - Show Help"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def post_init(application: Application):
    commands = [
        BotCommand("stats", "View Bot Statistics & Config"),
        BotCommand("users", "Check Total User Count"),
        BotCommand("ping", "Response Latency"),
        BotCommand("backup", "Change Backup Channel Link"),
        BotCommand("setwelcome", "Set New Welcome Msg/Photo"),
        BotCommand("broadcast", "Send Text Broadcast"),
        BotCommand("fbroadcast", "Send Forward Post Broadcast"),
        BotCommand("delete", "Delete Last Broadcast Now"),
        BotCommand("restart", "Reboot Bot Server"),
        BotCommand("help", "Show Admin Help Menu"),
    ]
    await application.bot.set_my_commands(commands)

def main():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("users", users_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("backup", set_backup))
    app.add_handler(CommandHandler("setwelcome", set_welcome_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("fbroadcast", forward_broadcast))
    app.add_handler(CommandHandler("delete", delete_last_broadcast))
    app.add_handler(CommandHandler("restart", restart_cmd))
    app.add_handler(CommandHandler("help", help_cmd))

    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_welcome_input))
    app.add_handler(ChatJoinRequestHandler(auto_accept_request))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
    
