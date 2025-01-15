import os
import json
import time
import logging
import smtplib
import warnings
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from load_env import load_environment
load_environment()

import firebase_admin
from firebase_admin import credentials, firestore
from jinja2 import Environment, FileSystemLoader, select_autoescape
from mail_counter import MailCounter

# Suppress UserWarnings about Firestore filters
warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Environment variables
firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")
gmail_username = os.getenv("GMAIL_USERNAME", "")
gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
from_email = os.getenv("FROM_EMAIL", gmail_username)
base_url = os.getenv("BASE_URL", "http://127.0.0.1:5001")
logo_url = os.getenv("LOGO_URL", "https://example.com/weeklygamevault_logo.png")

# Initialize mail counter
mail_counter = MailCounter()

def initialize_firebase():
    global db
    try:
        if not firebase_credentials_str:
            raise ValueError("FIREBASE_CREDENTIALS is empty.")
        creds_json = json.loads(firebase_credentials_str)
        cred = credentials.Certificate(creds_json)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("Firebase initialized successfully in newsletter_new_games.py.")
    except Exception as e:
        logging.error(f"Firebase initialization error: {e}")
        db = None

initialize_firebase()

env = Environment(
    loader=FileSystemLoader(searchpath="./templates"),
    autoescape=select_autoescape(['html', 'xml'])
)
template = env.get_template("newsletter_template.html")

def fetch_last_run_time():
    """
    Reads the last_run_time from Firestore doc config/newGamesNewsletter.
    If not found, fallback to 24 hours ago.
    """
    if not db:
        logging.error("DB not initialized. Can't fetch last_run_time.")
        # fallback 24 hours
        return datetime.now(timezone.utc) - timedelta(hours=24)

    doc_ref = db.collection("config").document("newGamesNewsletter")
    doc = doc_ref.get()
    if doc.exists:
        data = doc.to_dict()
        last_run_time = data.get("last_run_time")
        if last_run_time is not None:
            return last_run_time  # Firestore Timestamp converts to Python datetime
        else:
            logging.info("No last_run_time field found, defaulting 24 hours ago.")
            return datetime.now(timezone.utc) - timedelta(hours=24)
    else:
        logging.info("config/newGamesNewsletter doc not found, defaulting 24 hours ago.")
        return datetime.now(timezone.utc) - timedelta(hours=24)

def update_last_run_time(new_time):
    """
    Updates the last_run_time in Firestore doc config/newGamesNewsletter to new_time.
    """
    doc_ref = db.collection("config").document("newGamesNewsletter")
    doc_ref.set({"last_run_time": new_time}, merge=True)
    logging.info(f"Updated last_run_time to {new_time} in Firestore.")

def build_new_games_list(last_run_time):
    """
    Query 'prime_free_games', 'epic_free_games', and 'gog_giveaway' for docs with createdAt > last_run_time.
    Return a dictionary with lists of newly added prime, epic, and gog games.
    """
    if not db:
        logging.error("DB not initialized. Aborting.")
        return {"prime_games": [], "epic_games": [], "gog_games": []}

    # Fetch new Prime games
    new_prime_query = db.collection("prime_free_games").where("createdAt", ">", last_run_time)
    prime_docs = new_prime_query.stream()

    prime_games = []
    for doc in prime_docs:
        data = doc.to_dict()
        title = data.get("title", "Unknown Title")
        url = data.get("url", "#")
        image_url = data.get("imageUrl", "")
        # Ensure all necessary fields are present
        if title and url and image_url:
            prime_games.append({"title": title, "url": url, "imageUrl": image_url})

    # Fetch new Epic games
    new_epic_query = db.collection("epic_free_games").where("createdAt", ">", last_run_time)
    epic_docs = new_epic_query.stream()

    epic_games = []
    for doc in epic_docs:
        data = doc.to_dict()
        title = data.get("title", "Unknown Title")
        url = data.get("url", "#")
        image_url = data.get("imageUrl", "")
        # Ensure all necessary fields are present
        if title and url and image_url:
            epic_games.append({"title": title, "url": url, "imageUrl": image_url})

    # Fetch new GOG games
    new_gog_query = db.collection("gog_giveaway").where("createdAt", ">", last_run_time)
    gog_docs = new_gog_query.stream()

    gog_games = []
    for doc in gog_docs:
        data = doc.to_dict()
        title = data.get("title", "Unknown Title")
        url = data.get("url", "#")
        image_url = data.get("imageUrl", "")
        # Ensure all necessary fields are present
        if title and url and image_url:
            gog_games.append({"title": title, "url": url, "imageUrl": image_url})

    # Debugging logs
    logging.info(f"Found {len(prime_games)} new Prime Gaming games.")
    logging.info(f"Found {len(epic_games)} new Epic Games games.")
    logging.info(f"Found {len(gog_games)} new GOG games.")

    return {"prime_games": prime_games, "epic_games": epic_games, "gog_games": gog_games}

def build_text_list(new_games):
    """
    Build a plain-text version for the email body, including Prime, Epic, and GOG games.
    """
    prime_games = new_games.get("prime_games", [])
    epic_games = new_games.get("epic_games", [])
    gog_games = new_games.get("gog_games", [])

    lines = []

    if prime_games:
        lines.append("Prime Gaming Offers:\n" + "\n".join([f"{g['title']}\n  URL: {g['url']}" for g in prime_games]))
    else:
        lines.append("Prime Gaming Offers:\n(No new Prime games found)\n")

    if epic_games:
        lines.append("Epic Games Offers:\n" + "\n".join([f"{g['title']}\n  URL: {g['url']}" for g in epic_games]))
    else:
        lines.append("Epic Games Offers:\n(No new Epic games found)\n")

    if gog_games:
        lines.append("GOG Offers:\n" + "\n".join([f"{g['title']}\n  URL: {g['url']}" for g in gog_games]))
    else:
        lines.append("GOG Offers:\n(No new GOG games found)\n")

    return "\n".join(lines)

def send_new_games_email(to_email, confirm_token, html_content, text_content):
    if not gmail_username or not gmail_app_password:
        logging.warning("Gmail credentials missing. Skipping email.")
        return

    subject = "WeeklyGameVault: New Game Added!"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    text_part = MIMEText(text_content, "plain", "utf-8")
    html_part = MIMEText(html_content, "html", "utf-8")

    msg.attach(text_part)
    msg.attach(html_part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_username, gmail_app_password)
            server.sendmail(from_email, [to_email], msg.as_string())
        logging.info(f"Sent new games newsletter to {to_email}.")
    except Exception as e:
        logging.error(f"Failed to send new games newsletter to {to_email}: {e}")

def run_new_games_newsletter():
    """Main newsletter function with partial send support"""
    logging.info("Starting new games newsletter job...")

    if not db:
        logging.error("DB not initialized. Exiting.")
        return

    last_run_time = fetch_last_run_time()
    new_games = build_new_games_list(last_run_time)
    
    if not new_games["prime_games"] and not new_games["epic_games"] and not new_games["gog_games"]:
        logging.info("No newly added games found since last_run_time. Exiting.")
        return

    text_content = build_text_list(new_games)
    current_year = time.strftime("%Y")

    try:
        subscribers = list(db.collection("newsletter_subscribers")
            .where("frequency", "in", ["newgame", "both"])
            .where("confirmed", "==", True)
            .stream())
        
        subscriber_count = len(subscribers)
        
        # Get number of emails we can send
        can_send_count, all_can_send = mail_counter.increment(subscriber_count)
        
        if can_send_count == 0:
            logging.error("Monthly email limit reached. No emails can be sent.")
            return
            
        if not all_can_send:
            logging.warning(f"Can only send to {can_send_count} out of {subscriber_count} subscribers due to monthly limit")
            # Only process the number of subscribers we can send to
            subscribers = subscribers[:can_send_count]

        sent_any = False
        for sub in subscribers:
            data = sub.to_dict()
            email = data.get("email")
            confirm_token = data.get("confirm_token", "")
            name = data.get("name", "Subscriber")

            unsubscribe_url = f"{base_url}/unsubscribe/{confirm_token}"

            rendered_html = template.render(
                logo_url=logo_url,
                subscriber_name=name,
                games=new_games["prime_games"],
                epic_games=new_games["epic_games"],
                gog_games=new_games["gog_games"],
                unsubscribe_url=unsubscribe_url,
                base_url=base_url,
                current_year=current_year,
                confirm_token=confirm_token
            )

            send_new_games_email(email, confirm_token, rendered_html, text_content)
            sent_any = True

        if sent_any:
            now_utc = datetime.now(timezone.utc)
            update_last_run_time(now_utc)
            logging.info(f"Successfully updated last_run_time to {now_utc}.")
        else:
            logging.info("No new games sent (no subscribers matched?), not updating last_run_time.")

    except Exception as e:
        logging.error(f"Error in newsletter process: {e}")

if __name__ == "__main__":
    run_new_games_newsletter()