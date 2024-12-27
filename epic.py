import asyncio
import json
import os
from playwright.async_api import async_playwright
from util import resolve_path, sanitize, get_current_datetime
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Firebase Initialization
firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')
if not firebase_credentials:
    raise ValueError("FIREBASE_CREDENTIALS not found in environment variables.")

firebase_credentials_dict = json.loads(firebase_credentials)
cred = credentials.Certificate(firebase_credentials_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# Configuration
CFG = {
    'headless': True,
    'width': 1280,
    'height': 800,
    'browser_data_dir': resolve_path('browser_data'),
    'screenshots_dir': resolve_path('screenshots', 'epic-games'),
    'timeout': 30000,  # 30 seconds
    'claim_url': 'https://store.epicgames.com/en-US/free-games',
}

# Ensure directories exist
os.makedirs(CFG['browser_data_dir'], exist_ok=True)
os.makedirs(CFG['screenshots_dir'], exist_ok=True)

async def scrape_free_games():
    """Scrape free games from Epic Games and update Firebase."""
    async with async_playwright() as p:
        browser = await p.firefox.launch_persistent_context(
            user_data_dir=CFG['browser_data_dir'],
            headless=CFG['headless'],
            viewport={'width': CFG['width'], 'height': CFG['height']},
            locale='en-US',
        )

        page = await browser.new_page()
        await page.goto(CFG['claim_url'], wait_until='domcontentloaded')

        print("Detecting free games...")
        games = await page.locator('a:has(span:text-is("Free Now"))').all()
        game_data = []

        for game in games:
            url = await game.get_attribute('href')
            title = await game.locator('h1').text_content()
            sanitized_title = sanitize(title or "Unknown Game")
            full_url = f"https://store.epicgames.com{url}"

            print(f"Found free game: {title}")
            game_data.append({
                'title': title,
                'url': full_url,
                'date_detected': get_current_datetime(),
            })

        # Update Firebase
        collection = db.collection('epic_free_games')
        existing_docs = {doc.id: doc.to_dict() for doc in collection.stream()}

        for game in game_data:
            doc_id = sanitize(game['title'])
            if doc_id not in existing_docs:
                collection.document(doc_id).set(game)
                print(f"Added new game to Firebase: {game['title']}")
            else:
                print(f"Game already exists: {game['title']}")

        # Take a screenshot of the current page
        screenshot_path = resolve_path(CFG['screenshots_dir'], f"{get_current_datetime()}_free_games.png")
        await page.screenshot(path=screenshot_path)
        print(f"Saved screenshot to {screenshot_path}")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(scrape_free_games())
