import os
import json
import logging
import warnings
import traceback
from firebase_admin import credentials, firestore, initialize_app
from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes
)
import asyncio
from datetime import datetime, timezone

from load_env import load_environment
load_environment()

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Suppress UserWarnings about Firestore filters
warnings.filterwarnings("ignore", category=UserWarning)

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TO_MAIL = os.getenv('TO_MAIL', 'info@weeklygamevault.com')  # Default fallback email

if not TELEGRAM_BOT_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN not found in environment variables.")
    exit(1)

# Initialize bot and track start time
bot = None
application = None
BOT_START_TIME = None

# Rate limiting settings
MESSAGE_RATE = 1  # messages per second
rate_limiter = asyncio.Semaphore(MESSAGE_RATE)

# Firestore initialization
firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')
if not firebase_credentials:
    logging.error("FIREBASE_CREDENTIALS not found in environment variables.")
    exit(1)

try:
    firebase_credentials_dict = json.loads(firebase_credentials)
    cred = credentials.Certificate(firebase_credentials_dict)
    initialize_app(cred)
    db = firestore.client()
except Exception as e:
    logging.error(f"Failed to initialize Firebase: {e}")
    exit(1)

# Collections to watch
GAME_COLLECTIONS = [
    'epic_free_games',
    'gog_free_games',
    'steam_free_games',
    'gog_giveaway',
    'prime_free_games'
]

SUBSCRIBERS_COLLECTION = 'telegram_subscribers'

# Create an event loop for the background tasks
background_loop = asyncio.new_event_loop()
asyncio.set_event_loop(background_loop)

def send_error_email(error_message, error_trace):
    """Send error notification email."""
    from util import send_email  # Import here to avoid circular imports

    subject = "Telegram Bot Script Failure"
    content = (
        f"An error occurred while running the Telegram bot:\n\n"
        f"Error: {error_message}\n\n"
        f"Traceback:\n{error_trace}\n\n"
        f"Timestamp: {datetime.now(timezone.utc)}"
    )

    try:
        send_email(subject, content, to=TO_MAIL)
        logging.info(f"Error notification email sent to {TO_MAIL}")
    except Exception as e:
        logging.error(f"Failed to send error notification email: {e}")

async def send_telegram_message(chat_id, text):
    """Send a Telegram message with rate limiting."""
    async with rate_limiter:  # Ensure we don't exceed rate limit
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='Markdown',
                disable_web_page_preview=False
            )
            logging.info(f"Successfully sent message to {chat_id}")
        except TelegramError as e:
            logging.error(f"Failed to send message to {chat_id}: {e}")
            error_trace = traceback.format_exc()
            send_error_email(str(e), error_trace)
        except Exception as e:
            logging.error(f"Unexpected error sending message to {chat_id}: {e}")
            error_trace = traceback.format_exc()
            send_error_email(str(e), error_trace)

async def notify_subscribers(game, collection_name):
    """Send a Telegram message to all subscribers."""
    try:
        subscribers_ref = db.collection(SUBSCRIBERS_COLLECTION).where('active', '==', True).stream()
    except Exception as e:
        logging.error(f"Failed to fetch subscribers: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)
        return

    message_text = (
        f"🎮 *New Free Game Available!*\n\n"
        f"*Source:* {collection_name.replace('_', ' ').title()}\n"
        f"*Title:* {game.get('title')}\n"
        f"[Claim Here]({game.get('url')})"
    )

    tasks = []
    for subscriber in subscribers_ref:
        task = asyncio.create_task(send_telegram_message(subscriber.id, message_text))
        tasks.append(task)

    await asyncio.gather(*tasks)

def watch_collection(collection_name):
    """Start watching a Firestore collection for changes."""
    def on_snapshot(col_snapshot, changes, read_time):
        """Handle new games added to the Firestore collection."""
        for change in changes:
            if change.type.name == 'ADDED':
                game = change.document.to_dict()
                
                # Get the update time from Firestore metadata
                update_time = change.document.update_time
                
                # Convert to UTC for comparison
                if update_time:
                    update_time = update_time.replace(tzinfo=timezone.utc)
                    
                    if update_time > BOT_START_TIME:
                        logging.info(f"New game detected in {collection_name}: {game.get('title')}")
                        background_loop.create_task(notify_subscribers(game, collection_name))
                    else:
                        logging.info(f"Skipping notification for existing game in {collection_name}: {game.get('title')}")
                        logging.info(f"Game update time: {update_time}")
                        logging.info(f"Bot started at: {BOT_START_TIME}")
                else:
                    logging.warning(f"No update time available for game: {game.get('title')}")

    try:
        collection_ref = db.collection(collection_name)
        collection_ref.on_snapshot(on_snapshot)
        logging.info(f"Started watching collection: {collection_name}")
    except Exception as e:
        logging.error(f"Failed to watch collection {collection_name}: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)

# Define states for ConversationHandler
PRIVACY_POLICY_ACCEPTANCE = 1

async def subscribe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the subscribe conversation and asks for privacy policy acceptance."""
    chat_id = update.effective_chat.id
    user = update.effective_user

    # Log the /subscribe usage with timestamp in Firestore
    try:
        subscriber_ref = db.collection(SUBSCRIBERS_COLLECTION).document(str(chat_id))
        subscriber_ref.set({
            'subscribe_requested_at': datetime.now(timezone.utc)
        }, merge=True)
        logging.info(f"/subscribe used by user {user.id} at {datetime.now(timezone.utc)}")
    except Exception as e:
        logging.error(f"Error logging /subscribe usage for user {user.id}: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)
        await update.message.reply_text("There was a problem processing your request. Please try again later.")
        return ConversationHandler.END

    # Send privacy policy message
    privacy_message = (
        "Please read our [Privacy Policy](https://www.weeklygamevault.com/PrivacyPolicy).\n\n"
        "If you accept the Privacy Policy, type `Accept`. Otherwise, type `Decline`."
    )
    await update.message.reply_text(
        privacy_message,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

    return PRIVACY_POLICY_ACCEPTANCE

async def subscribe_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the user's response to the privacy policy."""
    response = update.message.text.strip().lower()
    chat_id = update.effective_chat.id
    user = update.effective_user

    if response == 'accept':
        try:
            subscriber_ref = db.collection(SUBSCRIBERS_COLLECTION).document(str(chat_id))
            subscriber = subscriber_ref.get()

            if subscriber.exists:
                subscriber_data = subscriber.to_dict()
                if subscriber_data.get('active', False):
                    await update.message.reply_text("You are already subscribed to notifications.")
                else:
                    subscriber_ref.update({
                        'active': True,
                        'subscribed_at': datetime.now(timezone.utc)
                    })
                    await update.message.reply_text("You have been successfully resubscribed!")
                    logging.info(f"User {user.id} resubscribed at {datetime.now(timezone.utc)}")
            else:
                subscriber_ref.set({
                    'active': True,
                    'subscribed_at': datetime.now(timezone.utc)
                })
                await update.message.reply_text("You have successfully subscribed to game notifications!")
                logging.info(f"User {user.id} subscribed at {datetime.now(timezone.utc)}")
        except Exception as e:
            logging.error(f"Error adding subscriber {user.id}: {e}")
            error_trace = traceback.format_exc()
            send_error_email(str(e), error_trace)
            await update.message.reply_text("There was a problem subscribing. Please try again later.")
    elif response == 'decline':
        await update.message.reply_text("You have not been subscribed. You can use the /subscribe command again at any time.")
        logging.info(f"User {user.id} declined subscription at {datetime.now(timezone.utc)}")
    else:
        await update.message.reply_text("Please respond with `Accept` or `Decline`.")
        return PRIVACY_POLICY_ACCEPTANCE  # Remain in the current state

    return ConversationHandler.END

async def subscribe_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the subscribe conversation."""
    await update.message.reply_text('Subscription process canceled.')
    return ConversationHandler.END

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /unsubscribe - Remove user from the subscriber list."""
    try:
        chat_id = update.effective_chat.id
        subscriber_ref = db.collection(SUBSCRIBERS_COLLECTION).document(str(chat_id))

        subscriber = subscriber_ref.get()
        if subscriber.exists and subscriber.to_dict().get('active', False):
            subscriber_ref.update({
                'active': False,
                'unsubscribed_at': datetime.now(timezone.utc)
            })
            await update.message.reply_text("You have successfully unsubscribed from game notifications.")
            logging.info(f"User {chat_id} unsubscribed at {datetime.now(timezone.utc)}")
        else:
            await update.message.reply_text("You are currently not subscribed.")
    except Exception as e:
        logging.error(f"Error in unsubscribe handler for user {chat_id}: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)
        await update.message.reply_text("There was a problem unsubscribing. Please try again later.")

async def delete_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command: /delete_me - Delete the user from the subscribers list."""
    try:
        chat_id = update.effective_chat.id
        subscriber_ref = db.collection(SUBSCRIBERS_COLLECTION).document(str(chat_id))

        if subscriber_ref.get().exists:
            subscriber_ref.delete()
            await update.message.reply_text("Your data has been successfully deleted.")
            logging.info(f"User {chat_id} data deleted at {datetime.now(timezone.utc)}")
        else:
            await update.message.reply_text("There is no saved data for you.")
    except Exception as e:
        logging.error(f"Error in delete_me handler for user {chat_id}: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)
        await update.message.reply_text("There was a problem deleting your data. Please try again later.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /status command."""
    chat_id = update.effective_chat.id
    try:
        subscriber_ref = db.collection(SUBSCRIBERS_COLLECTION).document(str(chat_id))
        subscriber = subscriber_ref.get()
        if subscriber.exists:
            data = subscriber.to_dict()
            status = "Active" if data.get('active', False) else "Inactive"
            subscribed_at = data.get('subscribed_at', 'N/A')
            subscribe_requested_at = data.get('subscribe_requested_at', 'N/A')
            status_message = (
                f"📊 *Your Subscription Status:*\n\n"
                f"Status: *{status}*\n"
                f"Subscribed At: {subscribed_at}\n"
                f"Subscription Requested At: {subscribe_requested_at}"
            )
        else:
            status_message = "You are not currently subscribed to any notifications."
        await update.message.reply_text(
            status_message,
            parse_mode='Markdown'
        )
    except Exception as e:
        logging.error(f"Error fetching status for user {chat_id}: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)
        await update.message.reply_text("There was a problem retrieving your status. Please try again later.")

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /about command."""
    about_text = (
        "🤖 *WeeklyGameVault Bot*\n\n"
        "This bot keeps you updated with the latest free game offers from various platforms like Prime Gaming Steam, Epic Games and GOG.\n\n"
        "Developed by [WeeklyGameVault](https://www.weeklygamevault.com).\n\n"
    )
    await update.message.reply_text(
        about_text,
        parse_mode='Markdown',
        disable_web_page_preview=True
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /help command."""
    help_text = (
        "🛠 *Available Commands*\\n\\n"
        "/help \\- Shows this help message\\n"
        "/about \\- Learn about WeeklyGameVault Bot\\n"
        "/subscribe \\- Start receiving free game notifications\\n"
        "/unsubscribe \\- Stop receiving notifications\\n"
        "/status \\- View your subscription details\\n"
        "/delete\\_me \\- Permanently remove all your data"
    )
    
    await update.message.reply_text(
        help_text,
        parse_mode='MarkdownV2',
        disable_web_page_preview=True
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /stats command. Admin only."""
    admin_ids = [7570291259] 
    user_id = update.effective_user.id
    if user_id not in admin_ids:
        await update.message.reply_text("You are not authorized to use this command.")
        return
    
    try:
        # Count active subscribers
        active_subscribers_query = db.collection(SUBSCRIBERS_COLLECTION).where('active', '==', True)
        active_subscribers = active_subscribers_query.stream()
        active_count = sum(1 for _ in active_subscribers)

        stats_message = (
            "*📊 Bot Statistics:*\\n\\n"
            f"*Active Subscribers:* {active_count}\\n"
        )
        await update.message.reply_text(
            stats_message,
            parse_mode='MarkdownV2'
        )
    except Exception as e:
        logging.error(f"Error fetching stats: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)
        await update.message.reply_text("There was a problem fetching the statistics.")

def main():
    try:
        global bot, application, BOT_START_TIME
        
        # Set bot start time
        BOT_START_TIME = datetime.now(timezone.utc)
        logging.info(f"Bot starting at: {BOT_START_TIME}")

        # Create the Application
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        bot = application.bot

        # Create ConversationHandler for /subscribe
        subscribe_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('subscribe', subscribe_start)],
            states={
                PRIVACY_POLICY_ACCEPTANCE: [
                    MessageHandler(
                        filters.TEXT & (~filters.COMMAND),
                        subscribe_response
                    )
                ],
            },
            fallbacks=[CommandHandler('cancel', subscribe_cancel)],
            allow_reentry=True
        )

        # Add handlers
        application.add_handler(subscribe_conv_handler)
        application.add_handler(CommandHandler("unsubscribe", unsubscribe))
        application.add_handler(CommandHandler("delete_me", delete_me))
        application.add_handler(CommandHandler("status", status))
        application.add_handler(CommandHandler("about", about))
        application.add_handler(CommandHandler("help", help))
        application.add_handler(CommandHandler("stats", stats))

        # Start Firestore listeners for all collections
        for collection_name in GAME_COLLECTIONS:
            watch_collection(collection_name)

        # Start the bot
        logging.info("Bot is running...")
        application.run_polling()

    except Exception as e:
        logging.error(f"Critical error in main: {e}")
        error_trace = traceback.format_exc()
        send_error_email(str(e), error_trace)
        raise

if __name__ == '__main__':
    main()