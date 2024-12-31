# gog.py

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

from util import resolve_path, sanitize, get_current_datetime, send_email, html_game_list

# ----- NEW: stealth import
try:
    from playwright_stealth import stealth_async
except ImportError:
    print("playwright-stealth is not installed. Run: pip install playwright-stealth")
    stealth_async = None

# Load environment variables from .env file
load_dotenv()

# ----- Firebase Initialization -----
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

# Configuration
CFG = {
    'headless': True,  # Set to False if you want to see the browser
    'width': 1280,
    'height': 800,
    'screenshots_dir': resolve_path('screenshots', 'gog'),
    'browser_data_dir': resolve_path('browser_data', 'gog'),
    'timeout': 30000,  # 30 seconds
    'max_scrolls': 30,  # Adjust as needed
    'wait_after_action': 1000,  # 1 second
}

# Ensure directories exist
os.makedirs(CFG['screenshots_dir'], exist_ok=True)
os.makedirs(CFG['browser_data_dir'], exist_ok=True)

async def handle_SIGINT(context):
    """
    Handle SIGINT (Ctrl+C) to gracefully close the browser context.
    """
    import signal

    loop = asyncio.get_event_loop()
    stop = loop.create_future()

    def signal_handler():
        if not stop.done():
            stop.set_result(None)

    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    await stop
    await context.close()

async def scrape_gog():
    print(f"{get_current_datetime()} - Started scraping GOG for free games.")

    async with async_playwright() as p:
        context = await p.firefox.launch_persistent_context(
            user_data_dir=CFG['browser_data_dir'],
            headless=CFG['headless'],
            viewport={'width': CFG['width'], 'height': CFG['height']},
            locale='en-US',
            timeout=CFG['timeout'],
        )

        # Apply stealth if available
        if stealth_async and context.pages:
            await stealth_async(context.pages[0])

        # Handle graceful shutdown
        asyncio.create_task(handle_SIGINT(context))

        page = context.pages[0] if context.pages else await context.new_page()

        # Set viewport size
        await page.set_viewport_size({'width': CFG['width'], 'height': CFG['height']})

        notify_games = []

        try:
            # Navigate to GOG's giveaways page
            GOG_FREE_GAMES_URL = 'https://www.gog.com/en/giveaways'
            print(f"Navigating to {GOG_FREE_GAMES_URL}...")
            await page.goto(GOG_FREE_GAMES_URL, wait_until='domcontentloaded')

            # Wait for the giveaways section to load
            giveaways_selector = 'div[class*="GiveawayGrid"]'
            try:
                await page.wait_for_selector(giveaways_selector, timeout=CFG['timeout'])
                print("Giveaways section loaded.")
            except PlaywrightTimeoutError:
                # Take a screenshot for debugging
                screenshot_path = resolve_path('screenshots', 'gog', 'debug_giveaways.png')
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"Giveaways selector not found. Screenshot saved to {screenshot_path}")
                raise

            # Scroll to load all giveaways
            for scroll in range(CFG['max_scrolls']):
                print(f"Scrolling: {scroll + 1}/{CFG['max_scrolls']}")
                await page.evaluate("window.scrollBy(0, window.innerHeight);")
                await asyncio.sleep(CFG['wait_after_action'] / 1000)
                # Optionally, check if more content is loaded
                # Break if no more scrollable content
                # This can be enhanced based on actual page behavior

            # Extract giveaway elements
            giveaway_cards = page.locator('div[class*="GiveawayCard"]')
            giveaway_count = await giveaway_cards.count()
            print(f"Found {giveaway_count} giveaways.")

            games_data = []

            for i in range(giveaway_count):
                card = giveaway_cards.nth(i)

                # Extract title
                try:
                    title = await card.locator('h3').inner_text()
                    title = title.strip()
                except PlaywrightTimeoutError:
                    title = 'Unknown Title'
                    print(f"Failed to extract title for giveaway {i + 1}.")

                # Extract URL
                try:
                    url = await card.locator('a').get_attribute('href')
                    if url and not url.startswith('http'):
                        url = f'https://www.gog.com{url}'
                except PlaywrightTimeoutError:
                    url = 'No URL Found'
                    print(f"Failed to extract URL for giveaway {i + 1}.")

                # Extract Image URL
                try:
                    image_url = await card.locator('img').get_attribute('src')
                    if not image_url:
                        image_url = 'No Image Found'
                        print(f"No image URL found for giveaway {i + 1}.")
                except PlaywrightTimeoutError:
                    image_url = 'No Image Found'
                    print(f"Failed to extract image URL for giveaway {i + 1}.")

                games_data.append({'title': title, 'url': url, 'imageUrl': image_url})

            print(f"Extracted data for {len(games_data)} giveaways.")
            print("Sample games data:", games_data[:5])

            # Update Firestore with new game list
            collection_ref = db.collection('gog_free_games')
            existing_games_snapshot = collection_ref.stream()
            existing_games = {}
            for doc in existing_games_snapshot:
                existing_games[doc.id] = doc.to_dict()

            # Add or update games
            for game in games_data:
                # Skip if invalid
                if (
                    game['title'] == 'Unknown Title'
                    and game['url'] == 'No URL Found'
                    and game['imageUrl'] == 'No Image Found'
                ):
                    print(f"Skipping invalid game data: {game}")
                    continue

                # Use the game ID from the URL for uniqueness
                url_match = re.search(r'/giveaway/(.+?)(?:\?|$)', game['url'])
                game_id = sanitize(url_match.group(1)) if url_match else sanitize(game['title'].replace(' ', '_').lower())

                if game_id not in existing_games:
                    print(f"Adding new game: {game['title']}")
                    # Set createdAt so crawler.py can query new games
                    game['createdAt'] = datetime.now(timezone.utc)
                    collection_ref.document(game_id).set(game)
                    notify_games.append(game)
                else:
                    print(f"Game already exists: {game['title']}")
                    # Remove from existing_games so we don't delete it below
                    del existing_games[game_id]

            # Remove games no longer free
            for leftover_id, leftover_data in existing_games.items():
                print(f"Removing game no longer free: {leftover_data.get('title', leftover_id)}")
                collection_ref.document(leftover_id).delete()

            print('Firestore database updated successfully.')

            # Take a screenshot of the giveaways page
            screenshot_path = resolve_path(
                CFG['screenshots_dir'],
                f"gog_free_games_{sanitize(get_current_datetime())}.png"
            )
            await page.screenshot(path=screenshot_path, full_page=True)
            print(f"Screenshot saved to {screenshot_path}")

            # Send email notification with the list of new games
            if notify_games:
                email_content = html_game_list(notify_games)
                send_email('GOG Free Games Scraper Notification', email_content)

        except Exception as e:
            print('--- Exception:')
            traceback.print_exc()
            send_email('GOG Scraper Error', f'GOG scraper encountered an error: {str(e).splitlines()[0]}')
            exit_code = 1
        else:
            exit_code = 0
        finally:
            # Send notifications for new games
            if notify_games:
                email_content = html_game_list(notify_games)
                send_email(f'GOG Scraper Notification', email_content)

            # Optionally, handle video recordings
            # if page.video():
            #     video_path = await page.video().path()
            #     print('Recorded video:', video_path)

            # Close context
            await context.close()
            print('Browser closed.')

            exit(exit_code)

if __name__ == "__main__":
    asyncio.run(scrape_gog())
