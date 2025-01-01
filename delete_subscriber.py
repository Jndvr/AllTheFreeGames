#delete a specific mail from the database with command python3 delete_subscriber.py -e user@example.com

import os
import json
import logging
import argparse
import warnings

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# Suppress UserWarnings about Firestore filters
warnings.filterwarnings("ignore", category=UserWarning)

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Retrieve Firebase credentials from environment variables
firebase_credentials_str = os.getenv("FIREBASE_CREDENTIALS", "")

def initialize_firebase():
    """
    Initializes the Firebase app and returns the Firestore client.
    """
    try:
        if not firebase_credentials_str:
            raise ValueError("FIREBASE_CREDENTIALS is empty. Check your .env file.")
        creds_json = json.loads(firebase_credentials_str)
        cred = credentials.Certificate(creds_json)
        # Initialize Firebase app if not already initialized
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
            logging.info("Firebase initialized successfully.")
        else:
            logging.info("Firebase already initialized.")
        db = firestore.client()
        return db
    except Exception as e:
        logging.error(f"Error initializing Firebase: {e}")
        return None

def cleanup_by_email(db, email):
    """
    Deletes documents in the 'newsletter_subscribers' collection that match the provided email.

    Args:
        db (firestore.Client): The Firestore client.
        email (str): The email address to clean up.
    """
    if not db:
        logging.error("Database is not initialized. Aborting cleanup.")
        return

    deleted_count = 0  # Counter for deleted documents

    try:
        subscribers_ref = db.collection("newsletter_subscribers")
        query = subscribers_ref.where("email", "==", email)
        docs = query.stream()

        for doc in docs:
            doc.reference.delete()
            logging.info(f"Deleted subscriber: {doc.id} with email: {email}")
            deleted_count += 1

        if deleted_count == 0:
            logging.info(f"No subscribers found with email: {email}")
        else:
            logging.info(f"Cleanup completed. Total deleted subscribers: {deleted_count}")
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

def parse_arguments():
    """
    Parses command-line arguments.

    Returns:
        argparse.Namespace: Parsed arguments containing the email.
    """
    parser = argparse.ArgumentParser(description="Firestore Cleanup Script for a Specific Email")
    parser.add_argument(
        "-e", "--email",
        type=str,
        required=True,
        help="The email address to clean up from Firestore."
    )
    return parser.parse_args()

def main():
    # Parse command-line arguments
    args = parse_arguments()
    email = args.email.strip().lower()

    if not email:
        logging.error("No email address provided. Use the -e or --email flag to specify an email.")
        return

    # Initialize Firebase
    db = initialize_firebase()

    # Perform cleanup
    cleanup_by_email(db, email)

if __name__ == "__main__":
    main()
