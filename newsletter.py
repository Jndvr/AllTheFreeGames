import os
import json
import time
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
from jinja2 import Environment, FileSystemLoader, select_autoescape

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Fetch environment variables
firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")
gmail_username = os.getenv("GMAIL_USERNAME", "")
gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
from_email = os.getenv("FROM_EMAIL", gmail_username)
base_url = os.getenv("BASE_URL", "http://127.0.0.1:5001")
logo_url = os.getenv("LOGO_URL", "https://yourdomain.com/path-to-your-logo.png")  # Add LOGO_URL to .env

# -------------------------------------------------
# Firebase Initialization
# -------------------------------------------------
def initialize_firebase():
    """
    Initializes Firebase with service account credentials.
    """
    global db
    try:
        if not firebase_credentials_str:
            raise ValueError("FIREBASE_CREDENTIALS is empty. Check your .env file.")
        creds_json = json.loads(firebase_credentials_str)
        cred = credentials.Certificate(creds_json)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("Firebase initialized successfully in newsletter.py.")
    except ValueError as ve:
        logging.error(f"Firebase initialization error: {ve}")
        db = None
    except json.JSONDecodeError as je:
        logging.error(f"Error parsing FIREBASE_CREDENTIALS JSON: {je}")
        db = None
    except Exception as e:
        logging.error(f"Unexpected error initializing Firebase: {e}")
        db = None

initialize_firebase()

# -------------------------------------------------
# Jinja2 Environment / Template
# -------------------------------------------------
env = Environment(
    loader=FileSystemLoader(searchpath="./templates"),
    autoescape=select_autoescape(['html', 'xml'])
)
template = env.get_template("newsletter_template.html")

# -------------------------------------------------
# Build HTML using Jinja2
# -------------------------------------------------
def build_games_html(subscriber_name, confirm_token):
    """
    Reads games from Firestore collection 'prime_free_games'
    and constructs the HTML content for the email using Jinja2.
    
    We reuse 'confirm_token' to build the unsubscribe link.
    """
    if not db:
        logging.error("Database is not initialized. Cannot fetch games.")
        return "<p>No data available.</p>"

    docs = db.collection("prime_free_games").stream()
    games = []
    for doc in docs:
        data = doc.to_dict()
        title = data.get("title", "Unknown Title")
        url = data.get("url", "#")
        image_url = data.get("imageUrl", "")
        games.append({"title": title, "url": url, "imageUrl": image_url})

    if not games:
        return "<p>No free games found in the database.</p>"

    current_year = time.strftime("%Y")
    unsubscribe_url = f"{base_url}/unsubscribe/{confirm_token}"

    html = template.render(
        logo_url=logo_url,
        subscriber_name=subscriber_name,
        games=games,
        unsubscribe_url=unsubscribe_url,
        base_url=base_url,
        current_year=current_year
    )
    return html

# -------------------------------------------------
# Build Plain-Text Version
# -------------------------------------------------
def build_games_text():
    """
    Reads games from Firestore collection 'prime_free_games'
    and constructs the plain text content for the email.
    """
    if not db:
        logging.error("Database is not initialized. Cannot fetch games.")
        return "No data available."

    docs = db.collection("prime_free_games").stream()
    lines = []
    for doc in docs:
        data = doc.to_dict()
        title = data.get("title", "Unknown Title")
        url = data.get("url", "No URL")
        lines.append(f"{title}\n  URL: {url}\n")

    return "\n".join(lines) if lines else "No free games found in the database."

# -------------------------------------------------
# Send the Newsletter Email
# -------------------------------------------------
def send_newsletter_email(to_email, confirm_token, html_content, text_content):
    """
    Sends an email with the free games content to the given email address.
    Reuses 'confirm_token' for unsubscribe link.
    """
    if not gmail_username or not gmail_app_password:
        logging.warning("Gmail credentials are not set. Email sending skipped.")
        return

    subject = "WeeklyGameVault: This Week's Free Prime Gaming Offers!"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    # Attach plain text part
    text_part = MIMEText(text_content, "plain", "utf-8")
    msg.attach(text_part)

    # Attach HTML part
    html_part = MIMEText(html_content, "html", "utf-8")
    msg.attach(html_part)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_username, gmail_app_password)
            server.sendmail(from_email, [to_email], msg.as_string())
        logging.info(f"Sent newsletter to {to_email}.")
    except Exception as e:
        logging.error(f"Failed to send newsletter to {to_email}: {e}")

# -------------------------------------------------
# Main Newsletter Logic
# -------------------------------------------------
def run_weekly_newsletter():
    """
    1. Builds the free games HTML and text.
    2. Fetches all subscribers from Firestore.
    3. Sends the newsletter email to each subscriber.
    
    We assume 'confirm_token' is used for unsubscribing.
    """
    logging.info("Starting weekly newsletter job...")
    if not db:
        logging.error("Database is not initialized. Aborting newsletter job.")
        return

    try:
        subscribers = db.collection("newsletter_subscribers").stream()
        for sub in subscribers:
            data = sub.to_dict()
            email = data.get("email")
            # Grab the 'confirm_token' from Firestore
            confirm_token = data.get("confirm_token", "")
            name = data.get("name", "Subscriber")  # Default to "Subscriber" if name not provided

            # Only send if they are confirmed; optionally check 'confirmed' == True
            if email and confirm_token and data.get("confirmed", False):
                html_content = build_games_html(name, confirm_token)
                text_content = build_games_text()
                send_newsletter_email(email, confirm_token, html_content, text_content)
            else:
                logging.info(f"Skipping {email}; either missing token or not confirmed.")
    except Exception as e:
        logging.error(f"Error fetching subscribers: {e}")

    logging.info("Weekly newsletter job completed successfully.")

# -------------------------------------------------
# Entry Point
# -------------------------------------------------
if __name__ == "__main__":
    run_weekly_newsletter()
