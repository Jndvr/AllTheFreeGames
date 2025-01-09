# steam.py

import asyncio
import os
import re
import json
from datetime import datetime, timezone

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
    write_static_games_file
)
from scraper_utils import (
    setup_browser_context,
    get_random_delay,
    natural_scroll,
    rotate_proxy,
    AsyncRequestRateLimiter,
    human_like_mouse_movements
)

warnings.filterwarnings("ignore", category=UserWarning)

# Initialize Firebase
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
    'headless': False,
    'width': 1280,
    'height': 800,
    'screenshots_dir': resolve_path('screenshots'),
    'browser_data_dir': resolve_path('browser_data'),
    'timeout': 30000,
    'max_scrolls': 10,
    'wait_after_cookie': 2000,
    'wait_after_scroll_min': 1500,
    'wait_after_scroll_max': 4000,
    'browser': 'chromium',
}

os.makedirs(CFG['screenshots_dir'], exist_ok=True)
os.makedirs(CFG['browser_data_dir'], exist_ok=True)

async def delete_all_firestore_entries(collection_ref, reason=""):
    """
    Deletes all documents in the specified Firestore collection.
    Optionally logs the reason for deletion.
    """
    try:
        existing_games_snapshot = collection_ref.stream()
        delete_tasks = []
        for doc in existing_games_snapshot:
            print(f"Deleting game: {doc.id} - {doc.to_dict().get('title', 'No Title')}")
            delete_tasks.append(collection_ref.document(doc.id).delete())
        await asyncio.gather(*delete_tasks)
        print("All entries deleted from Firestore.")

        # Optionally, log this event or update a status collection
        status_ref = db.collection('scrape_status').document('steam')
        status_ref.set({
            'last_scrape': datetime.now(timezone.utc),
            'status': 'No games found or failed to load results',
            'reason': reason,
            'games_found': 0
        })

        # Write the static games file (which will now be empty)
        write_static_games_file(db)

    except Exception as delete_err:
        print(f"Error while deleting entries from Firestore: {delete_err}")
        # Send an email notification about the failure
        error_message = f"Steam scraper encountered an issue ({reason}) and attempted to delete all entries, but encountered an error:\n\n{repr(delete_err)}"
        try:
            await asyncio.to_thread(
                send_email,
                'Steam Scraper Deletion Error',
                error_message,
                to="info@weeklygamevault.com"
            )
            print("[Email] Sent successfully to info@weeklygamevault.com.")
        except Exception as email_err:
            print(f"Failed to send error email: {email_err}")

async def scrape_steam():
    """
    Scrapes Steam for free-to-play or free-to-own games and updates Firestore.
    Adjust selectors/logic as necessary to match Steam's page structure.
    """
    print(f"{get_current_datetime()} - Starting Steam scraper...")

    rate_limiter = AsyncRequestRateLimiter()

    # URL to Steam's free games listing
    steam_free_url = "https://store.steampowered.com/search/?maxprice=free&category1=998&supportedlang=english&specials=1&ndl=1"

    async with async_playwright() as p:
        context, page = await setup_browser_context(p, CFG)

        collection_ref = db.collection('steam_free_games')  # Initialize Firestore collection reference

        try:
            # Rate limiting
            await rate_limiter.wait_if_needed()

            print(f'Navigating to Steam free games page: {steam_free_url}')
            await page.goto(steam_free_url, wait_until='domcontentloaded')
            await page.wait_for_timeout(get_random_delay(2000, 4000))

            await human_like_mouse_movements(page, CFG['width'], CFG['height'])
            print("Performed human-like mouse movements.")

            # Accept or close any cookie banner if it exists (Steam typically has a pop-up or a bar at the bottom).
            accept_cookies_selectors = [
                'button.acceptAllButton',      # Example: Steam might have a cookie acceptance button
                '#onetrust-accept-btn-handler' # Another possible selector
            ]
            accepted_cookies = False
            for selector in accept_cookies_selectors:
                if await page.is_visible(selector):
                    await page.wait_for_timeout(get_random_delay(500, 1500))
                    await page.click(selector)
                    print('Accepted cookies.')
                    accepted_cookies = True
                    await page.wait_for_timeout(get_random_delay(1000, 2000))
                    break
            if not accepted_cookies:
                print('No cookie banner found or it was already handled.')

            # Wait for the search results to load
            results_selector = '.search_result_row'
            try:
                await page.wait_for_selector(results_selector, timeout=CFG['timeout'])
                print('Steam free games search results loaded.')
            except PlaywrightTimeoutError:
                print('Steam free games search results did not load.')
                # **New Logic:** Delete Firestore entries due to failure to load search results
                await delete_all_firestore_entries(collection_ref, reason="Failed to load search results")
                return  # Exit the function since no results were loaded

            # Perform scrolling to load more results
            await natural_scroll(
                page,
                CFG['max_scrolls'],
                CFG['wait_after_scroll_min'],
                CFG['wait_after_scroll_max']
            )

            # Extract game elements
            # Usually each game entry has class: .search_result_row
            # Title: .search_name > .title
            # URL: href of .search_result_row
            # Image: .search_capsule img
            games_data = []
            result_rows = page.locator('.search_result_row')
            count = await result_rows.count()

            print(f"Total results found: {count}")
            for i in range(count):
                await page.wait_for_timeout(get_random_delay(300, 800))
                row = result_rows.nth(i)

                # Title
                title = 'Unknown Title'
                try:
                    title_element = row.locator('.search_name .title')
                    title = await title_element.inner_text(timeout=3000)
                    title = title.strip()
                except PlaywrightTimeoutError:
                    pass

                # URL
                url = 'No URL Found'
                try:
                    temp = await row.get_attribute('href')
                    if temp and temp.startswith('http'):
                        url = temp
                except Exception as e:
                    print(f"Attempt to extract game URL failed: {e}")

                # Image
                image_url = 'No Image Found'
                try:
                    image_element = row.locator('.search_capsule img')
                    temp_img = await image_element.get_attribute('src')
                    if temp_img:
                        image_url = temp_img
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

            if not games_data:
                # **New Logic:** Delete Firestore entries because no games were extracted
                print("No games data extracted. Proceeding to delete all entries in Firestore.")
                await delete_all_firestore_entries(collection_ref, reason="No games data extracted")
                return  # Exit the function since there's no data to process

            # **Existing Logic Continues Here:** Update Firestore with new games

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

                # Attempt to parse a unique ID from the URL
                match = re.search(r'/app/\d+/([^/]+)/', game['url'])
                if match:
                    game_id = match.group(1)
                else:
                    # Fallback: sanitize the title
                    game_id = sanitize(game['title'].replace(' ', '_').lower())

                if game_id not in existing_games:
                    print(f"Adding new game: {game['title']}")
                    game['createdAt'] = datetime.now(timezone.utc)
                    collection_ref.document(game_id).set(game)
                    notify_games.append(game)
                else:
                    print(f"Game already exists: {game['title']}")
                    # Remove from existing_games so we know what is *still* present
                    del existing_games[game_id]

            # Remove games no longer free / no longer in the list
            for game_id, game_data in existing_games.items():
                print(f"Removing game no longer free or no longer in listing: {game_data['title']}")
                collection_ref.document(game_id).delete()

            print('Firestore database updated successfully.')
            write_static_games_file(db)

            print("Successfully scraped Steam free games.")

        except Exception as e:
            print('Error during Steam scraping:', e)

            # On error: TAKE SCREENSHOT + SEND EMAIL
            screenshot_path = resolve_path(
                CFG['screenshots_dir'],
                f"steam_error_{sanitize(get_current_datetime())}.png"
            )
            try:
                await page.screenshot(path=screenshot_path, full_page=True)
                print(f"Error screenshot saved to {screenshot_path}")
            except Exception as ss_err:
                print(f"Failed to take error screenshot: {ss_err}")

            error_message = f"Steam scraper encountered an error:\n\n{repr(e)}"
            try:
                await asyncio.to_thread(
                    send_email,
                    'Steam Scraper Error',
                    error_message,
                    to="info@weeklygamevault.com"
                )
                print("[Email] Sent successfully to info@weeklygamevault.com.")
            except Exception as email_err:
                print(f"Failed to send error email: {email_err}")
        finally:
            await context.close()
            print('Browser closed.')


if __name__ == '__main__':
    asyncio.run(scrape_steam())
