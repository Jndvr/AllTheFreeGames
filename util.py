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
