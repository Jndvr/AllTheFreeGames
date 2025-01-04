#will run once per day to clean up mails that are not confirmed within a week

import os
import json
import logging
import datetime
from datetime import timezone
import warnings

import firebase_admin
from firebase_admin import credentials, firestore

# Load environment depending on ENVIRONMENT
from load_env import load_environment
load_environment()

# Suppress UserWarnings about Firestore filters
warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")

def initialize_firebase():
    global db
    try:
        if not firebase_credentials_str:
            raise ValueError("FIREBASE_CREDENTIALS is empty. Check your .env file.")
        creds_json = json.loads(firebase_credentials_str)
        cred = credentials.Certificate(creds_json)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logging.info("Firebase initialized successfully in cleanup.py.")
    except Exception as e:
        logging.error(f"Error initializing Firebase in cleanup.py: {e}")
        db = None

def cleanup_unconfirmed_subscribers():
    """
    Removes newsletter_subscribers who haven't confirmed within 7 days.
    """
    if not db:
        logging.error("Database is not initialized. Aborting cleanup.")
        return

    # Adjusted to use timezone-aware datetime
    cutoff_time = datetime.datetime.now(timezone.utc) - datetime.timedelta(days=7)
    deleted_count = 0  # Counter to track the number of deleted documents

    try:
        subscribers_ref = db.collection("newsletter_subscribers")
        subscribers_ref = subscribers_ref.where("confirmed", "==", False)
        subscribers_ref = subscribers_ref.where("createdAt", "<", cutoff_time)
        docs = subscribers_ref.stream()

        for doc in docs:
            doc.reference.delete()
            logging.info(f"Deleted unconfirmed subscriber: {doc.id} (older than 7 days).")
            deleted_count += 1

        if deleted_count == 0:
            logging.info("No unconfirmed subscribers were found for deletion.")
        else:
            logging.info(f"Cleanup completed. Total deleted unconfirmed subscribers: {deleted_count}")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

if __name__ == "__main__":
    initialize_firebase()
    cleanup_unconfirmed_subscribers()
