# app.py

import os
import json
import re
import smtplib
import logging
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, request, render_template
from dotenv import load_dotenv

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# Rate Limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# -------------------------------------------------
# 1. Environment & Logging Setup
# -------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Read environment variables
firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")
gmail_username = os.getenv("GMAIL_USERNAME", "")
gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")
from_email = os.getenv("FROM_EMAIL", gmail_username)  # fallback to your Gmail address

if not firebase_credentials_str:
    logging.error("FIREBASE_CREDENTIALS env var is not set.")
if not gmail_username or not gmail_app_password:
    logging.warning("GMAIL_USERNAME or GMAIL_APP_PASSWORD is not set; emails won't be sent.")

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

# Set up the limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day"]  # Global default limit (example: 200 requests per day)
)

EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

# -------------------------------------------------
# 4. Helper Functions
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

def send_confirmation_email(to_email: str, unsubscribe_token: str):
    """
    Sends an HTML-based confirmation email via Gmail's SMTP, 
    including an unsubscribe button link.
    """
    if not gmail_username or not gmail_app_password:
        logging.warning("Gmail credentials not provided; skipping confirmation email.")
        return

    subject = "Thank you for subscribing to our Newsletter!"

    # Build the unsubscribe link
    # request.url_root is something like 'http://127.0.0.1:5001/'
    # but here we only have that in the route. For safety, we can manually build or pass it.
    # Alternatively, you can store your domain in an env variable. For local dev:
    unsubscribe_url = f"http://127.0.0.1:5001/unsubscribe/{unsubscribe_token}"

    # Create an HTML email body with an unsubscribe button
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif;">
        <p>Hello,</p>
        <p>Thank you for subscribing to our newsletter! We'll keep you updated about free games!</p>
        <p>
          Best regards,<br>
          All the free games
        </p>
        <p> You did not subscribe to our Newsletter? Just click the Unsubscribe button and you'll never hear from us again! </p>
        <p style="margin-top: 20px;">
          <a
            href="{unsubscribe_url}"
            style="
              display: inline-block;
              padding: 10px 15px;
              background: #dc3545;
              color: #ffffff;
              text-decoration: none;
              border-radius: 4px;
            "
          >
            Unsubscribe
          </a>
        </p>
      </body>
    </html>
    """

    # Construct the email as multipart in case you want text + HTML
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email

    # We can add a plain-text fallback if desired
    text_part = MIMEText(
        "Hello,\n\n"
        "Thank you for subscribing to our newsletter! We'll keep you updated.\n\n"
        "Best regards,\nYour Company\n\n"
        f"Unsubscribe link: {unsubscribe_url}",
        "plain",
        "utf-8"
    )
    html_part = MIMEText(html_content, "html", "utf-8")

    # Attach both parts to the message (plain text and HTML)
    message.attach(text_part)
    message.attach(html_part)

    # Send via Gmail SMTP
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(gmail_username, gmail_app_password)
        server.sendmail(from_email, [to_email], message.as_string())
        server.quit()
        logging.info(f"Confirmation email sent to {to_email}.")
    except Exception as e:
        logging.error(f"Failed to send confirmation email: {e}")

# -------------------------------------------------
# 5. Routes
# -------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    """Render the home page with an email subscription form."""
    return render_template("index.html")

@limiter.limit("5 per minute", override_defaults=False)
@app.route("/subscribe", methods=["POST"])
def subscribe():
    """
    Receive the email, validate it, check duplicates, store, send confirmation.
    Rate-limited to 5 requests/minute per IP (returns 429 on overload).
    """
    if not db:
        return "Database not initialized. Contact administrator.", 500

    email = request.form.get("email", "").strip()

    # Validate email format
    if not is_valid_email(email):
        logging.info(f"Invalid email format attempted: {email}")
        return "Invalid email address.", 400

    # Check duplicates
    if email_exists(email):
        logging.info(f"Duplicate email detected: {email}")
        return "That email is already subscribed.", 409

    # Generate an unsubscribe token
    unsubscribe_token = str(uuid.uuid4())

    # Add to Firestore
    try:
        doc_ref = db.collection("newsletter_subscribers").document()
        doc_ref.set({
            "email": email,
            "unsubscribe_token": unsubscribe_token
        })
        logging.info(f"New subscriber added: {email}")
    except Exception as e:
        logging.error(f"Error writing email to Firestore: {e}")
        return "Internal server error.", 500

    # Send confirmation with unsubscribe button
    send_confirmation_email(email, unsubscribe_token)

    return "Thank you for subscribing!"

@app.route("/unsubscribe/<token>", methods=["GET"])
def unsubscribe(token):
    """
    When the user clicks the "Unsubscribe" link/button from the email,
    we remove (or update) their document in Firestore.
    """
    if not db:
        return "Database not initialized. Contact administrator.", 500

    # Find the document that has this unsubscribe_token
    docs = db.collection("newsletter_subscribers") \
             .where("unsubscribe_token", "==", token) \
             .stream()

    unsubscribed_email = None
    for doc in docs:
        unsubscribed_email = doc.to_dict().get("email")
        # Remove (delete) their doc from Firestore:
        doc.reference.delete()
        break

    if unsubscribed_email:
        return f"You have unsubscribed from the newsletter for {unsubscribed_email}."
    else:
        return "Invalid or expired unsubscribe link."

# -------------------------------------------------
# 6. Main Entry Point
# -------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
