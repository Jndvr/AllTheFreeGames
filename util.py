import os
import re
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

def resolve_path(*args):
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), *args)

def sanitize(text):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text)

def get_current_datetime():
    return datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')

def html_game_list(games):
    html = '<ul>'
    for game in games:
        html += f'<li><a href="{game["url"]}">{game["title"]}</a><br><img src="{game["imageUrl"]}" alt="{game["title"]}" width="200"></li>'
    html += '</ul>'
    return html

def send_email(subject, content):
    from_email = os.getenv('FROM_EMAIL')
    to_email = os.getenv('FROM_EMAIL')  # Change as needed
    gmail_username = os.getenv('GMAIL_USERNAME')
    gmail_password = os.getenv('GMAIL_APP_PASSWORD')

    msg = MIMEText(content, 'html')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(gmail_username, gmail_password)
            server.sendmail(from_email, [to_email], msg.as_string())
        print('Email sent successfully.')
    except Exception as e:
        print('Failed to send email:', e)
