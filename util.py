# util.py

import os
import re
import json
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
import firebase_admin
from firebase_admin import credentials, firestore
import logging

###############################################################################
# 1. Basic Utility Functions
###############################################################################

def resolve_path(*args):
    """
    Resolves a path relative to the current file's directory.
    """
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *args)

def sanitize(text):
    """
    Sanitizes a string to be filesystem-friendly by replacing non-alphanumeric characters
    (excluding underscores and hyphens) with underscores.
    """
    return re.sub(r'[^a-zA-Z0-9_-]+', '_', text)

def get_current_datetime():
    """
    Returns the current UTC datetime as a formatted string.
    """
    return datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S UTC')

def html_game_list(games):
    """
    Builds an HTML unordered list from a list of game dictionaries.
    Each game should have 'title', 'url', and 'imageUrl' keys.
    """
    html = '<ul>'
    for game in games:
        title = game.get("title", "No Title")
        url = game.get("url", "#")
        image_url = game.get("imageUrl", "")
        html += f'''
            <li>
                <a href="{url}">{title}</a><br>
                <img src="{image_url}" alt="{title}" width="200">
            </li>
        '''
    html += '</ul>'
    return html

###############################################################################
# 2. Firebase Initialization
###############################################################################

# Configure logging for Firebase helper
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def initialize_firebase():
    """
    Initializes Firebase based on the current environment (development or production).
    Returns the Firestore client or None if initialization fails.
    """
    if not firebase_admin._apps:
        environment = os.getenv("ENVIRONMENT", "development").lower()
        
        if environment == "production":
            firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")
            if not firebase_credentials_str:
                logging.error("FIREBASE_CREDENTIALS_PROD is empty. Check your config.env.production file.")
                return None
        else:
            firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")
            if not firebase_credentials_str:
                logging.error("FIREBASE_CREDENTIALS is empty. Check your config.env.development file.")
                return None

        try:
            firebase_creds_json = json.loads(firebase_credentials_str)
            cred = credentials.Certificate(firebase_creds_json)
            firebase_admin.initialize_app(cred)
            db = firestore.client()
            logging.info(f"Firebase initialized successfully for '{environment}' environment.")
            return db
        except json.JSONDecodeError as e:
            logging.error(f"Failed to parse Firebase credentials JSON: {e}")
            return None
        except Exception as e:
            logging.error(f"Error initializing Firebase for '{environment}' environment: {e}")
            return None
    else:
        db = firestore.client()
        logging.info("Firebase already initialized.")
        return db

# Initialize Firebase and get the Firestore client
db = initialize_firebase()

###############################################################################
# 3. Send Email (Dev vs. Prod aware)
###############################################################################

def send_email(subject, content, to=None):
    """
    Sends an HTML email using Gmail's SMTP server.

    The environment variables used:
    - ENVIRONMENT (development or production)
    - FROM_EMAIL
    - TO_EMAIL (default recipient if 'to' not supplied)
    - GMAIL_USERNAME
    - GMAIL_APP_PASSWORD
    """
    # Check environment
    environment = os.getenv('ENVIRONMENT', 'development').lower()

    from_email = os.getenv('FROM_EMAIL')
    gmail_username = os.getenv('GMAIL_USERNAME')
    gmail_password = os.getenv('GMAIL_APP_PASSWORD')

    # If no explicit 'to' was provided, use the default
    if not to:
        to = os.getenv('TO_EMAIL')  # fallback to the environment variable

    if not all([from_email, to, gmail_username, gmail_password]):
        print("Email config incomplete. Check FROM_EMAIL, TO_EMAIL, GMAIL_USERNAME, GMAIL_APP_PASSWORD.")
        return

    if environment == 'development':
        # For safety, you might override the recipient here, if desired.
        pass

    msg = MIMEText(content, 'html')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_username, gmail_password)
            server.sendmail(from_email, [to], msg.as_string())
        print(f'[Email] {environment} => Sent successfully to {to}.')
    except Exception as e:
        print(f'[Email] Failed to send to {to}:', e)
