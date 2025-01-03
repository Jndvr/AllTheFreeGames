import asyncio
import re
import traceback
import os
import json
from datetime import datetime, timezone

from dotenv import load_dotenv

import firebase_admin
from firebase_admin import credentials, firestore

from scraper_utils import setup_browser_context
from util import (
    resolve_path,
    sanitize,
    send_email,
    write_static_games_file
)

################################################################################
# 1) FIRESTORE INITIALIZATION
################################################################################
load_dotenv()

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

################################################################################
# 2) CONFIG FOR PLAYWRIGHT (mirroring JS cfg)
################################################################################
CFG = {
    'headless': False,  # Set True to hide the browser
    'width': 1280,
    'height': 800,
    'screenshots_dir': resolve_path('screenshots', 'gog'),
    'browser_data_dir': resolve_path('browser_data', 'gog'),
    'timeout': 30000,
    'max_pagedowns': 10,
    'wait_after_scroll_min': 500,
    'wait_after_scroll_max': 1500,
    'browser': 'chromium',  # or 'firefox' / 'webkit'
}


################################################################################
# 3) SCRAPE FUNCTION
################################################################################
async def scrape_gog_game_data(cfg) -> list[dict]:
    """
    Launches a browser with anti-detection measures (via setup_browser_context),
    opens https://www.gog.com/en, and checks if there's a current free giveaway.
    Returns a list containing one game dict if found, or an empty list if none.
    Each dict includes title, url, and imageUrl.
    """
    from playwright.async_api import async_playwright

    game_data = []

    async with async_playwright() as p:
        # 1) Launch context/page with anti-detection
        context, page = await setup_browser_context(p, cfg)

        try:
            # 2) Go to the main GOG page
            await page.goto("https://www.gog.com/en", wait_until="domcontentloaded")

            # 3) Check if there's a '#giveaway' banner
            banner = page.locator("#giveaway")
            banner_count = await banner.count()
            if banner_count == 0:
                print("Currently no free giveaway on GOG.")
            else:
                # Extract the text to find the title
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

                # Extract store URL from the banner link
                url = await banner.locator("a").first.get_attribute("href")
                if not url:
                    url = "No URL Found"

                # Extract an image from the banner (if present)
                image_url = await banner.locator("img").first.get_attribute("src")
                if not image_url:
                    image_url = "No Image Found"

                # Return the found game data as a single-entry list
                print(f"Found a GOG giveaway: {title} - {url}")
                game_data.append({
                    "title": title,
                    "url": url,
                    "imageUrl": image_url
                })

        except Exception as e:
            # If something in scraping fails, re-raise so main() can handle it
            raise e
        finally:
            # Always close context after finishing
            await context.close()

    return game_data


################################################################################
# 4) MAIN LOGIC: SCRAPE + FIRESTORE + EMAIL ON FAILURE
################################################################################
async def main():
    notify_games = []

    try:
        # 1) Scrape GOG for the current free game
        games_data = await scrape_gog_game_data(CFG)

        # 2) Firestore collection
        collection_ref = db.collection('gog_giveaway')
        existing_games_snapshot = collection_ref.stream()
        existing_games = {}
        for doc in existing_games_snapshot:
            existing_games[doc.id] = doc.to_dict()

        # 3) If no free game is found, remove all existing entries
        if not games_data:
            print("No free GOG giveaway found; removing all existing entries in Firestore.")
            for game_id, game_data in existing_games.items():
                print(f"Removing: {game_data.get('title', game_id)}")
                collection_ref.document(game_id).delete()
            print('Firestore database updated successfully (no current giveaway).')
            return

        # 4) Otherwise, process the found game(s)
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
                # fallback
                game_id = sanitize(game['title'].replace(' ', '_').lower())

            if game_id not in existing_games:
                print(f"Adding new game: {game['title']}")
                game['createdAt'] = datetime.now(timezone.utc)
                collection_ref.document(game_id).set(game)
                notify_games.append(game)
            else:
                print(f"Game already exists: {game['title']}")
                del existing_games[game_id]

        # 5) Remove games no longer free
        for game_id, game_data in existing_games.items():
            print(f"Removing game no longer free: {game_data.get('title', game_id)}")
            collection_ref.document(game_id).delete()

        print('Firestore database updated successfully.')
        write_static_games_file(db)

    except Exception as e:
        # If anything fails, send an email to info@weeklygamevault.com
        error_trace = traceback.format_exc()
        subject = "GOG Free Giveaway Script Failure"
        content = (
            f"An error occurred while running the GOG scraper:\n\n"
            f"Error: {str(e)}\n\n"
            f"Traceback:\n{error_trace}\n\n"
        )

        print("Script failed. Sending error email...")
        send_email(subject, content)
        print("Email sent. Exiting with error.")
        raise  # Re-raise so the script returns a non-zero exit code


if __name__ == "__main__":
    asyncio.run(main())
