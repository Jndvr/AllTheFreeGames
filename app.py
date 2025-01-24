import os
import json
import re
import smtplib
import logging
import uuid
from datetime import datetime, timezone
import asyncio

# Import scrapers
from crawler import scrape_prime_gaming
from epic import main as epic_scraper
from steam import scrape_steam
from gog_freeGameCollection import scrape_gog
from gog_giveaway import main as gog_giveaway_scraper

# Import newsletter functionality
from newsletter import run_weekly_newsletter
from newsletter_new_games import run_new_games_newsletter
from cleanup import cleanup_unconfirmed_subscribers

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests  # To verify reCAPTCHA
from flask import Flask, request, render_template, jsonify, url_for, send_from_directory, make_response

# Load environment variables
from load_env import load_environment  # Assumes you have a load_env.py to handle .env files

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# Rate Limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Jinja2 for rendering HTML email templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

from functools import wraps

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('Authorization')
        if not api_key or api_key != f"Bearer {os.getenv('API_KEY')}":
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# -------------------------------------------------
# 1. Environment & Logging Setup
# -------------------------------------------------
load_environment()  # Load environment variables from .env files

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Read environment variables
firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")
gmail_username = os.getenv("GMAIL_USERNAME", "")
gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
from_email = os.getenv("FROM_EMAIL", gmail_username)
base_url = os.getenv("BASE_URL", "http://127.0.0.1:5001")

# reCAPTCHA secret key
RECAPTCHA_SECRET = os.getenv("RECAPTCHA_SECRET_KEY", "")

# Environment selection
environment = os.getenv("ENVIRONMENT", "development").lower()

# -------------------------------------------------
# 2. Firebase Initialization
# -------------------------------------------------
try:
    firebase_creds_json = json.loads(firebase_credentials_str)
    cred = credentials.Certificate(firebase_creds_json)
    # Only initialize if not already initialized
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("Firebase initialized successfully.")
except Exception as e:
    logging.error(f"Error initializing Firebase: {e}")
    db = None  # Proceed without Firestore

# -------------------------------------------------
# 3. Flask App & Rate Limiter
# -------------------------------------------------
app = Flask(__name__)

# Initialize Flask-Limiter without passing 'app' as a positional argument
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
limiter.init_app(app)

EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

# -------------------------------------------------
# 4. Jinja2 Environment (for confirmation email)
# -------------------------------------------------
env = Environment(
    loader=FileSystemLoader(searchpath="./templates"),
    autoescape=select_autoescape(["html", "xml"])
)

# -------------------------------------------------
# 5. Helper Functions
# -------------------------------------------------
def is_valid_email(email: str) -> bool:
    """Check if the email has a valid format."""
    return bool(EMAIL_REGEX.match(email))

def email_exists(email: str) -> bool:
    """Check if the email is already in Firestore."""
    if not db:
        logging.error("No Firestore database connection available.")
        return False

    try:
        collection_ref = db.collection("newsletter_subscribers")
        query = collection_ref.where("email", "==", email).stream()
        exists = any(True for _ in query)
        logging.debug(f"Email exists check for '{email}': {exists}")
        return exists
    except Exception as e:
        logging.error(f"Error checking email existence: {e}")
        return False

def send_confirmation_email(to_email: str, confirm_token: str):
    """
    Sends a double opt-in confirmation email with an HTML layout.
    Uses Jinja2 to render 'confirmation_template.html'.
    """
    if not gmail_username or not gmail_app_password:
        logging.warning("Gmail credentials not provided; skipping email send.")
        return

    try:
        template = env.get_template("confirmation_template.html")
        confirm_url = f"{base_url}/confirm/{confirm_token}"

        rendered_html = template.render(
            confirm_url=confirm_url,
            base_url=base_url
        )

        subject = "Please Confirm Your Subscription to WeeklyGameVault"
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = from_email
        message["To"] = to_email

        # Plain text fallback
        text_part = MIMEText(
            f"Hello,\n\n"
            f"Thank you for subscribing to WeeklyGameVault.\n\n"
            f"Please confirm your subscription by clicking here: {confirm_url}\n\n"
            f"If you did not request this, ignore this email.\n\n"
            f"Best regards,\n"
            f"WeeklyGameVault Team",
            "plain",
            "utf-8"
        )
        html_part = MIMEText(rendered_html, "html", "utf-8")

        message.attach(text_part)
        message.attach(html_part)

        # Send email via Gmail SMTP
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(gmail_username, gmail_app_password)
            server.sendmail(from_email, [to_email], message.as_string())

        logging.info(f"Confirmation email sent to {to_email}.")

    except Exception as e:
        logging.error(f"Failed to send confirmation email to {to_email}: {e}")

def verify_recaptcha(response_token: str) -> bool:
    """
    Verifies the reCAPTCHA response token by sending it to Google.
    Returns True if successful, False otherwise.
    """
    if not RECAPTCHA_SECRET:
        logging.warning("No reCAPTCHA secret key set; skipping verification.")
        return True  # Skip verification if secret is not set

    verify_url = "https://www.google.com/recaptcha/api/siteverify"
    payload = {
        "secret": RECAPTCHA_SECRET,
        "response": response_token
    }

    try:
        r = requests.post(verify_url, data=payload)
        data = r.json()
        success = data.get("success", False)
        logging.debug(f"reCAPTCHA verification success: {success}")
        return success
    except Exception as e:
        logging.error(f"reCAPTCHA verification error: {e}")
        return False

# -------------------------------------------------
# 6. Routes
# -------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    """
    Render the home page with an email subscription form.
    The slideshow will fetch games from the new /games_data endpoint.
    """
    # Instead of pointing to a static file, we point to a Firestore-based JSON route
    games_json_path = url_for("games_data")

    current_year = datetime.now(timezone.utc).year

    return render_template(
        "index.html",
        show_slideshow=True,
        games_json_path=games_json_path,
        current_year=current_year
    )

@app.route("/games_data", methods=["GET"])
def games_data():
    """
    Returns JSON game data from Firestore
    (Prime, Epic, GOG Free, GOG Giveaway, Steam).
    Used by the slideshow and anywhere else we need raw JSON.
    """
    if not db:
        return jsonify({"error": "Firestore is not initialized"}), 500

    try:
        prime_docs = db.collection("prime_free_games").stream()
        epic_docs = db.collection("epic_free_games").stream()
        gog_free_docs = db.collection("gog_free_games").stream()
        gog_giveaway_docs = db.collection("gog_giveaway").stream()
        steam_docs = db.collection("steam_free_games").stream()

        data = {
            "prime_games": [doc.to_dict() for doc in prime_docs],
            "epic_games": [doc.to_dict() for doc in epic_docs],
            "gog_free": [doc.to_dict() for doc in gog_free_docs],
            "gog_giveaway": [doc.to_dict() for doc in gog_giveaway_docs],
            "steam_games": [doc.to_dict() for doc in steam_docs],
        }
        return jsonify(data), 200
    except Exception as e:
        logging.error(f"Error reading games from Firestore: {e}")
        return jsonify({"error": "Failed to retrieve games data"}), 500

@app.route("/PrivacyPolicy", methods=["GET"])
def privacy_policy():
    """Render the Privacy Policy page."""
    current_year = datetime.now(timezone.utc).year
    return render_template("PrivacyPolicy.html", current_year=current_year)

@app.route("/contact", methods=["GET", "POST"])
def contact():
    """
    - GET: Show the contact form (contact.html).
    - POST: Verify reCAPTCHA, then send an email to your Gmail if valid.
    - Then show success and redirect to home after 3 seconds.
    """
    if request.method == "GET":
        current_year = datetime.now(timezone.utc).year
        return render_template("contact.html", current_year=current_year)
    else:
        recaptcha_token = request.form.get("g-recaptcha-response", "")
        if not verify_recaptcha(recaptcha_token):
            logging.info("reCAPTCHA failed or missing in contact form.")
            return "reCAPTCHA validation failed. Please go back and try again.", 400

        name = request.form.get("name", "No Name Provided").strip()
        user_email = request.form.get("email", "").strip()
        message_body = request.form.get("message", "").strip()

        if not is_valid_email(user_email):
            logging.info(f"Invalid email format in contact form: {user_email}")
            return "Invalid email address.", 400

        if not gmail_username or not gmail_app_password:
            logging.warning("Gmail credentials not set; skipping contact email.")
            return "Contact form not configured for email."

        try:
            # Prepare email content
            subject = f"Contact Form Submission from {name}"
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email
            msg["To"] = gmail_username  # Send to your Gmail

            text_part = MIMEText(
                f"Name: {name}\nEmail: {user_email}\n\nMessage:\n{message_body}",
                "plain",
                "utf-8"
            )
            html_content = f"""
            <html>
              <body style="font-family: Arial, sans-serif;">
                <p><strong>Name:</strong> {name}</p>
                <p><strong>Email:</strong> {user_email}</p>
                <p><strong>Message:</strong><br>{message_body}</p>
              </body>
            </html>
            """
            html_part = MIMEText(html_content, "html", "utf-8")

            msg.attach(text_part)
            msg.attach(html_part)

            # Send email via Gmail SMTP
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(gmail_username, gmail_app_password)
                server.sendmail(from_email, [gmail_username], msg.as_string())

            logging.info(f"Contact form email sent from {user_email}.")

            # Render success message with redirect
            return """
            <html>
            <head>
            <meta http-equiv="refresh" content="3;url=/" />
            </head>
            <body style="font-family: Arial, sans-serif; text-align: center; margin-top: 50px;">
              <h2>Thank you for contacting us!</h2>
              <p>We will get back to you soon. You will be redirected to the home page.</p>
            </body>
            </html>
            """
        except Exception as e:
            logging.error(f"Failed to send contact form email: {e}")
            return "Failed to send your message. Please try again later.", 500

@app.route("/subscribe", methods=["POST"])
@limiter.limit("5 per minute")
def subscribe():
    """Handles newsletter subscription (double opt-in)."""
    if not db:
        logging.error("Firestore database not initialized.")
        return "Database not initialized. Contact administrator.", 500

    email = request.form.get("email", "").strip()
    frequency = request.form.get("frequency", "").strip()  # "weekly", "newgame", or "both"

    if not is_valid_email(email):
        logging.info(f"Invalid email format attempted for subscription: {email}")
        return "Invalid email address.", 400

    if not frequency or frequency not in ["weekly", "newgame", "both"]:
        logging.info(f"Invalid or missing frequency option for email: {email}")
        return "Please select a valid newsletter frequency.", 400

    if email_exists(email):
        logging.info(f"Duplicate email subscription attempt: {email}")
        return "That email is already subscribed.", 409  # Conflict

    confirm_token = str(uuid.uuid4())

    try:
        # Add subscriber to Firestore
        doc_ref = db.collection("newsletter_subscribers").document()
        doc_ref.set({
            "email": email,
            "frequency": frequency,
            "confirm_token": confirm_token,
            "confirmed": False,
            "createdAt": datetime.now(timezone.utc),
            "confirmedAt": None
        })
        logging.info(f"New subscriber added: {email}")
    except Exception as e:
        logging.error(f"Error writing subscription to Firestore for {email}: {e}")
        return "Internal server error.", 500

    # Send confirmation email
    send_confirmation_email(email, confirm_token)

    return "Thank you for subscribing! Please check your email to confirm."

@app.route("/confirm/<token>", methods=["GET"])
def confirm_subscription(token):
    """User clicks link in their email to confirm subscription."""
    if not db:
        logging.error("Firestore database not initialized.")
        return "Database not initialized. Contact administrator.", 500

    try:
        # Query Firestore for the subscriber with the given token and not yet confirmed
        docs = db.collection("newsletter_subscribers") \
                 .where("confirm_token", "==", token) \
                 .where("confirmed", "==", False) \
                 .stream()

        confirmed_email = None
        for doc in docs:
            doc_data = doc.to_dict()
            confirmed_email = doc_data.get("email")
            doc.reference.update({
                "confirmed": True,
                "confirmedAt": datetime.now(timezone.utc)
            })
            logging.info(f"Subscription confirmed for {confirmed_email}")
            break  # Only one matching document

        if confirmed_email:
            return f"Thank you! {confirmed_email} is now confirmed for the newsletter."
        else:
            logging.warning(f"Invalid or expired confirmation token: {token}")
            return "Invalid or expired confirmation link."

    except Exception as e:
        logging.error(f"Error confirming subscription with token {token}: {e}")
        return "Internal server error.", 500

@app.route("/unsubscribe/<token>", methods=["GET"])
def unsubscribe(token):
    """
    Removes the subscriber with the matching confirm_token from Firestore.
    Reuses 'confirm_token' for unsubscribing as well.
    """
    if not db:
        logging.error("Firestore database not initialized.")
        return "Database not initialized. Contact administrator.", 500

    try:
        # Query Firestore for the subscriber with the given token
        docs = db.collection("newsletter_subscribers") \
                 .where("confirm_token", "==", token) \
                 .stream()

        unsubscribed_email = None
        for doc in docs:
            unsubscribed_email = doc.to_dict().get("email")
            doc.reference.delete()
            logging.info(f"Subscriber unsubscribed: {unsubscribed_email}")
            break  # Only one matching document

        if unsubscribed_email:
            return f"You have unsubscribed from the newsletter for {unsubscribed_email}."
        else:
            logging.warning(f"Invalid or expired unsubscribe token: {token}")
            return "Invalid or expired unsubscribe link."

    except Exception as e:
        logging.error(f"Error unsubscribing with token {token}: {e}")
        return "Internal server error.", 500

@app.route("/AvailableGames", methods=["GET"])
def available_games():
    """
    Renders the Available Games page by loading data directly from Firestore
    (instead of any static file).
    """
    if not db:
        logging.error("Firestore database not initialized.")
        data = {
            "prime_games": [],
            "epic_games": [],
            "gog_free": [],
            "gog_giveaway": [],
            "steam_games": []
        }
    else:
        try:
            prime_docs = db.collection("prime_free_games").stream()
            epic_docs = db.collection("epic_free_games").stream()
            gog_free_docs = db.collection("gog_free_games").stream()
            gog_giveaway_docs = db.collection("gog_giveaway").stream()
            steam_docs = db.collection("steam_free_games").stream()

            data = {
                "prime_games": [d.to_dict() for d in prime_docs],
                "epic_games": [d.to_dict() for d in epic_docs],
                "gog_free": [d.to_dict() for d in gog_free_docs],
                "gog_giveaway": [d.to_dict() for d in gog_giveaway_docs],
                "steam_games": [d.to_dict() for d in steam_docs]
            }
            logging.info("Loaded available games from Firestore.")
        except Exception as e:
            logging.error(f"Error loading from Firestore: {e}")
            data = {
                "prime_games": [],
                "epic_games": [],
                "gog_free": [],
                "gog_giveaway": [],
                "steam_games": []
            }

    current_year = datetime.now(timezone.utc).year

    return render_template(
        "available_games.html",
        prime_games=data.get("prime_games", []),
        epic_games=data.get("epic_games", []),
        gog_free=data.get("gog_free", []),
        gog_giveaway=data.get("gog_giveaway", []),
        steam_games=data.get("steam_games", []),
        current_year=current_year
    )

@app.route("/change-frequency/<token>", methods=["GET", "POST"])
def change_frequency(token):
    """
    Allows a user to change their newsletter frequency via a link in the newsletter.
    """
    if not db:
        logging.error("Firestore database not initialized.")
        return "Database not initialized. Contact administrator.", 500

    if request.method == "GET":
        current_year = datetime.now(timezone.utc).year
        return render_template("change_frequency.html", token=token, current_year=current_year)
    else:
        # POST request to update frequency
        new_freq = request.form.get("frequency", "").strip()  # "weekly", "newgame", or "both"
        if new_freq not in ["weekly", "newgame", "both"]:
            logging.info(f"Invalid frequency option provided: {new_freq}")
            return "Invalid frequency choice.", 400

        try:
            docs = db.collection("newsletter_subscribers") \
                     .where("confirm_token", "==", token) \
                     .stream()

            updated = False
            for doc in docs:
                doc.reference.update({"frequency": new_freq})
                updated = True
                logging.info(f"Newsletter frequency updated to '{new_freq}' for {doc.to_dict().get('email')}")
                break

            if updated:
                return f"Your frequency has been updated to '{new_freq}'. Thank you!"
            else:
                logging.warning(f"Invalid or expired frequency change token: {token}")
                return "Invalid or expired token. Could not update frequency."

        except Exception as e:
            logging.error(f"Error updating frequency with token {token}: {e}")
            return "Internal server error.", 500

@app.route("/run/<task>", methods=["POST"])
@require_api_key
async def run_task(task):
    try:
        if task == "crawler":
            await scrape_prime_gaming()
        elif task == "epic":
            epic_scraper()  # Not async
        elif task == "steam":
            await scrape_steam()
        elif task == "gog_free":
            await scrape_gog()
        elif task == "gog_giveaway":
            await gog_giveaway_scraper()
        elif task == "newsletter":
            run_weekly_newsletter()  # Not async
        elif task == "newsletter_new_games":
            run_new_games_newsletter()  # Not async
        elif task == "cleanup":
            cleanup_unconfirmed_subscribers()  # Not async
        else:
            return jsonify({"error": f"Unknown task: {task}"}), 400

        return jsonify({"message": f"Task {task} completed successfully"}), 200
    except Exception as e:
        logging.error(f"Error running task {task}: {str(e)}")
        return jsonify({"error": f"Error running task: {str(e)}"}), 500

# -------------------------------------------------
# RSS Feed Routes
# -------------------------------------------------
@app.route("/rss_feed_raw.xml", methods=["GET"])
def rss_feed_raw():
    """
    Generate and serve the raw RSS feed from Firestore data
    (instead of static JSON files).
    """
    if not db:
        return make_response("Firestore not initialized.", 500)

    try:
        prime_docs = db.collection("prime_free_games").stream()
        epic_docs = db.collection("epic_free_games").stream()
        gog_free_docs = db.collection("gog_free_games").stream()
        gog_giveaway_docs = db.collection("gog_giveaway").stream()
        steam_docs = db.collection("steam_free_games").stream()

        games_data = {
            "prime_games": [d.to_dict() for d in prime_docs],
            "epic_games": [d.to_dict() for d in epic_docs],
            "gog_free": [d.to_dict() for d in gog_free_docs],
            "gog_giveaway": [d.to_dict() for d in gog_giveaway_docs],
            "steam_games": [d.to_dict() for d in steam_docs]
        }

        last_build_date = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')

        # Render the raw RSS feed template
        rss_content = render_template(
            "rss_feed.xml",
            games_data=games_data,
            last_build_date=last_build_date
        )
        return make_response(rss_content, 200, {"Content-Type": "application/rss+xml"})
    except Exception as e:
        logging.error(f"Error generating RSS feed: {e}")
        return make_response("Internal server error.", 500)

@app.route("/rss", methods=["GET"])
def rss_feed():
    """Render the RSS feed subscription guide."""
    rss_url = f"{base_url}/rss_feed_raw.xml"
    return render_template("rss_feed.html", rss_url=rss_url)

# -------------------------------------------------
# 7. Legal Notice Route (NEW)
# -------------------------------------------------
@app.route("/LegalNotice", methods=["GET"])
def legal_notice():
    """
    Renders the Legal Notice page.
    """
    current_year = datetime.now(timezone.utc).year
    return render_template("legal_notice.html", current_year=current_year)

# -------------------------------------------------
# 8. Main Entry Point
# -------------------------------------------------
if __name__ == "__main__":
    # Run the Flask app
    app.run(debug=True, host="0.0.0.0", port=5001)
