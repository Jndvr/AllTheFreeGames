import asyncio
import os
import re
import json
import traceback
import random
from datetime import datetime, timezone
import warnings

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

import firebase_admin
from firebase_admin import credentials, firestore

from dotenv import load_dotenv

try:
    from playwright_stealth import stealth_async
except ImportError:
    print("playwright-stealth is not installed. Run: pip install playwright-stealth")
    stealth_async = None

from util import resolve_path, sanitize, get_current_datetime, send_email, html_game_list, write_static_games_file
from scraper_utils import (
    setup_browser_context,
    get_random_delay,
    rotate_proxy,
    AsyncRequestRateLimiter,
    human_like_mouse_movements
)

# Suppress UserWarnings about Firestore filters
warnings.filterwarnings("ignore", category=UserWarning)

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

os.makedirs(CFG['screenshots_dir'], exist_ok=True)
os.makedirs(CFG['browser_data_dir'], exist_ok=True)

rate_limiter = AsyncRequestRateLimiter(requests_per_minute=30)

async def pagedown_scroll(page, max_pagedowns: int = 10, min_delay: int = 500, max_delay: int = 1500):
    for pagedown in range(max_pagedowns):
        print(f"Pagedown {pagedown + 1}/{max_pagedowns}")
        await page.keyboard.press('PageDown')
        await page.wait_for_timeout(random.randint(min_delay, max_delay))

async def scrape_gog():
    print(f"{get_current_datetime()} - Starting GOG scraper...")

    notify_games = []

    try:
        CFG['proxy'] = rotate_proxy()

        async with async_playwright() as p:
            context, page = await setup_browser_context(p, CFG)

            if stealth_async and context.pages:
                await stealth_async(context.pages[0])

            try:
                await rate_limiter.wait_if_needed()

                GOG_FREE_GAMES_URL = 'https://www.gog.com/en/partner/free_games'
                print(f"Navigating to {GOG_FREE_GAMES_URL}...")
                await page.goto(GOG_FREE_GAMES_URL, wait_until='domcontentloaded')
                await page.wait_for_timeout(get_random_delay(2000, 4000))

                await page.screenshot(path=resolve_path('screenshots', 'gog', 'after_navigation.png'), full_page=True)
                print("Screenshot taken after navigation.")

                await human_like_mouse_movements(page, CFG['width'], CFG['height'])
                print("Performed human-like mouse movements.")

                accept_cookies_selector = 'button[data-testid="accept-cookies-button"]'
                if await page.is_visible(accept_cookies_selector):
                    await page.wait_for_timeout(get_random_delay(500, 1500))
                    await page.click(accept_cookies_selector)
                    print('Accepted cookies.')
                    await page.wait_for_timeout(get_random_delay(1000, 2000))
                else:
                    print('No cookie banner found.')

                await page.screenshot(path=resolve_path('screenshots', 'gog', 'after_cookies.png'), full_page=True)
                print("Screenshot taken after handling cookies.")

                print("Starting pagedown scroll to load all free games...")
                await pagedown_scroll(
                    page,
                    max_pagedowns=CFG['max_pagedowns'],
                    min_delay=CFG['wait_after_scroll_min'],
                    max_delay=CFG['wait_after_scroll_max']
                )

                await page.screenshot(path=resolve_path('screenshots', 'gog', 'after_scrolling.png'), full_page=True)
                print("Screenshot taken after scrolling.")

                giveaways_selector = '.partners__section--left > ul > div'
                giveaways = page.locator(giveaways_selector)
                giveaway_count = await giveaways.count()
                print(f"Found {giveaway_count} giveaways with selector '{giveaways_selector}'.")

                if giveaway_count == 0:
                    page_content_path = resolve_path('screenshots', 'gog', 'gog_page_content.html')
                    with open(page_content_path, 'w', encoding='utf-8') as f:
                        f.write(await page.content())
                    print(f"No giveaways found. Page content saved to {page_content_path}")
                    return

                games_data = []

                title_selector = '.product-title__text'
                image_selector = '.product-row__img'
                link_selector = '.product-row__link'

                for i in range(giveaway_count):
                    await page.wait_for_timeout(get_random_delay(300, 800))

                    giveaway = giveaways.nth(i)

                    title = 'Unknown Title'
                    try:
                        title_element = giveaway.locator(title_selector).first
                        title = await title_element.inner_text(timeout=5000)
                        title = title.strip()
                        print(f"Extracted Title: {title}")
                    except PlaywrightTimeoutError:
                        print(f"Failed to extract title for giveaway {i + 1}.")

                    url = 'No URL Found'
                    try:
                        url = await giveaway.locator(link_selector).get_attribute('href', timeout=5000)
                        if url and not url.startswith('http'):
                            url = f'https://www.gog.com{url}'
                        print(f"Extracted URL: {url}")
                    except PlaywrightTimeoutError:
                        print(f"Failed to extract URL for giveaway {i + 1}.")

                    image_url = 'No Image Found'
                    try:
                        image_element = giveaway.locator(image_selector).first
                        srcset = await image_element.get_attribute('srcset', timeout=5000)
                        if srcset:
                            image_url = 'https:' + srcset.split(',')[0].strip().split(' ')[0]
                        print(f"Extracted Image URL: {image_url}")
                    except PlaywrightTimeoutError:
                        print(f"Failed to extract image URL for giveaway {i + 1}.")

                    games_data.append({'title': title, 'url': url, 'imageUrl': image_url})

                print(f"Extracted data for {len(games_data)} giveaways.")
                print("Sample games data:", games_data[:5])

                collection_ref = db.collection('gog_free_games')
                existing_games_snapshot = collection_ref.stream()
                existing_games = {}
                for doc in existing_games_snapshot:
                    existing_games[doc.id] = doc.to_dict()

                for game in games_data:
                    if (
                        game['title'] == 'Unknown Title'
                        and game['url'] == 'No URL Found'
                        and game['imageUrl'] == 'No Image Found'
                    ):
                        print(f"Skipping invalid game data: {game}")
                        continue

                    url_match = re.search(r'/en/game/(.+?)(?:\?|$)', game['url'])
                    game_id = sanitize(url_match.group(1)) if url_match else sanitize(game['title'].replace(' ', '_').lower())

                    if game_id not in existing_games:
                        print(f"Adding new game: {game['title']}")
                        game['createdAt'] = datetime.now(timezone.utc)
                        collection_ref.document(game_id).set(game)
                        notify_games.append(game)
                    else:
                        print(f"Game already exists: {game['title']}")
                        del existing_games[game_id]

                for game_id, game_data in existing_games.items():
                    print(f"Removing game no longer free: {game_data.get('title', game_id)}")
                    collection_ref.document(game_id).delete()

                print('Firestore database updated successfully.')
                write_static_games_file(db)

                await page.wait_for_timeout(get_random_delay(1000, 2000))
                final_screenshot_path = resolve_path(
                    CFG['screenshots_dir'],
                    f"gog_free_games_{sanitize(get_current_datetime())}.png"
                )
                await page.screenshot(path=final_screenshot_path, full_page=True)
                print(f"Final screenshot saved to {final_screenshot_path}")

                if notify_games:
                    email_content = html_game_list(notify_games)
                    await asyncio.to_thread(send_email, 'GOG Free Games Scraper Notification', email_content)

            except Exception as e:
                print('--- Exception:')
                traceback.print_exc()
                error_message = f"GOG scraper encountered an error: {str(e).splitlines()[0]}"
                await asyncio.to_thread(send_email, 'GOG Scraper Error', error_message)

            finally:
                await context.close()
                print('Browser closed.')
                
    except Exception as e:
        print('Failed to initialize browser:', e)
        error_message = f"GOG scraper failed to initialize: {str(e).splitlines()[0]}"
        await asyncio.to_thread(send_email, 'GOG Scraper Initialization Error', error_message)

if __name__ == "__main__":
    asyncio.run(scrape_gog())