import logging
import json
import os
import asyncio
from telegram import Update
from telegram.ext import Application, ChatJoinRequestHandler, CommandHandler, ContextTypes

# Setup basic logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

# १. तुमचा Bot Token
TOKEN = "8919865202:AAFfW5bDcrIypxKfJWiLJHfZRH4at8HiB_c"

# २. तुमचा Numeric Telegram Admin ID
ADMIN_ID = 6518835352  

DB_FILE = "users.json"

def load_users():
    """सेव्ह केलेले युझर्स लोड करा"""
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r") as f:
            try:
                return set(json.load(f))
            except json.JSONDecodeError:
                return set()
    return set()

def save_users(users):
    """नवीन युझर फाईलमध्ये सेव्ह करा"""
    with open(DB_FILE, "w") as f:
        json.dump(list(users), f)

saved_users = load_users()

async def auto_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically approves join requests, saves user ID, and sends welcome message."""
    request = update.chat_join_request
    chat_id = request.chat.id
    user_id = request.from_user.id
    user_name = request.from_user.first_name

    try:
        # 1. Approve the join request
        await context.bot.approve_chat_join_request(
            chat_id=chat_id, 
            user_id=user_id
        )
        print(f"Accepted {user_name} (ID: {user_id}) into Chat ID: {chat_id}")

        # 2. Save user ID for future broadcast messages
        if user_id not in saved_users:
            saved_users.add(user_id)
            save_users(saved_users)

        # 3. Send a private welcome DM to the user
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Welcome {user_name}! Your join request has been approved automatically."
        )

    except Exception as e:
        print(f"Failed to approve {user_id}: {e}")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all accepted users (Admin only)."""
    sender_id = update.effective_user.id

    # Admin Verification
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
            await asyncio.sleep(0.05)  # Avoid Telegram ban rate limits
        except Exception:
            failed += 1

    await update.message.reply_text(f"✅ Broadcast finished!\nSuccess: {success}\nFailed: {failed}")

def main():
    # Build application
    app = Application.builder().token(TOKEN).build()

    # Add Handlers
    app.add_handler(ChatJoinRequestHandler(auto_accept_request))
    app.add_handler(CommandHandler("broadcast", broadcast))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
