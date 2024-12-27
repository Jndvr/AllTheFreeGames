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

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day"]  # e.g., 200 requests/day globally
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

    # Use BASE_URL env var if deploying on Render (or fallback locally)
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:5001")
    unsubscribe_url = f"{base_url}/unsubscribe/{unsubscribe_token}"

    # Keep your custom text
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

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email

    text_part = MIMEText(
        "Hello,\n\n"
        "Thank you for subscribing to our newsletter! We'll keep you updated.\n\n"
        "Best regards,\nYour Company\n\n"
        f"Unsubscribe link: {unsubscribe_url}",
        "plain",
        "utf-8"
    )
    html_part = MIMEText(html_content, "html", "utf-8")

    message.attach(text_part)
    message.attach(html_part)

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
    Rate-limited to 5 requests/minute per IP (429 on overload).
    Saves email & unsubscribe_token, then sends a confirmation.
    """
    if not db:
        return "Database not initialized. Contact administrator.", 500

    email = request.form.get("email", "").strip()

    # Validate
    if not is_valid_email(email):
        logging.info(f"Invalid email format attempted: {email}")
        return "Invalid email address.", 400

    # Check duplicates
    if email_exists(email):
        logging.info(f"Duplicate email detected: {email}")
        return "That email is already subscribed.", 409

    # Generate token & save
    unsubscribe_token = str(uuid.uuid4())
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

    # Send confirmation
    send_confirmation_email(email, unsubscribe_token)
    return "Thank you for subscribing!"

@app.route("/unsubscribe/<token>", methods=["GET"])
def unsubscribe(token):
    """
    Removes the doc with the matching unsubscribe_token from Firestore.
    """
    if not db:
        return "Database not initialized. Contact administrator.", 500

    docs = db.collection("newsletter_subscribers") \
             .where("unsubscribe_token", "==", token) \
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
# 6. Main Entry Point
# -------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
