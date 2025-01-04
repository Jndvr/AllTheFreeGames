import requests
import json
import os
import re
import traceback
from datetime import datetime, timezone

# Load environment depending on ENVIRONMENT
from load_env import load_environment
load_environment()

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

from util import sanitize, send_email, write_static_games_file

# If needed, load_dotenv() again or just rely on load_env above
# load_dotenv()

def get_epic_free_games():
    """
    Fetches the Epic Games free games data and returns a list of dicts with:
      - title
      - url
      - imageUrl
    """
    endpoint = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"
    
    from scraper_utils import get_random_user_agent
    headers = {"User-Agent": get_random_user_agent()}

    resp = requests.get(endpoint, timeout=30)  # you can pass headers=headers
    resp.raise_for_status()
    
    data = resp.json()
    elements = (
        data
        .get("data", {})
        .get("Catalog", {})
        .get("searchStore", {})
        .get("elements", [])
    )
    
    free_games = []
    
    for elem in elements:
        price_info = elem.get("price", {}).get("totalPrice", {})
        discount_price = price_info.get("discountPrice", None)
        
        if discount_price == 0:
            title = elem.get("title", "Unknown Title")
            product_slug = elem.get("productSlug")
            url_slug = elem.get("urlSlug")

            if product_slug:
                store_url = f"https://store.epicgames.com/p/{product_slug}"
            elif url_slug:
                store_url = f"https://store.epicgames.com/p/{url_slug}"
            else:
                store_url = "No URL Found"

            key_images = elem.get("keyImages", [])
            if key_images:
                image_url = key_images[0].get("url", "No Image Found")
            else:
                image_url = "No Image Found"
            
            free_games.append({
                "title": title,
                "url": store_url,
                "imageUrl": image_url
            })
    
    return free_games


def update_firestore_with_free_games(games_data):
    """
    Updates Firestore with the provided free games data.
    Adds new games, updates if needed, and removes old ones.
    """
    firebase_credentials = os.getenv('FIREBASE_CREDENTIALS')
    if not firebase_credentials:
        print('FIREBASE_CREDENTIALS not found in environment variables.')
        return

    try:
        firebase_credentials_dict = json.loads(firebase_credentials)
    except json.JSONDecodeError as e:
        print('Failed to parse FIREBASE_CREDENTIALS:', e)
        return

    try:
        cred = credentials.Certificate(firebase_credentials_dict)
        # If already initialized, you might see an error, so check:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print('Failed to initialize Firebase:', e)
        return

    collection_ref = db.collection('epic_free_games')
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

    # Remove stale
    for game_id, game_data in existing_games.items():
        print(f"Removing game no longer free: {game_data['title']}")
        collection_ref.document(game_id).delete()

    print('Firestore database updated successfully.')
    write_static_games_file(db)


def main():
    """
    Main entry point: fetch free games, update Firestore.
    Only email on error. No success email or screenshot.
    """
    try:
        free_games = get_epic_free_games()
        print("Free games found:")
        for fg in free_games:
            print(f" - {fg['title']} => {fg['url']}")
        
        update_firestore_with_free_games(free_games)
        print("Epic free games updated successfully.")

    except Exception as e:
        # On error => send email
        error_trace = traceback.format_exc()
        subject = "Epic Free Games Script Failure"
        content = (
            f"An error occurred while running the script:\n\n"
            f"Error: {str(e)}\n\n"
            f"Traceback:\n{error_trace}\n\n"
        )

        print("Script failed. Sending error email to info@weeklygamevault.com...")
        send_email(subject, content, to="info@weeklygamevault.com")
        print("Email sent. Exiting with error.")
        raise


if __name__ == "__main__":
    main()
