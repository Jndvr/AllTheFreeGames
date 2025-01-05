# util.py

import os
import re
import json
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from google.cloud.firestore_v1 import DocumentSnapshot

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
# 2. Send Email (Dev vs. Prod aware)
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

    # If in dev environment and you want to override 'to' with a dev address,
    # you could do something like:
    if environment == 'development':
        # For safety, you might want to ensure you don't accidentally send to real users in dev
        # to = "mytestaddress@domain.com"
        pass

    msg = MIMEText(content, 'html')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to

    try:
        # Use SSL or TLS approach
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_username, gmail_password)
            server.sendmail(from_email, [to], msg.as_string())
        print(f'[Email] {environment} => Sent successfully to {to}.')
    except Exception as e:
        print(f'[Email] Failed to send to {to}:', e)

###############################################################################
# 3. Write Static Games File (Dev vs. Prod aware)
###############################################################################

def write_static_games_file(db):
    """
    Reads from prime_free_games, epic_free_games, gog_free_games, gog_giveaway and
    steam_games and writes a local JSON file for the /AvailableGames route to serve.
    Converts Firestore timestamps to string to avoid JSON serialization errors.

    If ENVIRONMENT=development, writes to 'all_games_dev.json'
    Otherwise, writes to 'all_games.json'
    """
    if not db:
        print("Database not initialized in write_static_games_file().")
        return

    environment = os.getenv('ENVIRONMENT', 'development').lower()
    data = {
        "prime_games": [],
        "epic_games": [],
        "gog_free": [],
        "gog_giveaway": [],
        "steam_games": []
    }

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

    # steam
    steam_docs = db.collection("steam_free_games").stream()
    data["steam_games"] = [doc_to_serializable(doc) for doc in steam_docs]

    # Decide the output filename by environment
    filename = "all_games.json" if environment == "production" else "all_games_dev.json"

    os.makedirs("static_data", exist_ok=True)
    path = os.path.join("static_data", filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Static file '{path}' updated successfully! [ENV={environment}]")
