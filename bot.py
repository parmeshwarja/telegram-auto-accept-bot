import logging
import os
import sys
import asyncio
import sqlite3
import time
import json

from datetime import datetime
from threading import Thread

from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from telegram.ext import (
    Application,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from telegram.error import (
    TelegramError,
    Forbidden,
    BadRequest,
    RetryAfter,
)


# =========================================================
# CONFIG
# =========================================================

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing!")

ADMIN_ID = int(os.getenv("ADMIN_ID", "6518835352"))

DB_FILE = "bot_data.db"

MAX_BROADCAST_RETRIES = 5


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# FLASK WEB SERVER
# =========================================================

web_app = Flask(__name__)


@web_app.route("/")
def home():
    return "Bot is Alive and Running with SQLite3!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))

    web_app.run(
        host="0.0.0.0",
        port=port
    )


# =========================================================
# DATABASE
# =========================================================

def get_db():
    conn = sqlite3.connect(
        DB_FILE,
        timeout=30
    )

    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")

    return conn


def init_db():

    conn = get_db()
    cursor = conn.cursor()

    # -----------------------------------------------------
    # USERS
    # IMPORTANT:
    # User IDs are NEVER deleted.
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            joined_at TEXT
        )
    """)

    # -----------------------------------------------------
    # SETTINGS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # -----------------------------------------------------
    # BROADCASTS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS broadcasts (
            broadcast_id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT
        )
    """)

    # -----------------------------------------------------
    # BROADCAST MESSAGES
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS broadcast_messages (
            broadcast_id INTEGER,
            user_id INTEGER,
            message_id INTEGER
        )
    """)

    # -----------------------------------------------------
    # CHANNELS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id INTEGER PRIMARY KEY,
            title TEXT,
            username TEXT,
            added_at TEXT,
            request_accepted INTEGER DEFAULT 0,
            last_action TEXT
        )
    """)

    # -----------------------------------------------------
    # USER <-> CHANNEL
    #
    # Same channel can be associated with multiple users.
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_channels (
            user_id INTEGER,
            channel_id INTEGER,
            added_at TEXT,
            PRIMARY KEY (user_id, channel_id)
        )
    """)

    # -----------------------------------------------------
    # INVITE LINKS
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channel_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            owner_user_id INTEGER,
            invite_link TEXT UNIQUE,
            created_at TEXT
        )
    """)

    # -----------------------------------------------------
    # DEFAULT SETTINGS
    # -----------------------------------------------------

    cursor.execute(
        """
        INSERT OR IGNORE INTO settings
        (key, value)
        VALUES (?, ?)
        """,
        (
            "backup_link",
            "https://t.me/+zBROkdncuC5iMzdl"
        )
    )

    cursor.execute(
        """
        INSERT OR IGNORE INTO settings
        (key, value)
        VALUES (?, ?)
        """,
        (
            "welcome_text",
            "🌟 **Welcome to the family, {name}!**\n\n"
            "🔓 **Access Granted!** You're all set to dive in.\n"
            "🍿 Stay tuned for amazing content ahead!"
        )
    )

    cursor.execute(
        """
        INSERT OR IGNORE INTO settings
        (key, value)
        VALUES (?, ?)
        """,
        (
            "welcome_photo",
            ""
        )
    )

    conn.commit()

    # -----------------------------------------------------
    # OLD users.json MIGRATION
    # -----------------------------------------------------

    if os.path.exists("users.json"):

        try:

            with open(
                "users.json",
                "r",
                encoding="utf-8"
            ) as f:

                old_users = json.load(f)

            now = datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            for user_id in old_users:

                try:

                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO users
                        (user_id, joined_at)
                        VALUES (?, ?)
                        """,
                        (
                            int(user_id),
                            now
                        )
                    )

                except Exception:
                    pass

            conn.commit()

            logger.info(
                "Migrated %s old users.",
                len(old_users)
            )

        except Exception as e:

            logger.error(
                "Migration error: %s",
                e
            )

    conn.close()


init_db()


# =========================================================
# USER DATABASE FUNCTIONS
# =========================================================

def db_add_user(user_id):

    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        INSERT OR IGNORE INTO users
        (user_id, joined_at)
        VALUES (?, ?)
        """,
        (
            user_id,
            now
        )
    )

    conn.commit()
    conn.close()


def db_get_all_users():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id
        FROM users
        ORDER BY joined_at ASC
        """
    )

    rows = cursor.fetchall()

    conn.close()

    return [
        row[0]
        for row in rows
    ]


def db_get_user_count():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count


# IMPORTANT:
# There is intentionally NO db_remove_user().
# User IDs are permanently stored.


# =========================================================
# SETTINGS
# =========================================================

def db_get_setting(key):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        (key,)
    )

    row = cursor.fetchone()

    conn.close()

    return row[0] if row else ""


def db_set_setting(key, value):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        REPLACE INTO settings
        (key, value)
        VALUES (?, ?)
        """,
        (
            key,
            value
        )
    )

    conn.commit()
    conn.close()


# =========================================================
# BROADCAST DATABASE
# =========================================================

def db_create_broadcast():

    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        INSERT INTO broadcasts
        (created_at)
        VALUES (?)
        """,
        (now,)
    )

    broadcast_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return broadcast_id


def db_save_broadcast_msg(
    broadcast_id,
    user_id,
    message_id
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO broadcast_messages
        (broadcast_id, user_id, message_id)
        VALUES (?, ?, ?)
        """,
        (
            broadcast_id,
            user_id,
            message_id
        )
    )

    conn.commit()
    conn.close()


def db_get_last_broadcast():

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT broadcast_id
        FROM broadcasts
        ORDER BY broadcast_id DESC
        LIMIT 1
        """
    )

    row = cursor.fetchone()

    conn.close()

    return row[0] if row else None


def db_get_broadcast_msgs(broadcast_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT user_id, message_id
        FROM broadcast_messages
        WHERE broadcast_id = ?
        """,
        (broadcast_id,)
    )

    rows = cursor.fetchall()

    conn.close()

    return rows


def db_clear_broadcast_msgs(broadcast_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM broadcast_messages
        WHERE broadcast_id = ?
        """,
        (broadcast_id,)
    )

    cursor.execute(
        """
        DELETE FROM broadcasts
        WHERE broadcast_id = ?
        """,
        (broadcast_id,)
    )

    conn.commit()
    conn.close()


# =========================================================
# CHANNEL DATABASE
# =========================================================

def db_add_channel(
    user_id,
    channel_id,
    title,
    username
):

    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Main channel information
    cursor.execute(
        """
        INSERT INTO channels
        (
            channel_id,
            title,
            username,
            added_at,
            request_accepted,
            last_action
        )
        VALUES (?, ?, ?, ?, 0, ?)

        ON CONFLICT(channel_id)
        DO UPDATE SET
            title = excluded.title,
            username = excluded.username
        """,
        (
            channel_id,
            title,
            username or "",
            now,
            now
        )
    )

    # User-channel association
    cursor.execute(
        """
        INSERT OR IGNORE INTO user_channels
        (
            user_id,
            channel_id,
            added_at
        )
        VALUES (?, ?, ?)
        """,
        (
            user_id,
            channel_id,
            now
        )
    )

    conn.commit()
    conn.close()


def db_get_user_channels(user_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            c.channel_id,
            c.title,
            c.username,
            c.request_accepted
        FROM channels c
        INNER JOIN user_channels uc
            ON c.channel_id = uc.channel_id
        WHERE uc.user_id = ?
        ORDER BY uc.added_at DESC
        """,
        (user_id,)
    )

    rows = cursor.fetchall()

    conn.close()

    return rows


def db_get_channel(channel_id):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            channel_id,
            title,
            username,
            request_accepted,
            last_action
        FROM channels
        WHERE channel_id = ?
        """,
        (channel_id,)
    )

    row = cursor.fetchone()

    conn.close()

    return row


def db_channel_belongs_to_user(
    user_id,
    channel_id
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM user_channels
        WHERE user_id = ?
        AND channel_id = ?
        """,
        (
            user_id,
            channel_id
        )
    )

    result = cursor.fetchone()

    conn.close()

    return result is not None


def db_increment_request(channel_id):

    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        UPDATE channels
        SET request_accepted = request_accepted + 1,
            last_action = ?
        WHERE channel_id = ?
        """,
        (
            now,
            channel_id
        )
    )

    conn.commit()
    conn.close()


def db_save_channel_link(
    channel_id,
    owner_user_id,
    invite_link
):

    conn = get_db()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        INSERT OR IGNORE INTO channel_links
        (
            channel_id,
            owner_user_id,
            invite_link,
            created_at
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            channel_id,
            owner_user_id,
            invite_link,
            now
        )
    )

    conn.commit()
    conn.close()


def db_get_user_links(
    user_id,
    channel_id
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            invite_link,
            created_at
        FROM channel_links
        WHERE owner_user_id = ?
        AND channel_id = ?
        ORDER BY id DESC
        """,
        (
            user_id,
            channel_id
        )
    )

    rows = cursor.fetchall()

    conn.close()

    return rows


def db_get_link_count(
    user_id,
    channel_id
):

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM channel_links
        WHERE owner_user_id = ?
        AND channel_id = ?
        """,
        (
            user_id,
            channel_id
        )
    )

    count = cursor.fetchone()[0]

    conn.close()

    return count


# =========================================================
# STATE
# =========================================================

AWAITING_WELCOME = {}
AWAITING_CHANNEL = {}


# =========================================================
# MAIN MENU
# =========================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                "➕ Add channel",
                "📚 My channels"
            ]
        ],
        resize_keyboard=True
    )


# =========================================================
# AUTO ACCEPT JOIN REQUEST
# =========================================================

async def auto_accept_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    request = update.chat_join_request

    if not request:
        return

    user_id = request.from_user.id
    user_name = request.from_user.first_name or "User"

    channel_id = request.chat.id

    # -----------------------------------------------------
    # ALWAYS SAVE USER ID
    # -----------------------------------------------------

    db_add_user(user_id)

    # -----------------------------------------------------
    # ACCEPT REQUEST
    # -----------------------------------------------------

    try:

        await context.bot.approve_chat_join_request(
            chat_id=channel_id,
            user_id=user_id
        )

        # Update channel counter if registered
        db_increment_request(channel_id)

    except Exception as e:

        logger.error(
            "Error approving request: %s",
            e
        )

        return

    # -----------------------------------------------------
    # WELCOME MESSAGE
    # NO AUTO DELETE
    # -----------------------------------------------------

    backup_link = db_get_setting(
        "backup_link"
    )

    welcome_text = db_get_setting(
        "welcome_text"
    )

    try:

        welcome_text = welcome_text.format(
            name=user_name
        )

    except Exception:

        pass

    reply_markup = None

    if backup_link:

        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔗 Join Backup Channel",
                        url=backup_link
                    )
                ]
            ]
        )

    welcome_photo = db_get_setting(
        "welcome_photo"
    )

    try:

        if welcome_photo:

            try:

                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=welcome_photo,
                    caption=welcome_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

            except TelegramError:

                # Markdown error fallback
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=welcome_photo,
                    caption=welcome_text,
                    reply_markup=reply_markup
                )

        else:

            try:

                await context.bot.send_message(
                    chat_id=user_id,
                    text=welcome_text,
                    reply_markup=reply_markup,
                    parse_mode="Markdown"
                )

            except TelegramError:

                # Markdown error fallback
                await context.bot.send_message(
                    chat_id=user_id,
                    text=welcome_text,
                    reply_markup=reply_markup
                )

    except Exception as e:

        logger.error(
            "Could not send welcome message to %s: %s",
            user_id,
            e
        )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    # NEVER remove this
    db_add_user(user_id)

    await update.message.reply_text(
        "👋 Welcome to the bot!",
        reply_markup=main_keyboard()
    )


# =========================================================
# PING
# =========================================================

async def ping(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    start_time = time.time()

    msg = await update.message.reply_text(
        "⚡ Pinging..."
    )

    latency = round(
        (time.time() - start_time) * 1000
    )

    await msg.edit_text(
        f"🏓 Pong! Response Time: {latency} ms"
    )


# =========================================================
# USERS
# =========================================================

async def users_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    count = db_get_user_count()

    await update.message.reply_text(
        f"👥 Total Users: {count:,}"
    )


# =========================================================
# STATS
# =========================================================

async def stats(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    count = db_get_user_count()

    backup_link = db_get_setting(
        "backup_link"
    )

    await update.message.reply_text(
        f"📊 Bot Analytics\n\n"
        f"👥 Total Users: {count:,}\n"
        f"🔗 Backup Link: {backup_link}\n"
        f"🗄️ Database: SQLite3\n"
        f"🔄 Broadcast Retry: Maximum {MAX_BROADCAST_RETRIES}\n"
        f"🗑️ Auto Delete: OFF\n"
        f"🟢 Status: Online"
    )


# =========================================================
# SET BACKUP
# =========================================================

async def set_backup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:

        await update.message.reply_text(
            "⚠️ Usage:\n"
            "/backup https://t.me/yourlink"
        )

        return

    new_link = context.args[0]

    db_set_setting(
        "backup_link",
        new_link
    )

    await update.message.reply_text(
        f"✅ Backup Link Updated!\n\n"
        f"🔗 {new_link}"
    )


# =========================================================
# SET WELCOME
# =========================================================

async def set_welcome_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    AWAITING_WELCOME[ADMIN_ID] = True

    await update.message.reply_text(
        "📝 Send the new Welcome Message.\n\n"
        "• Text / Photo supported\n"
        "• Use {name} to insert user's name\n"
        "• /cancel to cancel"
    )


# =========================================================
# WELCOME INPUT
# =========================================================

async def handle_welcome_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if user_id != ADMIN_ID:
        return

    if not AWAITING_WELCOME.get(
        ADMIN_ID,
        False
    ):
        return

    message = update.message

    if not message:
        return

    if message.text and message.text.startswith(
        "/cancel"
    ):

        AWAITING_WELCOME[ADMIN_ID] = False

        await message.reply_text(
            "❌ Welcome message update cancelled."
        )

        return

    if message.photo:

        photo_id = message.photo[-1].file_id

        caption = (
            message.caption
            if message.caption
            else ""
        )

        db_set_setting(
            "welcome_photo",
            photo_id
        )

        db_set_setting(
            "welcome_text",
            caption
        )

    elif message.text:

        db_set_setting(
            "welcome_photo",
            ""
        )

        db_set_setting(
            "welcome_text",
            message.text
        )

    else:

        await message.reply_text(
            "⚠️ Please send Text or Photo."
        )

        return

    AWAITING_WELCOME[ADMIN_ID] = False

    await message.reply_text(
        "✅ Welcome Message Saved!\n"
        "🗑️ Auto-delete is OFF."
    )


# =========================================================
# BROADCAST SEND WITH MAX 5 RETRIES
# =========================================================

async def send_message_with_retry(
    context,
    user_id,
    text
):

    last_error = None

    for attempt in range(
        1,
        MAX_BROADCAST_RETRIES + 1
    ):

        try:

            message = await context.bot.send_message(
                chat_id=user_id,
                text=text
            )

            return message

        except RetryAfter as e:

            last_error = e

            logger.warning(
                "RetryAfter for %s. "
                "Attempt %s/%s. Waiting %s sec.",
                user_id,
                attempt,
                MAX_BROADCAST_RETRIES,
                e.retry_after
            )

            if attempt >= MAX_BROADCAST_RETRIES:
                break

            await asyncio.sleep(
                e.retry_after
            )

        except Exception as e:

            last_error = e

            logger.warning(
                "Broadcast failed for %s. "
                "Attempt %s/%s: %s",
                user_id,
                attempt,
                MAX_BROADCAST_RETRIES,
                e
            )

            if attempt >= MAX_BROADCAST_RETRIES:
                break

            # Small increasing delay
            await asyncio.sleep(
                min(
                    2 ** (attempt - 1),
                    30
                )
            )

    raise last_error or Exception(
        "Broadcast failed"
    )


# =========================================================
# COPY BROADCAST WITH MAX 5 RETRIES
# =========================================================

async def copy_message_with_retry(
    context,
    user_id,
    from_chat_id,
    message_id,
    reply_markup=None
):

    last_error = None

    for attempt in range(
        1,
        MAX_BROADCAST_RETRIES + 1
    ):

        try:

            message = await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                reply_markup=reply_markup
            )

            return message

        except RetryAfter as e:

            last_error = e

            logger.warning(
                "Copy RetryAfter for %s. "
                "Attempt %s/%s.",
                user_id,
                attempt,
                MAX_BROADCAST_RETRIES
            )

            if attempt >= MAX_BROADCAST_RETRIES:
                break

            await asyncio.sleep(
                e.retry_after
            )

        except Exception as e:

            last_error = e

            logger.warning(
                "Copy failed for %s. "
                "Attempt %s/%s: %s",
                user_id,
                attempt,
                MAX_BROADCAST_RETRIES,
                e
            )

            if attempt >= MAX_BROADCAST_RETRIES:
                break

            await asyncio.sleep(
                min(
                    2 ** (attempt - 1),
                    30
                )
            )

    raise last_error or Exception(
        "Copy broadcast failed"
    )


# =========================================================
# TEXT BROADCAST
# =========================================================

async def broadcast_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:

        await update.message.reply_text(
            "⚠️ Usage:\n"
            "/broadcast Your message here"
        )

        return

    # Exact text
    message_text = " ".join(
        context.args
    )

    all_users = db_get_all_users()

    total = len(all_users)

    success = 0
    failed = 0

    b_id = db_create_broadcast()

    status_msg = await update.message.reply_text(
        f"🚀 Broadcast Started...\n"
        f"Progress: 0/{total}\n\n"
        f"🔄 Maximum retries: {MAX_BROADCAST_RETRIES}"
    )

    for i, user_id in enumerate(
        all_users,
        start=1
    ):

        try:

            message = await send_message_with_retry(
                context,
                user_id,
                message_text
            )

            db_save_broadcast_msg(
                b_id,
                user_id,
                message.message_id
            )

            success += 1

        except Exception as e:

            # IMPORTANT:
            # User ID remains in DB.
            failed += 1

            logger.warning(
                "Final broadcast failure for %s: %s",
                user_id,
                e
            )

        await asyncio.sleep(0.05)

        if i % 30 == 0 or i == total:

            try:

                await status_msg.edit_text(
                    f"🚀 Sending...\n"
                    f"{i}/{total} Users\n\n"
                    f"✅ Success: {success}\n"
                    f"❌ Failed: {failed}\n"
                    f"🔄 Max retries: {MAX_BROADCAST_RETRIES}"
                )

            except Exception:
                pass

    # -----------------------------------------------------
    # NO AUTO DELETE
    # -----------------------------------------------------

    await status_msg.edit_text(
        f"✅ Broadcast Completed!\n\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {failed}\n\n"
        f"🔄 Failed messages were retried "
        f"up to {MAX_BROADCAST_RETRIES} times.\n\n"
        f"🗑️ Auto-delete: OFF\n"
        f"Use /delete to manually delete this broadcast."
    )


# =========================================================
# FORWARD BROADCAST
# =========================================================

async def forward_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    if not update.message.reply_to_message:

        await update.message.reply_text(
            "⚠️ Reply to a message and type:\n"
            "/fbroadcast"
        )

        return

    replied_msg = update.message.reply_to_message

    all_users = db_get_all_users()

    total = len(all_users)

    success = 0
    failed = 0

    b_id = db_create_broadcast()

    status_msg = await update.message.reply_text(
        f"🚀 Forward Broadcast Started...\n"
        f"Progress: 0/{total}\n\n"
        f"🔄 Maximum retries: {MAX_BROADCAST_RETRIES}"
    )

    # -----------------------------------------------------
    # BACKUP BUTTON
    # -----------------------------------------------------

    backup_link = db_get_setting(
        "backup_link"
    )

    reply_markup = None

    if backup_link:

        reply_markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔗 Join Backup Channel",
                        url=backup_link
                    )
                ]
            ]
        )

    for i, user_id in enumerate(
        all_users,
        start=1
    ):

        try:

            message = await copy_message_with_retry(
                context,
                user_id,
                replied_msg.chat_id,
                replied_msg.message_id,
                reply_markup
            )

            db_save_broadcast_msg(
                b_id,
                user_id,
                message.message_id
            )

            success += 1

        except Exception as e:

            # IMPORTANT:
            # ID remains permanently saved.
            failed += 1

            logger.warning(
                "Final forward failure for %s: %s",
                user_id,
                e
            )

        await asyncio.sleep(0.05)

        if i % 30 == 0 or i == total:

            try:

                await status_msg.edit_text(
                    f"🚀 Sending...\n"
                    f"{i}/{total} Users\n\n"
                    f"✅ Success: {success}\n"
                    f"❌ Failed: {failed}\n"
                    f"🔄 Max retries: {MAX_BROADCAST_RETRIES}"
                )

            except Exception:
                pass

    # -----------------------------------------------------
    # NO AUTO DELETE
    # -----------------------------------------------------

    await status_msg.edit_text(
        f"✅ Forward Broadcast Completed!\n\n"
        f"✅ Success: {success}\n"
        f"❌ Failed: {failed}\n\n"
        f"🔄 Failed messages were retried "
        f"up to {MAX_BROADCAST_RETRIES} times.\n\n"
        f"🗑️ Auto-delete: OFF\n"
        f"Use /delete to manually delete this broadcast."
    )


# =========================================================
# MANUAL DELETE LAST BROADCAST
# =========================================================

async def delete_last_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    b_id = db_get_last_broadcast()

    if not b_id:

        await update.message.reply_text(
            "⚠️ No broadcast found to delete."
        )

        return

    msgs = db_get_broadcast_msgs(
        b_id
    )

    total = len(msgs)

    deleted = 0

    status_msg = await update.message.reply_text(
        f"🗑️ Deleting Last Broadcast...\n"
        f"Progress: 0/{total}"
    )

    for user_id, message_id in msgs:

        try:

            await context.bot.delete_message(
                chat_id=user_id,
                message_id=message_id
            )

            deleted += 1

        except Exception:
            pass

        await asyncio.sleep(0.03)

    db_clear_broadcast_msgs(
        b_id
    )

    await status_msg.edit_text(
        f"✅ Deleted Broadcast\n\n"
        f"🗑️ Deleted: {deleted}/{total}\n\n"
        f"ℹ️ User IDs were NOT deleted."
    )


# =========================================================
# ADD CHANNEL
# =========================================================

async def add_channel_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    AWAITING_CHANNEL[user_id] = True

    await update.message.reply_text(
        "📌 **Add Channel**\n\n"
        "1️⃣ Add this bot to your channel.\n"
        "2️⃣ Make the bot an administrator.\n"
        "3️⃣ Give the bot permission to invite users.\n"
        "4️⃣ Forward any message from your channel to this chat.\n\n"
        "After verification, your channel will be added.\n\n"
        "⚠️ The bot must be an admin in the channel.",
        parse_mode="Markdown"
    )


# =========================================================
# HANDLE FORWARDED CHANNEL MESSAGE
# =========================================================

async def handle_channel_forward(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message

    if not message:
        return

    user_id = update.effective_user.id

    if not AWAITING_CHANNEL.get(
        user_id,
        False
    ):
        return

    # -----------------------------------------------------
    # Detect forwarded origin
    # -----------------------------------------------------

    origin = getattr(
        message,
        "forward_origin",
        None
    )

    channel = getattr(
        origin,
        "chat",
        None
    )

    if not channel or channel.type != "channel":

        await message.reply_text(
            "⚠️ Please forward a message directly "
            "from your Telegram channel.\n\n"
            "Make sure the bot is an administrator first."
        )

        return

    channel_id = channel.id

    # -----------------------------------------------------
    # Check bot admin status
    # -----------------------------------------------------

    try:

        bot_member = await context.bot.get_chat_member(
            chat_id=channel_id,
            user_id=context.bot.id
        )

        if bot_member.status not in (
            "administrator",
            "creator"
        ):

            await message.reply_text(
                "❌ Bot is not a channel admin.\n\n"
                "Please make the bot administrator "
                "and forward the channel message again."
            )

            return

        # For invite links, bot needs invite permission.
        if (
            bot_member.status == "administrator"
            and not getattr(
                bot_member,
                "can_invite_users",
                False
            )
        ):

            await message.reply_text(
                "⚠️ Bot is an admin, but it does not "
                "have permission to invite users.\n\n"
                "Enable **Invite Users via Link** permission "
                "and forward the message again.",
                parse_mode="Markdown"
            )

            return

    except TelegramError as e:

        await message.reply_text(
            f"❌ Could not verify channel admin status.\n\n"
            f"Error: {e}"
        )

        return

    # -----------------------------------------------------
    # Get channel info
    # -----------------------------------------------------

    try:

        chat = await context.bot.get_chat(
            channel_id
        )

        title = chat.title or "Unknown Channel"

        username = chat.username or ""

    except Exception:

        title = channel.title or "Unknown Channel"

        username = getattr(
            channel,
            "username",
            ""
        ) or ""

    # -----------------------------------------------------
    # Save channel
    # -----------------------------------------------------

    db_add_channel(
        user_id,
        channel_id,
        title,
        username
    )

    AWAITING_CHANNEL[user_id] = False

    await message.reply_text(
        f"💜 **Chat added!**\n\n"
        f"📢 {title}\n"
        f"🆔 `{channel_id}`\n\n"
        f"Your channel has been successfully added.",
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )


# =========================================================
# MY CHANNELS
# =========================================================

async def my_channels(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    channels = db_get_user_channels(
        user_id
    )

    if not channels:

        await update.message.reply_text(
            "📭 You haven't added any channels yet.\n\n"
            "Use /addchannel to add one."
        )

        return

    # -----------------------------------------------------
    # If multiple channels
    # -----------------------------------------------------

    if len(channels) == 1:

        await show_channel_panel(
            update.message,
            channels[0]
        )

        return

    buttons = []

    for (
        channel_id,
        title,
        username,
        request_accepted
    ) in channels:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"📢 {title}",
                    callback_data=f"channel:{channel_id}"
                )
            ]
        )

    await update.message.reply_text(
        "📚 **My Channels**\n\n"
        "Select a channel:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            buttons
        )
    )


# =========================================================
# SHOW CHANNEL PANEL
# =========================================================

async def show_channel_panel(
    message,
    channel_data
):

    (
        channel_id,
        title,
        username,
        request_accepted
    ) = channel_data

    # Owner will be supplied through callback.
    # For direct /mychannels we need message.from_user.
    user_id = message.chat.id

    active_links = db_get_link_count(
        user_id,
        channel_id
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📌 Create link",
                    callback_data=f"create:{channel_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "📨 All links",
                    callback_data=f"links:{channel_id}"
                )
            ]
        ]
    )

    await message.reply_text(
        f"📢 **{title}**\n\n"
        f"❄️ Active links: {active_links}\n"
        f"🎯 Request accepted: {request_accepted}",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


# =========================================================
# CHANNEL CALLBACKS
# =========================================================

async def channel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    data = query.data

    # -----------------------------------------------------
    # SELECT CHANNEL
    # -----------------------------------------------------

    if data.startswith(
        "channel:"
    ):

        channel_id = int(
            data.split(
                ":",
                1
            )[1]
        )

        if not db_channel_belongs_to_user(
            user_id,
            channel_id
        ):

            await query.message.reply_text(
                "❌ This channel does not belong to you."
            )

            return

        channel = db_get_channel(
            channel_id
        )

        if not channel:
            return

        (
            channel_id,
            title,
            username,
            request_accepted,
            last_action
        ) = channel

        active_links = db_get_link_count(
            user_id,
            channel_id
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "📌 Create link",
                        callback_data=f"create:{channel_id}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📨 All links",
                        callback_data=f"links:{channel_id}"
                    )
                ]
            ]
        )

        await query.message.reply_text(
            f"📢 **{title}**\n\n"
            f"❄️ Active links: {active_links}\n"
            f"🎯 Request accepted: {request_accepted}",
            parse_mode="Markdown",
            reply_markup=keyboard
        )

        return

    # -----------------------------------------------------
    # CREATE LINK
    # -----------------------------------------------------

    if data.startswith(
        "create:"
    ):

        channel_id = int(
            data.split(
                ":",
                1
            )[1]
        )

        if not db_channel_belongs_to_user(
            user_id,
            channel_id
        ):

            await query.message.reply_text(
                "❌ You don't have access to this channel."
            )

            return

        channel = db_get_channel(
            channel_id
        )

        title = (
            channel[1]
            if channel
            else "Channel"
        )

        try:

            invite = await context.bot.create_chat_invite_link(
                chat_id=channel_id,
                name=f"Bot Link - {user_id}",
                creates_join_request=True
            )

            invite_link = invite.invite_link

            db_save_channel_link(
                channel_id,
                user_id,
                invite_link
            )

            await query.message.reply_text(
                f"🔄 Link for **{title}** created!\n\n"
                f"🔗 {invite_link}",
                parse_mode="Markdown"
            )

        except TelegramError as e:

            await query.message.reply_text(
                f"❌ Could not create link.\n\n"
                f"{e}\n\n"
                f"Make sure the bot is admin and has "
                f"permission to invite users."
            )

        return

    # -----------------------------------------------------
    # ALL LINKS
    # -----------------------------------------------------

    if data.startswith(
        "links:"
    ):

        channel_id = int(
            data.split(
                ":",
                1
            )[1]
        )

        if not db_channel_belongs_to_user(
            user_id,
            channel_id
        ):

            await query.message.reply_text(
                "❌ You don't have access to this channel."
            )

            return

        channel = db_get_channel(
            channel_id
        )

        title = (
            channel[1]
            if channel
            else "Channel"
        )

        request_accepted = (
            channel[3]
            if channel
            else 0
        )

        links = db_get_user_links(
            user_id,
            channel_id
        )

        if not links:

            await query.message.reply_text(
                f"📨 **All Links**\n\n"
                f"📢 {title}\n\n"
                f"❌ No links created yet.\n\n"
                f"Tap **📌 Create link** to create one.",
                parse_mode="Markdown"
            )

            return

        text = (
            f"📨 **All Links**\n\n"
            f"📢 {title}\n"
            f"🎯 Request accepted: {request_accepted}\n\n"
        )

        for index, (
            link_id,
            invite_link,
            created_at
        ) in enumerate(
            links,
            start=1
        ):

            text += (
                f"🔗 **Link {index}**\n"
                f"{invite_link}\n"
                f"📅 Created: {created_at}\n\n"
            )

        await query.message.reply_text(
            text,
            parse_mode="Markdown"
        )

        return


# =========================================================
# RESTART
# =========================================================

async def restart_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    await update.message.reply_text(
        "🔄 Restarting Bot..."
    )

    os.execl(
        sys.executable,
        sys.executable,
        *sys.argv
    )


# =========================================================
# HELP
# =========================================================

async def help_cmd(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != ADMIN_ID:
        return

    help_text = (
        "🛠️ Admin Panel\n\n"

        "👥 USER\n"
        "/users - Total Users\n"
        "/stats - Bot Statistics\n"
        "/ping - Response Latency\n\n"

        "📢 BROADCAST\n"
        "/broadcast <text> - Text Broadcast\n"
        "/fbroadcast - Forward/Copy Broadcast\n"
        "/delete - Delete Last Broadcast\n\n"

        "📢 CHANNEL\n"
        "/addchannel - Add Channel\n"
        "/mychannels - My Channels\n\n"

        "⚙️ SETTINGS\n"
        "/backup <link> - Change Backup Link\n"
        "/setwelcome - Change Welcome Message\n"
        "/restart - Restart Bot\n"
        "/help - Show Help\n\n"

        f"🔄 Broadcast retry: Maximum {MAX_BROADCAST_RETRIES}\n"
        "🗑️ Automatic deletion: OFF\n"
        "💾 User IDs: Permanent"
    )

    await update.message.reply_text(
        help_text
    )


# =========================================================
# POST INIT (ADMIN VS NORMAL USER MENU)
# =========================================================

async def post_init(
    application: Application
):

    # -----------------------------------------------------
    # 1. NORMAL USERS MENU (फक्त ३ कमांड्स दिसतील)
    # -----------------------------------------------------

    user_commands = [
        BotCommand(
            "start",
            "Start Bot"
        ),
        BotCommand(
            "addchannel",
            "Add Channel"
        ),
        BotCommand(
            "mychannels",
            "View My Channels"
        ),
    ]

    await application.bot.set_my_commands(
        commands=user_commands,
        scope=BotCommandScopeAllPrivateChats()
    )

    # -----------------------------------------------------
    # 2. ADMIN MENU (एडमिनला सर्व कमांड्स दिसतील)
    # -----------------------------------------------------

    admin_commands = [

        BotCommand(
            "start",
            "Start Bot"
        ),

        BotCommand(
            "stats",
            "View Statistics"
        ),

        BotCommand(
            "users",
            "Total Users"
        ),

        BotCommand(
            "ping",
            "Response Latency"
        ),

        BotCommand(
            "backup",
            "Change Backup Link"
        ),

        BotCommand(
            "setwelcome",
            "Set Welcome Message"
        ),

        BotCommand(
            "broadcast",
            "Send Text Broadcast"
        ),

        BotCommand(
            "fbroadcast",
            "Send Forward Broadcast"
        ),

        BotCommand(
            "delete",
            "Delete Last Broadcast"
        ),

        BotCommand(
            "addchannel",
            "Add Channel"
        ),

        BotCommand(
            "mychannels",
            "View My Channels"
        ),

        BotCommand(
            "restart",
            "Restart Bot"
        ),

        BotCommand(
            "help",
            "Show Help"
        ),
    ]

    try:
        await application.bot.set_my_commands(
            commands=admin_commands,
            scope=BotCommandScopeChat(chat_id=ADMIN_ID)
        )
    except Exception as e:
        logger.error(
            "Could not set admin commands: %s",
            e
        )


# =========================================================
# MAIN
# =========================================================

def main():

    # Flask
    flask_thread = Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    # Telegram Application
    app = (
        Application
        .builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "ping",
            ping
        )
    )

    app.add_handler(
        CommandHandler(
            "users",
            users_cmd
        )
    )

    app.add_handler(
        CommandHandler(
            "stats",
            stats
        )
    )

    app.add_handler(
        CommandHandler(
            "backup",
            set_backup
        )
    )

    app.add_handler(
        CommandHandler(
            "setwelcome",
            set_welcome_cmd
        )
    )

    app.add_handler(
        CommandHandler(
            "broadcast",
            broadcast_cmd
        )
    )

    app.add_handler(
        CommandHandler(
            "fbroadcast",
            forward_broadcast
        )
    )

    app.add_handler(
        CommandHandler(
            "delete",
            delete_last_broadcast
        )
    )

    app.add_handler(
        CommandHandler(
            "addchannel",
            add_channel_command
        )
    )

    app.add_handler(
        CommandHandler(
            "mychannels",
            my_channels
        )
    )

    app.add_handler(
        CommandHandler(
            "restart",
            restart_cmd
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_cmd
        )
    )

    # -----------------------------------------------------
    # BUTTON TEXT
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.Regex(
                r"^➕ Add channel$"
            ),
            add_channel_command
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(
                r"^📚 My channels$"
            ),
            my_channels
        )
    )

    # -----------------------------------------------------
    # CHANNEL FORWARDED MESSAGE
    #
    # This MUST come before welcome handler.
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_channel_forward
        ),
        group=0
    )

    # -----------------------------------------------------
    # WELCOME INPUT
    # -----------------------------------------------------

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            handle_welcome_input
        ),
        group=1
    )

    # -----------------------------------------------------
    # CALLBACKS
    # -----------------------------------------------------

    app.add_handler(
        CallbackQueryHandler(
            channel_callback
        )
    )

    # -----------------------------------------------------
    # JOIN REQUESTS
    #
    # Works for ALL channels where bot is admin.
    # -----------------------------------------------------

    app.add_handler(
        ChatJoinRequestHandler(
            auto_accept_request
        )
    )

    # -----------------------------------------------------
    # RUN
    # -----------------------------------------------------

    print(
        "Bot is running..."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# ENTRY POINT
# =========================================================

if __name__ == "__main__":
    main()
