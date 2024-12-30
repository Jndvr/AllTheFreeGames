import asyncio
import os
import re
import json
import traceback
from datetime import datetime, timezone

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

import firebase_admin
from firebase_admin import credentials, firestore

from dotenv import load_dotenv

# ----- NEW: stealth import
try:
    from playwright_stealth import stealth_async
except ImportError:
    print("playwright-stealth is not installed. Run: pip install playwright-stealth")
    stealth_async = None

load_dotenv()

def get_current_datetime():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

def sanitize(text):
    return re.sub(r'[^a-zA-Z0-9_-]+', '_', text)

def html_game_list(games):
    """
    Builds a small HTML snippet listing the games (title + link + image).
    """
    lines = []
    for g in games:
        title = g.get('title', 'Unknown')
        url = g.get('url', '#')
        img = g.get('imageUrl', '')
        lines.append(f'<li><a href="{url}">{title}</a> (Image: {img})</li>')
    return '<ul>' + ''.join(lines) + '</ul>'

def send_email(subject, content):
    """
    Stub or example method if you want to send email notifications.
    In production, replace with your actual email-sending logic.
    """
    print(f"[EMAIL NOTIFICATION]\nSubject: {subject}\nContent:\n{content}\n")

# ---- Firebase Initialization (like in crawler.py) ----
firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')
if not firebase_credentials:
    print('FIREBASE_CREDENTIALS not found in environment variables.')
    exit(1)

try:
    firebase_credentials_dict = json.loads(firebase_credentials)
except json.JSONDecodeError as e:
    print('Failed to parse FIREBASE_CREDENTIALS:', e)
    exit(1)

try:
    cred = credentials.Certificate(firebase_credentials_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print('Failed to initialize Firebase:', e)
    exit(1)

CFG = {
    'headless': False,  # Use True if you prefer headless mode
    'width': 1280,
    'height': 800,
    'timeout': 30000,  # 30 seconds
    'screenshots_dir': os.path.join(os.getcwd(), 'screenshots'),
}

# Ensure screenshots directory exists
os.makedirs(CFG['screenshots_dir'], exist_ok=True)

async def scrape_epic_free_game_block():
    """
    Scrapes the first "free game block" from:
      https://store.epicgames.com/en-US/free-games

    1) Title from: 
       #dieselReactWrapper > div > div > div.css-1vplx76 > main > div.css-1dnikhe > div ...
         > div.css-1a6kj04 > div > h6
    2) Image from <img>
       #dieselReactWrapper > div > div > div.css-1vplx76 > main > div.css-1dnikhe > div ...
         > div.css-u421q6 > div > div > div > div > div > img
    3) URL from the same anchor's href

    Then uses Firestore logic to:
      - Check if game is new
      - If new, add
      - If existing, skip
      - Remove leftover docs
      - Optionally email
    """
    print(f"{get_current_datetime()} - Starting Epic Games scraper (single block)")

    # The selectors you provided
    title_sel = "#dieselReactWrapper > div > div > div.css-1vplx76 > main > div.css-1dnikhe > div > div > div > div > div:nth-child(3) > span > div > div > section > div > div:nth-child(1) > div > div > a > div > div.css-1a6kj04 > div > h6"
    image_sel = "#dieselReactWrapper > div > div > div.css-1vplx76 > main > div.css-1dnikhe > div > div > div > div > div:nth-child(3) > span > div > div > section > div > div:nth-child(1) > div > div > a > div > div.css-i9acc6 > div.css-u421q6 > div > div > div > div > div > img"
    link_sel  = "#dieselReactWrapper > div > div > div.css-1vplx76 > main > div.css-1dnikhe > div > div > div > div > div:nth-child(3) > span > div > div > section > div > div:nth-child(1) > div > div > a"

    async with async_playwright() as p:
        browser_data_dir = os.path.join(os.getcwd(), "epic_browser_data")
        os.makedirs(browser_data_dir, exist_ok=True)

        # Launch a persistent context so cookies & session persist between runs
        context = await p.chromium.launch_persistent_context(
            user_data_dir=browser_data_dir,
            headless=CFG['headless'],
            viewport={'width': CFG['width'], 'height': CFG['height']},
            locale='en-US',
            timeout=CFG['timeout'],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # ----- NEW: Apply stealth if available
        if stealth_async:
            await stealth_async(page)

        await page.set_viewport_size({'width': CFG['width'], 'height': CFG['height']})

        new_games = []  # We'll store newly discovered game(s) here

        try:
            # 1. Navigate to epic free games
            print('Navigating to Epic Games free page...')
            await page.goto("https://store.epicgames.com/en-US/free-games", wait_until='domcontentloaded')

            # 2. Optionally set cookies to remove or skip disclaimers
            cookies = [
                {
                    'name': 'OptanonAlertBoxClosed',
                    'value': f"{datetime.now().isoformat()}",
                    'domain': '.epicgames.com',
                    'path': '/'
                },
                {
                    'name': 'HasAcceptedAgeGates',
                    'value': 'USK:9007199254740991,general:18,EPIC SUGGESTED RATING:18',
                    'domain': 'store.epicgames.com',
                    'path': '/'
                }
            ]
            await context.add_cookies(cookies)
            await page.wait_for_timeout(3000)

            # 3. Extract the single block’s data

            # Title
            try:
                title = await page.locator(title_sel).inner_text(timeout=10000)
            except TimeoutError:
                title = "Unknown Title"
                print("Could not find the game title within 10s.")

            # URL
            try:
                link = await page.locator(link_sel).get_attribute('href', timeout=5000)
                if link and not link.startswith('http'):
                    link = "https://store.epicgames.com" + link
            except TimeoutError:
                link = "No link found."

            # Image (from an <img> element's src)
            image_url = "No image found."
            try:
                image_url = await page.locator(image_sel).get_attribute('src')
                if not image_url:
                    image_url = "No image found."
            except TimeoutError:
                pass
            except Exception as e:
                print("Error extracting image URL:", e)

            # Build a dict for the new game
            free_game_data = {
                'title': title,
                'url': link if link else "No URL",
                'imageUrl': image_url,
            }

            print("Scraped data =>", free_game_data)

            # -- NEW: If the data is invalid => skip Firestore and leftover doc removal
            if (
                free_game_data['title'] == "Unknown Title"
                and free_game_data['url'] == "No link found."
                and free_game_data['imageUrl'] == "No image found."
            ):
                print("Data is invalid. Skipping Firestore updates and leftover doc removal.")
            else:
                # 4. Firestore logic (like crawler.py)
                collection_ref = db.collection('epic_free_games')
                existing_snapshot = collection_ref.stream()
                existing_games = {}
                for doc in existing_snapshot:
                    existing_games[doc.id] = doc.to_dict()

                # Use a game_id from the URL. If none, fallback to sanitized title.
                if free_game_data['url'] and free_game_data['url'] != "No URL":
                    game_id = free_game_data['url'].rstrip('/').split('/')[-1]
                else:
                    game_id = sanitize(title.lower().replace(' ', '_'))

                if game_id not in existing_games:
                    # new game
                    print(f"Adding new free game => {title}")
                    free_game_data['createdAt'] = datetime.now(timezone.utc)
                    collection_ref.document(game_id).set(free_game_data)
                    new_games.append(free_game_data)
                else:
                    print(f"Free game already listed => {title}")
                    # remove from existing_games so we don't delete it
                    existing_games.pop(game_id)

                # Remove leftover docs (no longer free)
                for leftover_id, leftover_data in existing_games.items():
                    print(f"Removing leftover doc (no longer free?): {leftover_data.get('title', leftover_id)}")
                    collection_ref.document(leftover_id).delete()

            # 5. Screenshot
            screenshot_path = os.path.join(
                CFG['screenshots_dir'],
                f"epic_free_game_{sanitize(get_current_datetime())}.png"
            )
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"Screenshot saved to {screenshot_path}")

            # 6. Send email if we found a new game
            if new_games:
                email_content = html_game_list(new_games)
                await asyncio.to_thread(send_email, "Epic Free Game - Updated", email_content)

        except Exception as exc:
            print("Error during scraping:", exc)
            traceback.print_exc()
            await asyncio.to_thread(send_email, 'Epic Games Scraper Error', str(exc))

        finally:
            await context.close()
            print('Browser closed.')

if __name__ == "__main__":
    asyncio.run(scrape_epic_free_game_block())
