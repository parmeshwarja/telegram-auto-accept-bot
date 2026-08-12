import os
import sys
import asyncio
from threading import Thread
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

# --- CONFIGURATION & DATABASE FUNCTIONS ---
# टीप: तुमचे डेटाबेस फंक्शन्स (db_*) आधीच जिथे डिझाइन केले आहेत, तिथून कॉल होतील.

ADMIN_ID = 12345678  # तुमचा Admin Telegram ID इथे टाका
TOKEN = "YOUR_BOT_TOKEN_HERE"  # तुमचा Bot Token इथे टाका


# --- HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db_add_user(user_id)  # ID नेहमी डेटाबेसमध्ये सेव्ह राहील
    await update.message.reply_text("👋 Welcome to the Bot!")


async def auto_accept_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_join_request = update.chat_join_request
    user_id = chat_join_request.from_user.id
    
    # युझर डेटाबेसमध्ये सेव्ह करा
    db_add_user(user_id)

    try:
        # रिक्वेस्ट एक्सेप्ट करा
        await chat_join_request.approve()
        
        # बॅकअप लिंक पाठवा (ही लिंक किंवा मेसेज ५ दिवसांनी किंवा कधीच ऑटो-डिलीट होणार नाही)
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
    except Exception as e:
        print(f"Error in auto_accept_request: {e}")


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
        max_retries = 3  # मेसेज फेल्ड झाल्यास ३ वेळा री-ट्राय करेल

        for attempt in range(max_retries):
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
                break  # मेसेज यशस्वीरित्या गेला

            except RetryAfter as e:
                await asyncio.sleep(e.retry_after)
                continue

            except (Forbidden, BadRequest):
                # ब्लॉक केलेल्या किंवा डिलीट अकाउंट्सची ID डेटाबेसमध्ये सेव्हच राहील
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
                    f"📢 **Sending.....**\n"
                    f"{i}/{total} Users\n\n"
                    f"✅ Success: {success}\n"
                    f"❌ Failed: {failed}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    # ऑटो डिलीटचा कोड काढून टाकला आहे
    await status_msg.edit_text(
        f"✅ **Forward Broadcast Completed!**\n\n"
        f"✅ Success : {success}\n"
        f"❌ Failed : {failed}\n\n"
        f"🗑️ *Use /delete to delete this broadcast manually if needed.*",
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
    # Flask Servet चलावण्यासाठी (आवश्यक असल्यास)
    try:
        t = Thread(target=run_flask)
        t.daemon = True
        t.start()
    except NameError:
        pass

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # Handlers Registration
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
        
