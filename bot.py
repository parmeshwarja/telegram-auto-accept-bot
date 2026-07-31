import logging
from telegram import Update
from telegram.ext import Application, ChatJoinRequestHandler, ContextTypes

# Setup basic logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)

TOKEN = "8919865202:AAFfW5bDcrIypxKfJWiLJHfZRH4at8HiB_c"
async def auto_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Automatically approves join requests and sends a welcome message."""
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

        # 2. (Optional) Send a private welcome DM to the user
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Welcome {user_name}! Your join request has been approved automatically."
        )

    except Exception as e:
        print(f"Failed to approve {user_id}: {e}")

def main():
    # Build application
    app = Application.builder().token(TOKEN).build()

    # Add handler specifically for Chat Join Requests
    app.add_handler(ChatJoinRequestHandler(auto_accept_request))

    print("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__== "__main__":
    main()