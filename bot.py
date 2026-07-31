import logging
import json
import os
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, 
    ChatJoinRequestHandler, 
    CommandHandler, 
    ContextTypes
)

# Render साठी Flask वेब सर्व्हर
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is Alive!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host='0.0.0.0', port=port)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

TOKEN = "8919865202:AAFfW5bDcrIypxKfJWiLJHfZRH4at8HiB_c"
ADMIN_ID = 6518835352  

DB_FILE = "users.json"
BACKUP_LINK = "https://t.me/+zBROkdncuC5iMzdl"

def load_users():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()

def save_users(users):
    with open(DB_FILE, "w") as f:
        json.dump(list(users), f)

saved_users = load_users()

# ⏳ ५ दिवसांनंतर मेसेज ऑटो-डिलीट करणारे फंक्शन
async def delete_msg_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay_seconds: int = 432000):
    await asyncio.sleep(delay_seconds)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        print(f"Deleted message {message_id} in chat {chat_id} after 5 days.")
    except Exception as e:
        print(f"Failed to delete message: {e}")

async def auto_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    chat_id = request.chat.id
    user_id = request.from_user.id
    user_name = request.from_user.first_name

    print(f"--> Received Join Request from {user_name} ({user_id}) for Chat {chat_id}")

    # 🌟 नवीन Welcome Message Caption
    welcome_caption = (
        f"🌟 **Welcome to the family, {user_name}!**\n\n"
        f"🔓 **Access Granted!** You're all set to dive in.\n"
        f"🍿 Stay tuned for amazing content ahead!\n\n"
        f"👇 *Click below to join our backup channel:*"
    )

    keyboard = [[InlineKeyboardButton("🔗 Join Backup Channel", url=BACKUP_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # १. जॉईन रिक्वेस्ट स्वीकारणे
    try:
        await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        print(f"SUCCESS: Approved request for {user_name}")
    except Exception as e:
        print(f"ERROR approving request: {e}")

    if user_id not in saved_users:
        saved_users.add(user_id)
        save_users(saved_users)

    # २. युझरला मेसेज पाठवणे
    try:
        sent_msg = await context.bot.send_message(
            chat_id=user_id,
            text=welcome_caption,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        print(f"SUCCESS: Sent Welcome Message to {user_id}")
        asyncio.create_task(delete_msg_after_delay(context, user_id, sent_msg.message_id, 432000))
    except Exception as e:
        print(f"ERROR sending welcome message to user {user_id}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in saved_users:
        saved_users.add(user_id)
        save_users(saved_users)
    await update.message.reply_text("👋 **Hello! Bot is Active and Ready.**\n\nWhen users request to join your channel, I will automatically accept them and send a welcome message!", parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    if sender_id != ADMIN_ID:
        return
    total_users = len(saved_users)
    await update.message.reply_text(f"📊 **Bot Statistics:**\n\n👤 Total Active Users: `{total_users}`", parse_mode="Markdown")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender_id = update.effective_user.id
    if sender_id != ADMIN_ID:
        await update.message.reply_text("You are not authorized to use this command!")
        return

    if not context.args:
        await update.message.reply_text("Please provide a message. Example:\n/broadcast Hello everyone!")
        return

    message_text = " ".join(context.args)
    total_users = len(saved_users)
    success = 0
    failed = 0

    await update.message.reply_text(f"Starting broadcast... Total users: {total_users}")

    for user in list(saved_users):
        try:
            await context.bot.send_message(chat_id=user, text=message_text)
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Broadcast finished!\nSuccess: {success}\nFailed: {failed}")

def main():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()

    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(ChatJoinRequestHandler(auto_accept_request))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
