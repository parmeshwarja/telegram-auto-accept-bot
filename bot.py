import logging
import json
import os
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, ChatJoinRequestHandler, CommandHandler, ContextTypes

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

async def auto_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    request = update.chat_join_request
    chat_id = request.chat.id
    user_id = request.from_user.id
    user_name = request.from_user.first_name  # युझरचे नाव ऑटोमॅटिक घेईल

    # 🎨 आकर्षक Welcome Image URL
    WELCOME_IMAGE_URL = "[attachment_0](attachment)"

    # ✨ Attractive English Welcome Message
    welcome_caption = (
        f"🎉 Welcome aboard, {user_name}! 🎉\n\n"
        f"✅ Your request to join has been approved successfully!\n\n"
        f"🌟 We're thrilled to have you in our community!\n"
        f"Get ready for premium content, regular updates, and much more.\n\n"
        f"👉 *Enjoy your time here!*"
    )

    try:
        # १. जॉईन रिक्वेस्ट स्वीकारणे
        await context.bot.approve_chat_join_request(
            chat_id=chat_id, 
            user_id=user_id
        )
        print(f"Accepted {user_name} (ID: {user_id}) into Chat ID: {chat_id}")

        # २. युझर ID सेव्ह करणे
        if user_id not in saved_users:
            saved_users.add(user_id)
            save_users(saved_users)

        # ३. आकर्षक Welcome Photo सोबत मेसेज पाठवणे
        await context.bot.send_photo(
            chat_id=user_id,
            photo=WELCOME_IMAGE_URL,
            caption=welcome_caption,
            parse_mode="Markdown"
        )

    except Exception as e:
        print(f"Failed to approve {user_id}: {e}")

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
    app.add_handler(ChatJoinRequestHandler(auto_accept_request))
    app.add_handler(CommandHandler("broadcast", broadcast))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
