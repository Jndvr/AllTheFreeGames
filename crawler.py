# crawler.py

import asyncio
import os
import re
import json
from datetime import datetime, timezone

# Load environment depending on ENVIRONMENT
from load_env import load_environment
load_environment()

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import firebase_admin
from firebase_admin import credentials, firestore
import warnings

from util import (
    resolve_path,
    sanitize,
    get_current_datetime,
    send_email,
    html_game_list,
    db
)
from scraper_utils import (
    setup_browser_context,
    get_random_delay,
    natural_scroll,
    rotate_proxy,
    AsyncRequestRateLimiter,
    human_like_mouse_movements
)

# Suppress UserWarnings about Firestore filters
warnings.filterwarnings("ignore", category=UserWarning)

# Initialize environment variables
# We already called load_environment() which handles .env
# so no separate load_dotenv() needed here.

# Firebase initialization
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

# Configuration
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

# Create necessary directories
os.makedirs(CFG['screenshots_dir'], exist_ok=True)
os.makedirs(CFG['browser_data_dir'], exist_ok=True)

async def scrape_prime_gaming():
    print(f"{get_current_datetime()} - Starting Prime Gaming scraper...")

    rate_limiter = AsyncRequestRateLimiter()
    CFG['proxy'] = rotate_proxy()

    async with async_playwright() as p:
        context, page = await setup_browser_context(p, CFG)

        try:
            # Rate limiting
            await rate_limiter.wait_if_needed()

            print('Navigating to Prime Gaming homepage...')
            await page.goto('https://gaming.amazon.com/home', wait_until='domcontentloaded')
            await page.wait_for_timeout(get_random_delay(2000, 4000))

            await human_like_mouse_movements(page, CFG['width'], CFG['height'])
            print("Performed human-like mouse movements.")

            # Handle cookie banner
            accept_cookies_selector = '[aria-label="Cookies usage disclaimer banner"] button:has-text("Accept Cookies")'
            if await page.is_visible(accept_cookies_selector):
                await page.wait_for_timeout(get_random_delay(500, 1500))
                await page.click(accept_cookies_selector)
                print('Accepted cookies.')
                await page.wait_for_timeout(get_random_delay(1000, 2000))
            else:
                print('No cookie banner found.')

            # Click Free Games
            free_games_button_selector = 'button[data-type="Game"]'
            try:
                await page.wait_for_selector(free_games_button_selector, timeout=CFG['timeout'])
                await page.wait_for_timeout(get_random_delay(500, 1500))
                await page.click(free_games_button_selector)
                print('Clicked "Free Games" button.')
            except TimeoutError:
                print('Free Games button not found.')
                return

            # Wait for games list
            games_list_selector = 'div[data-a-target="offer-list-FGWP_FULL"]'
            try:
                await page.wait_for_selector(games_list_selector, timeout=CFG['timeout'])
                print('Free games list loaded.')
            except TimeoutError:
                print('Free games list not loaded.')
                return

            # Perform scrolling
            await natural_scroll(
                page,
                CFG['max_scrolls'],
                CFG['wait_after_scroll_min'],
                CFG['wait_after_scroll_max']
            )

            # Extract game elements
            games_list = page.locator('div[data-a-target="offer-list-FGWP_FULL"] a[data-a-target="learn-more-card"]')
            game_count = await games_list.count()
            print(f"Total games found: {game_count}")

            games_data = []
            for i in range(game_count):
                await page.wait_for_timeout(get_random_delay(300, 800))
                game = games_list.nth(i)

                # Title
                title = 'Unknown Title'
                for _ in range(3):
                    try:
                        title_element = game.locator('.item-card-details__body__primary h3')
                        title = await title_element.inner_text(timeout=5000)
                        title = title.strip()
                        break
                    except TimeoutError:
                        await page.wait_for_timeout(get_random_delay(500, 1000))

                # URL
                url = 'No URL Found'
                for _ in range(3):
                    try:
                        temp = await game.get_attribute('href')
                        if temp:
                            if not temp.startswith('http'):
                                temp = f'https://gaming.amazon.com{temp}'
                            url = temp
                            break
                        await page.wait_for_timeout(get_random_delay(500, 1000))
                    except Exception as e:
                        print(f"Attempt to extract URL failed: {e}")

                # Image
                image_url = 'No Image Found'
                for _ in range(3):
                    try:
                        image_element = game.locator('img.tw-image')
                        temp_img = await image_element.get_attribute('src')
                        if temp_img:
                            image_url = temp_img
                            break
                        await page.wait_for_timeout(get_random_delay(500, 1000))
                    except Exception as e:
                        print(f"Attempt to extract image URL failed: {e}")

                games_data.append({
                    'title': title or 'Unknown Title',
                    'url': url,
                    'imageUrl': image_url
                })

            print(f"Extracted data for {len(games_data)} games.")
            if games_data:
                print('Sample games data:', games_data[:5])

            # Update Firestore
            collection_ref = db.collection('prime_free_games')
            existing_games_snapshot = collection_ref.stream()
            existing_games = {}
            for doc in existing_games_snapshot:
                existing_games[doc.id] = doc.to_dict()

            notify_games = []
            for game in games_data:
                if (
                    game['title'] == 'Unknown Title'
                    and game['url'] == 'No URL Found'
                    and game['imageUrl'] == 'No Image Found'
                ):
                    print(f"Skipping invalid game data: {game}")
                    continue

                url_match = re.search(r'/games/(.+?)(?:\?|$)', game['url'])
                game_id = sanitize(url_match.group(1)) if url_match else sanitize(game['title'].replace(' ', '_').lower())

                if game_id not in existing_games:
                    print(f"Adding new game: {game['title']}")
                    game['createdAt'] = datetime.now(timezone.utc)
                    collection_ref.document(game_id).set(game)
                    notify_games.append(game)
                else:
                    print(f"Game already exists: {game['title']}")
                    del existing_games[game_id]

            # Remove games no longer free
            for game_id, game_data in existing_games.items():
                print(f"Removing game no longer free: {game_data['title']}")
                collection_ref.document(game_id).delete()

            print('Firestore database updated successfully.')

            print("Successfully scraped Prime Gaming.")

        except Exception as e:
            print('Error during scraping:', e)

            # On error: TAKE SCREENSHOT + SEND EMAIL
            screenshot_path = resolve_path(
                CFG['screenshots_dir'],
                f"prime_gaming_error_{sanitize(get_current_datetime())}.png"
            )
            # Attempt screenshot
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"Error screenshot saved to {screenshot_path}")
            except Exception as ss_err:
                print(f"Failed to take error screenshot: {ss_err}")

            error_message = f"Prime Gaming scraper encountered an error:\n\n{repr(e)}"
            await asyncio.to_thread(
                send_email, 
                'Prime Gaming Scraper Error',
                error_message,
                to="info@weeklygamevault.com"
            )

        finally:
            await context.close()
            print('Browser closed.')


if __name__ == '__main__':
    asyncio.run(scrape_prime_gaming())
