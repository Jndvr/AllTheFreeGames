# util.py

import os
import re
from datetime import datetime, timezone
import smtplib
from email.mime.text import MIMEText

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

def send_email(subject, content):
    """
    Sends an HTML email using Gmail's SMTP server.
    
    Environment Variables Required:
    - FROM_EMAIL: The sender's email address.
    - TO_EMAIL: The recipient's email address.
    - GMAIL_USERNAME: Your Gmail username (usually your email address).
    - GMAIL_APP_PASSWORD: Your Gmail App Password.
    """
    from_email = os.getenv('FROM_EMAIL')
    to_email = os.getenv('TO_EMAIL')  # Changed to separate 'TO_EMAIL'
    gmail_username = os.getenv('GMAIL_USERNAME')
    gmail_password = os.getenv('GMAIL_APP_PASSWORD')

    if not all([from_email, to_email, gmail_username, gmail_password]):
        print("Email configuration is incomplete. Please set FROM_EMAIL, TO_EMAIL, GMAIL_USERNAME, and GMAIL_APP_PASSWORD in your environment.")
        return

    msg = MIMEText(content, 'html')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_username, gmail_password)
            server.sendmail(from_email, [to_email], msg.as_string())
        print(f'Email sent successfully to {to_email}.')
    except Exception as e:
        print(f'Failed to send email to {to_email}:', e)

# util.py (or wherever you put this helper function)
import os
import json
from datetime import datetime
from google.cloud.firestore_v1 import DocumentSnapshot

def write_static_games_file(db):
    """
    Reads from prime_free_games, epic_free_games, gog_free_games, gog_giveaway
    and writes a local JSON file for the /AvailableGames route to serve.
    Converts Firestore timestamps to string to avoid JSON serialization errors.
    """

    data = {
        "prime_games": [],
        "epic_games": [],
        "gog_free": [],
        "gog_giveaway": []
    }

    # Helper: convert Firestore doc to dict and fix timestamps
    def doc_to_serializable(doc):
        d = doc.to_dict()
        for k, v in d.items():
            # If it's a Firestore Timestamp or 'DatetimeWithNanoseconds', convert to iso string
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        return d

    # prime
    prime_docs = db.collection("prime_free_games").stream()
    data["prime_games"] = [doc_to_serializable(doc) for doc in prime_docs]

    # epic
    epic_docs = db.collection("epic_free_games").stream()
    data["epic_games"] = [doc_to_serializable(doc) for doc in epic_docs]

    # old GOG freebies
    gog_docs = db.collection("gog_free_games").stream()
    data["gog_free"] = [doc_to_serializable(doc) for doc in gog_docs]

    # new GOG giveaways
    gog_giveaway_docs = db.collection("gog_giveaway").stream()
    data["gog_giveaway"] = [doc_to_serializable(doc) for doc in gog_giveaway_docs]

    # Save to a local file, e.g. 'static_data/all_games.json'
    os.makedirs("static_data", exist_ok=True)
    path = os.path.join("static_data", "all_games.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Static file '{path}' updated successfully!")
