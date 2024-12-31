import os
import json
import re
import smtplib
import logging
import uuid
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests  # To verify reCAPTCHA
from flask import Flask, request, render_template
from dotenv import load_dotenv

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# Rate Limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Jinja2 for rendering HTML email templates
from jinja2 import Environment, FileSystemLoader, select_autoescape

# -------------------------------------------------
# 1. Environment & Logging Setup
# -------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Read environment variables from .env
firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")
gmail_username = os.getenv("GMAIL_USERNAME", "")
gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
from_email = os.getenv("FROM_EMAIL", gmail_username)
base_url = os.getenv("BASE_URL", "http://127.0.0.1:5001")

# reCAPTCHA secret key
RECAPTCHA_SECRET = os.getenv("RECAPTCHA_SECRET_KEY", "")

if not firebase_credentials_str:
    logging.error("FIREBASE_CREDENTIALS env var is not set.")
if not gmail_username or not gmail_app_password:
    logging.warning("GMAIL_USERNAME or GMAIL_APP_PASSWORD is not set; emails won't be sent.")
if not RECAPTCHA_SECRET:
    logging.warning("RECAPTCHA_SECRET_KEY is not set; reCAPTCHA verification is disabled.")

# -------------------------------------------------
# 2. Firebase Initialization
# -------------------------------------------------
try:
    firebase_creds_json = json.loads(firebase_credentials_str)
    cred = credentials.Certificate(firebase_creds_json)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    logging.info("Firebase initialized successfully.")
except Exception as e:
    logging.error(f"Error initializing Firebase: {e}")
    db = None  # handle gracefully later if needed

# -------------------------------------------------
# 3. Flask App & Rate Limiter
# -------------------------------------------------
app = Flask(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day"]
)

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
        logging.error("No database connection available.")
        return False

    collection_ref = db.collection("newsletter_subscribers")
    query = collection_ref.where("email", "==", email).stream()
    return any(True for _ in query)

def send_confirmation_email(to_email: str, confirm_token: str):
    """
    Sends a double opt-in confirmation email with a nice HTML layout.
    Uses Jinja2 to render 'confirmation_template.html'.
    """
    if not gmail_username or not gmail_app_password:
        logging.warning("Gmail credentials not provided; skipping email send.")
        return

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

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(gmail_username, gmail_app_password)
        server.sendmail(from_email, [to_email], message.as_string())
        server.quit()
        logging.info(f"Confirmation email sent to {to_email}.")
    except Exception as e:
        logging.error(f"Failed to send confirmation email: {e}")

def verify_recaptcha(response_token: str) -> bool:
    """
    Verifies the reCAPTCHA response token by sending it to Google.
    Returns True if successful, False otherwise.
    """
    if not RECAPTCHA_SECRET:
        logging.warning("No reCAPTCHA secret key set; skipping verification.")
        return True  # In dev, skip. In production, better to fail if not set.

    verify_url = "https://www.google.com/recaptcha/api/siteverify"
    payload = {
        "secret": RECAPTCHA_SECRET,
        "response": response_token
    }

    try:
        r = requests.post(verify_url, data=payload)
        data = r.json()
        return data.get("success", False)
    except Exception as e:
        logging.error(f"reCAPTCHA verification error: {e}")
        return False

# -------------------------------------------------
# 6. Routes
# -------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    """Render the home page with an email subscription form."""
    return render_template("index.html")

@app.route("/LegalNotice", methods=["GET"])
def impressum():
    """Render the Impressum page."""
    return render_template("LegalNotice.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    """
    - GET: Show the contact form (contact.html).
    - POST: Verify reCAPTCHA, then send an email to your Gmail if valid.
    - Then show success and redirect to home after 3 seconds.
    """
    if request.method == "GET":
        return render_template("contact.html")
    else:
        recaptcha_token = request.form.get("g-recaptcha-response", "")
        if not verify_recaptcha(recaptcha_token):
            logging.info("reCAPTCHA failed or missing.")
            return "reCAPTCHA validation failed. Please go back and try again.", 400

        name = request.form.get("name", "No Name Provided")
        user_email = request.form.get("email", "").strip()
        message_body = request.form.get("message", "")

        if not gmail_username or not gmail_app_password:
            logging.warning("Gmail credentials not set; skipping contact email.")
            return "Contact form not configured for email."

        subject = f"Contact Form Submission from {name}"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = gmail_username  # your Gmail

        text_part = MIMEText(
            f"Name: {name}\nEmail: {user_email}\n\nMessage:\n{message_body}",
            "plain",
            "utf-8"
        )
        msg.attach(text_part)

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
        msg.attach(html_part)

        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(gmail_username, gmail_app_password)
                server.sendmail(from_email, [gmail_username], msg.as_string())
            logging.info(f"Contact form email sent from {user_email}.")

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
            logging.error(f"Failed to send contact email: {e}")
            return "Failed to send your message. Please try again later.", 500

@limiter.limit("5 per minute", override_defaults=False)
@app.route("/subscribe", methods=["POST"])
def subscribe():
    """Handles newsletter subscription (double opt-in)."""
    if not db:
        return "Database not initialized. Contact administrator.", 500

    email = request.form.get("email", "").strip()
    frequency = request.form.get("frequency", "").strip()  # "weekly" or "newgame"

    if not is_valid_email(email):
        logging.info(f"Invalid email format attempted: {email}")
        return "Invalid email address.", 400
    if not frequency:
        return "Please select how often you want to receive the newsletter.", 400

    if email_exists(email):
        logging.info(f"Duplicate email detected: {email}")
        return "That email is already subscribed.", 409

    confirm_token = str(uuid.uuid4())
    try:
        doc_ref = db.collection("newsletter_subscribers").document()
        doc_ref.set({
            "email": email,
            "frequency": frequency,
            "confirm_token": confirm_token,
            "confirmed": False,
            "createdAt": datetime.datetime.utcnow(),
            "confirmedAt": None
        })
        logging.info(f"New subscriber added: {email}")
    except Exception as e:
        logging.error(f"Error writing email to Firestore: {e}")
        return "Internal server error.", 500

    send_confirmation_email(email, confirm_token)
    return "Thank you for subscribing! Please check your email to confirm."

@app.route("/confirm/<token>", methods=["GET"])
def confirm_subscription(token):
    """User clicks link in their email to confirm subscription."""
    if not db:
        return "Database not initialized. Contact administrator.", 500

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
            "confirmedAt": datetime.datetime.utcnow()
        })
        break

    if confirmed_email:
        return f"Thank you! {confirmed_email} is now confirmed for the newsletter."
    else:
        return "Invalid or expired confirmation link."

@app.route("/unsubscribe/<token>", methods=["GET"])
def unsubscribe(token):
    """
    Removes the doc with the matching confirm_token from Firestore.
    We reuse 'confirm_token' for unsubscribing as well.
    """
    if not db:
        return "Database not initialized. Contact administrator.", 500

    docs = db.collection("newsletter_subscribers") \
             .where("confirm_token", "==", token) \
             .stream()

    unsubscribed_email = None
    for doc in docs:
        unsubscribed_email = doc.to_dict().get("email")
        doc.reference.delete()
        break

    if unsubscribed_email:
        return f"You have unsubscribed from the newsletter for {unsubscribed_email}."
    else:
        return "Invalid or expired unsubscribe link."

# -------------------------------------------------
# 7. Main Entry Point
# -------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
