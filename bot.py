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

# Logging सेटअप
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

# ⏳ ५ दिवसांनंतर मेसेज डिलीट करणारे फंक्शन (५ दिवस = ४,३२,००० सेकंद)
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

    WELCOME_IMAGE_URL = "http://googleusercontent.com/image_collection/image_retrieval/10301050047407275243_0"

    welcome_caption = (
        f"🎉 **Welcome aboard, {user_name}!** 🎉\n\n"
        f"✅ **Your request to join has been approved successfully!**\n\n"
        f"🌟 We're thrilled to have you in our community!\n"
        f"Get ready for premium content, regular updates, and much more.\n\n"
        f"👇 *Click below to join our backup channel:* \n\n"
        f"⚠️ *Note: This welcome message will auto-delete in 5 days.*"
    )

    # 🔘 Inline Button (Join Backup Channel)
    keyboard = [[InlineKeyboardButton("🔗 Join Backup Channel", url=BACKUP_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        # १. रिक्वेस्ट स्वीकारणे
        await context.bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        print(f"Accepted {user_name} (ID: {user_id}) into Chat ID: {chat_id}")

        if user_id not in saved_users:
            saved_users.add(user_id)
            save_users(saved_users)

        # २. बटन आणि फोटोसोबत मेसेज पाठवणे
        sent_msg = await context.bot.send_photo(
            chat_id=user_id,
            photo=WELCOME_IMAGE_URL,
            caption=welcome_caption,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

        # ३. ५ दिवसांनंतर मेसेज ऑटो-डिलीट होण्यासाठी टॉस्क सुरू करणे
        asyncio.create_task(delete_msg_after_delay(context, user_id, sent_msg.message_id, 432000))

    except Exception as e:
        print(f"Failed to approve {user_id}: {e}")

# 📊 Admin Stats Command
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
    
    # Handlers (लिंक प्रोटेक्शन काढून टाकला आहे)
    app.add_handler(ChatJoinRequestHandler(auto_accept_request))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
