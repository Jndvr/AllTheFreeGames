import asyncio
import re
import traceback
import os
import json
from datetime import datetime, timezone

# Load environment
from load_env import load_environment
load_environment()

import firebase_admin
from firebase_admin import credentials, firestore

from scraper_utils import setup_browser_context
from util import (
    resolve_path,
    sanitize,
    send_email
    # Removed write_static_games_file
)

################################################################################
# 1) FIRESTORE INITIALIZATION
################################################################################
# load_dotenv() # optional if you're relying on load_env
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
    # Only initialize if not already initialized
    if not firebase_admin._apps:
        firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print('Failed to initialize Firebase:', e)
    exit(1)

################################################################################
# 2) CONFIG FOR PLAYWRIGHT
################################################################################
CFG = {
    'headless': False,
    'width': 1280,
    'height': 800,
    'screenshots_dir': resolve_path('screenshots', 'gog'),
    'browser_data_dir': resolve_path('browser_data', 'gog'),
    'timeout': 30000,
    'max_pagedowns': 10,
    'wait_after_scroll_min': 500,
    'wait_after_scroll_max': 1500,
    'browser': 'chromium',
}

################################################################################
# 3) SCRAPE FUNCTION
################################################################################
async def scrape_gog_game_data(cfg) -> list[dict]:
    """
    Launches a browser, opens https://www.gog.com/en, 
    checks if there's a current free giveaway (#giveaway).
    Returns a list with a single dict if found, or empty if none.
    """
    from playwright.async_api import async_playwright

    game_data = []
    async with async_playwright() as p:
        context, page = await setup_browser_context(p, cfg)

        try:
            await page.goto("https://www.gog.com/en", wait_until="domcontentloaded")

            # Check giveaway banner
            banner = page.locator("#giveaway")
            banner_count = await banner.count()
            if banner_count == 0:
                print("Currently no free giveaway on GOG.")
            else:
                text = await banner.locator(".giveaway__content-header").inner_text()
                pattern = re.compile(r"Claim (.*) and don't miss the|Success! (.*) was added to")
                match = pattern.search(text)
                if match:
                    if match.group(1):
                        title = match.group(1).strip()
                    else:
                        title = match.group(2).strip()
                else:
                    title = "Unknown Title"

                url = await banner.locator("a").first.get_attribute("href")
                if not url:
                    url = "No URL Found"

                image_url = await banner.locator("img").first.get_attribute("src")
                if not image_url:
                    image_url = "No Image Found"

                print(f"Found a GOG giveaway: {title} - {url}")
                game_data.append({
                    "title": title,
                    "url": url,
                    "imageUrl": image_url
                })

        finally:
            await context.close()

    return game_data

################################################################################
# 4) MAIN LOGIC
################################################################################
async def main():
    try:
        games_data = await scrape_gog_game_data(CFG)

        collection_ref = db.collection('gog_giveaway')
        existing_games_snapshot = collection_ref.stream()
        existing_games = {}
        for doc in existing_games_snapshot:
            existing_games[doc.id] = doc.to_dict()

        if not games_data:
            print("No free GOG giveaway found; removing all existing entries.")
            for game_id, game_data in existing_games.items():
                print(f"Removing: {game_data.get('title', game_id)}")
                collection_ref.document(game_id).delete()

            print('Firestore updated (no current giveaway).')
            return

        # If we found a giveaway
        notify_games = []
        for game in games_data:
            if (
                game['title'] == 'Unknown Title'
                and game['url'] == 'No URL Found'
                and game['imageUrl'] == 'No Image Found'
            ):
                print(f"Skipping invalid game data: {game}")
                continue

            url_match = re.search(r'/en/game/(.+?)(?:\?|$)', game['url'])
            if url_match:
                game_id = sanitize(url_match.group(1))
            else:
                game_id = sanitize(game['title'].replace(' ', '_').lower())

            if game_id not in existing_games:
                print(f"Adding new game: {game['title']}")
                game['createdAt'] = datetime.now(timezone.utc)
                collection_ref.document(game_id).set(game)
                notify_games.append(game)
            else:
                print(f"Game already exists: {game['title']}")
                del existing_games[game_id]

        # Remove no-longer-free
        for game_id, game_data in existing_games.items():
            print(f"Removing game no longer free: {game_data.get('title', game_id)}")
            collection_ref.document(game_id).delete()

        print('Firestore database updated successfully.')
        # Removed write_static_games_file(db)

        print("GOG giveaway update complete.")

    except Exception as e:
        error_trace = traceback.format_exc()
        subject = "GOG Free Giveaway Script Failure"
        content = (
            f"An error occurred while running the GOG scraper:\n\n"
            f"Error: {str(e)}\n\n"
            f"Traceback:\n{error_trace}\n\n"
        )

        print("Script failed. Sending error email to info@weeklygamevault.com...")
        send_email(subject, content, to="info@weeklygamevault.com")
        print("Email sent. Exiting with error.")
        raise


if __name__ == "__main__":
    asyncio.run(main())
