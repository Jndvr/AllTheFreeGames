import os
import json
import logging
import datetime

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

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

    cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    subscribers_ref = db.collection("newsletter_subscribers") \
                        .where("confirmed", "==", False) \
                        .where("createdAt", "<", cutoff_time)
    docs = subscribers_ref.stream()

    for doc in docs:
        doc.reference.delete()
        logging.info(f"Deleted unconfirmed subscriber: {doc.id} (older than 7 days).")

if __name__ == "__main__":
    initialize_firebase()
    cleanup_unconfirmed_subscribers()
