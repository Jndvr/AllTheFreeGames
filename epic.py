# epic.py

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

# Import utilities from util.py and scraper_utils.py
from util import resolve_path, sanitize, get_current_datetime, send_email, html_game_list
from scraper_utils import (
    setup_browser_context,
    get_random_delay,
    rotate_proxy,
    RequestRateLimiter,
    human_like_mouse_movements
)

load_dotenv()

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
    'headless': False, 
    'width': 1280,
    'height': 800,
    'screenshots_dir': resolve_path('screenshots'),
    'browser_data_dir': resolve_path('browser_data'),
    'timeout': 30000,
    'max_scrolls': 50, 
    'wait_after_cookie': 2000,
    'wait_after_scroll_min': 1500,
    'wait_after_scroll_max': 4000,
    'browser': 'chromium', 
}

# Ensure directories exist
os.makedirs(CFG['screenshots_dir'], exist_ok=True)
os.makedirs(CFG['browser_data_dir'], exist_ok=True)

# Initialize Rate Limiter (optional, adjust as needed)
rate_limiter = RequestRateLimiter(requests_per_minute=30)

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
        # Setup browser context using scraper_utils
        context, page = await setup_browser_context(p, CFG)
        new_games = []  # We'll store newly discovered game(s) here

        try:
            # Rate limiting
            await rate_limiter.wait_if_needed()

            # Optionally perform human-like mouse movements
            await human_like_mouse_movements(page, CFG['width'], CFG['height'])

            # Navigate to Epic Games free games page
            print('Navigating to Epic Games free games page...')
            await page.goto("https://store.epicgames.com/en-US/free-games", wait_until='domcontentloaded')

            # Optionally set cookies to remove or skip disclaimers
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
            await page.wait_for_timeout(get_random_delay(2000, 4000))  # Wait between 2 to 4 seconds

            # Extract the single block’s data

            # Title
            try:
                title = await page.locator(title_sel).inner_text(timeout=10000)
                title = title.strip()
                print(f"Extracted Title: {title}")
            except PlaywrightTimeoutError:
                title = "Unknown Title"
                print("Could not find the game title within 10s.")

            # URL
            try:
                link = await page.locator(link_sel).get_attribute('href', timeout=5000)
                if link and not link.startswith('http'):
                    link = "https://store.epicgames.com" + link
                print(f"Extracted URL: {link}")
            except PlaywrightTimeoutError:
                link = "No URL Found"
                print("Could not find the game URL within 5s.")

            # Image (from an <img> element's src)
            try:
                image_url = await page.locator(image_sel).get_attribute('src', timeout=5000)
                if image_url:
                    print(f"Extracted Image URL: {image_url}")
                else:
                    image_url = "No Image Found"
                    print("Image URL not found.")
            except PlaywrightTimeoutError:
                image_url = "No Image Found"
                print("Could not find the image URL within 5s.")
            except Exception as e:
                image_url = "No Image Found"
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
                and free_game_data['url'] == "No URL Found"
                and free_game_data['imageUrl'] == "No Image Found"
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
                if free_game_data['url'] and free_game_data['url'] != "No URL Found":
                    game_id = free_game_data['url'].rstrip('/').split('/')[-1]
                else:
                    game_id = sanitize(title.lower().replace(' ', '_'))

                if game_id not in existing_games:
                    # New game
                    print(f"Adding new free game => {title}")
                    free_game_data['createdAt'] = datetime.now(timezone.utc)
                    collection_ref.document(game_id).set(free_game_data)
                    new_games.append(free_game_data)
                else:
                    print(f"Free game already listed => {title}")
                    # Remove from existing_games so we don't delete it
                    existing_games.pop(game_id)

                # Remove leftover docs (no longer free)
                for leftover_id, leftover_data in existing_games.items():
                    print(f"Removing leftover doc (no longer free?): {leftover_data.get('title', leftover_id)}")
                    collection_ref.document(leftover_id).delete()

            # 5. Screenshot
            screenshot_path = resolve_path(
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
