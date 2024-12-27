# crawler.py

import asyncio
import os
import re
import json
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import firebase_admin
from firebase_admin import credentials, firestore
from util import resolve_path, sanitize, get_current_datetime, send_email, html_game_list
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize Firebase using credentials from environment variable
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
    'headless': True,
    'width': 1280,
    'height': 800,
    'screenshots_dir': resolve_path('screenshots'),
    'browser_data_dir': resolve_path('browser_data'),
    'timeout': 30000,  # 30 seconds
    'max_scrolls': 30,  # Adjusted to match JS script
    'wait_after_cookie': 2000,  # 2 seconds
    'wait_after_scroll': 3000,  # 3 seconds
    'record_video': False,  # Optional: set to True to record video
}

# Ensure screenshots directory exists
os.makedirs(CFG['screenshots_dir'], exist_ok=True)

async def scroll_until_stable(page, max_scrolls, wait_after_scroll):
    previous_count = 0
    for scroll in range(max_scrolls):
        current_count = await page.evaluate("""
            () => {
                const games = document.querySelectorAll('div[data-a-target="offer-list-FGWP_FULL"] a[data-a-target="learn-more-card"]');
                return games.length;
            }
        """)
        print(f"Scroll {scroll + 1}: Found {current_count} games")

        if current_count == previous_count:
            print('No new games loaded. Stopping scrolling.')
            break

        previous_count = current_count

        # Press PageDown to scroll
        await page.keyboard.press('PageDown')
        print('Pressed PageDown to scroll.')

        # Wait for network to be idle and additional timeout
        await page.wait_for_load_state('networkidle')
        await asyncio.sleep(wait_after_scroll / 1000)  # Convert ms to seconds

    if current_count == previous_count:
        print(f"Total games found after scrolling: {current_count}")
    else:
        print(f"Reached maximum scroll limit ({max_scrolls}). Some games might not have loaded.")

    return current_count

async def scrape_prime_gaming():
    print(f"{get_current_datetime()} - Starting Prime Gaming scraper...")

    async with async_playwright() as p:
        browser = await p.firefox.launch_persistent_context(
            user_data_dir=CFG['browser_data_dir'],
            headless=CFG['headless'],
            viewport={'width': CFG['width'], 'height': CFG['height']},
            locale='en-US',
            timeout=CFG['timeout']
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.set_viewport_size({'width': CFG['width'], 'height': CFG['height']})

        notify_games = []

        try:
            print('Navigating to Prime Gaming homepage...')
            await page.goto('https://gaming.amazon.com/home', wait_until='domcontentloaded')

            # Accept cookies if the banner is present
            accept_cookies_selector = '[aria-label="Cookies usage disclaimer banner"] button:has-text("Accept Cookies")'
            if await page.is_visible(accept_cookies_selector):
                await page.click(accept_cookies_selector)
                print('Accepted cookies.')
                await asyncio.sleep(CFG['wait_after_cookie'] / 1000)  # Wait after accepting cookies
            else:
                print('No cookie banner found.')

            # Click on "Free Games" button to view offers
            free_games_button_selector = 'button[data-type="Game"]'
            try:
                await page.wait_for_selector(free_games_button_selector, timeout=CFG['timeout'])
                await page.click(free_games_button_selector)
                print('Clicked "Free Games" button.')
            except PlaywrightTimeoutError:
                print('Free Games button not found.')
                return

            # Wait for the games list to load
            games_list_selector = 'div[data-a-target="offer-list-FGWP_FULL"]'
            try:
                await page.wait_for_selector(games_list_selector, timeout=CFG['timeout'])
                print('Free games list loaded.')
            except PlaywrightTimeoutError:
                print('Free games list not loaded.')
                return

            # Perform scrolling to load all games
            total_games = await scroll_until_stable(page, CFG['max_scrolls'], CFG['wait_after_scroll'])

            # Extract game elements
            games_list = page.locator('div[data-a-target="offer-list-FGWP_FULL"] a[data-a-target="learn-more-card"]')
            game_count = await games_list.count()
            print(f"Total games found: {game_count}")

            games_data = []

            for i in range(game_count):
                game = games_list.nth(i)

                # Extract title
                title_element = game.locator('.item-card-details__body__primary h3')
                try:
                    title = await title_element.inner_text(timeout=5000)
                    title = title.strip()
                except PlaywrightTimeoutError:
                    title = 'Unknown Title'
                    print(f"Failed to extract title for game at index {i}.")

                # Extract URL
                try:
                    url = await game.get_attribute('href')
                    if url:
                        if not url.startswith('http'):
                            url = f'https://gaming.amazon.com{url}'
                    else:
                        url = 'No URL Found'
                        print(f"No URL found for game at index {i}.")
                except Exception as e:
                    url = 'No URL Found'
                    print(f"Failed to extract URL for game at index {i}: {e}")

                # Extract Image URL
                image_element = game.locator('img.tw-image')
                try:
                    image_url = await image_element.get_attribute('src')
                    if not image_url:
                        image_url = 'No Image Found'
                        print(f"No image URL found for game at index {i}.")
                except Exception as e:
                    image_url = 'No Image Found'
                    print(f"Failed to extract image URL for game at index {i}: {e}")

                # Log and capture screenshot if title extraction failed
                if title == 'Unknown Title':
                    game_html = await game.inner_html()
                    print(f"Game at index {i} has an unknown title. Game HTML: {game_html}")

                    # Capture a screenshot of the problematic game element
                    screenshot_path = resolve_path(
                        CFG['screenshots_dir'],
                        f"unknown_title_{sanitize(get_current_datetime())}_game_{i}.png"
                    )
                    await game.screenshot(path=screenshot_path, full_page=True)
                    print(f"Screenshot saved for game at index {i}: {screenshot_path}")

                games_data.append({'title': title, 'url': url, 'imageUrl': image_url})

            print(f"Extracted data for {len(games_data)} games.")
            print('Sample games data:', games_data[:5])

            # Update Firestore with new game list
            collection_ref = db.collection('prime_free_games')  # Updated collection name
            existing_games_snapshot = collection_ref.stream()

            existing_games = {}
            for doc in existing_games_snapshot:
                existing_games[doc.id] = doc.to_dict()

            # Add or update games
            for game in games_data:
                # Use the game ID from the URL for uniqueness
                url_match = re.search(r'/games/(.+?)(?:\?|$)', game['url'])
                game_id = sanitize(url_match.group(1)) if url_match else sanitize(game['title'].replace(' ', '_').lower())

                if game_id not in existing_games:
                    print(f"Adding new game: {game['title']}")
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

            # Optionally, take a screenshot of the games page
            final_screenshot_path = resolve_path(
                CFG['screenshots_dir'],
                f"free_games_{sanitize(get_current_datetime())}.png"
            )
            await page.screenshot(path=final_screenshot_path, full_page=True)
            print(f"Screenshot saved to {final_screenshot_path}")

            # Optionally, send a notification email with the list of new games including images
            if notify_games:
                email_content = html_game_list(notify_games)
                await asyncio.to_thread(send_email, 'Prime Gaming Scraper Notification', email_content)

        except Exception as e:
            print('Error during scraping:', e)
            error_message = f"Prime Gaming scraper encountered an error: {str(e)}"
            await asyncio.to_thread(send_email, 'Prime Gaming Scraper Error', error_message)

        finally:
            await browser.close()
            print('Browser closed.')

if __name__ == '__main__':
    asyncio.run(scrape_prime_gaming())
