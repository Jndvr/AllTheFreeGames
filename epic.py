import requests
import json
import os
import re
import traceback
from datetime import datetime, timezone
from dotenv import load_dotenv

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# Utilities (assuming these functions exist in util.py)
# - sanitize
# - send_email
# - etc.
from util import sanitize, send_email, write_static_games_file

load_dotenv()  # Load environment variables from .env

def get_epic_free_games():
    """
    Fetches the Epic Games free games data and returns a list of dicts with:
      - title
      - url (a link to the Epic Store product page)
      - imageUrl
    """
    endpoint = "https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions"
    
    from scraper_utils import get_random_user_agent

    headers = { "User-Agent": get_random_user_agent() }
    
    # resp = requests.get(endpoint, headers=headers, timeout=30)
    resp = requests.get(endpoint, timeout=30)
    resp.raise_for_status()
    
    data = resp.json()
    
    # Navigate through the JSON to get the 'elements'
    elements = (
        data
        .get("data", {})
        .get("Catalog", {})
        .get("searchStore", {})
        .get("elements", [])
    )
    
    free_games = []
    
    for elem in elements:
        # Check discountPrice == 0
        price_info = elem.get("price", {}).get("totalPrice", {})
        discount_price = price_info.get("discountPrice", None)
        
        if discount_price == 0:
            # Extract the title
            title = elem.get("title", "Unknown Title")
            
            # Extract store link
            product_slug = elem.get("productSlug")
            url_slug = elem.get("urlSlug")
            
            if product_slug:
                store_url = f"https://store.epicgames.com/p/{product_slug}"
            elif url_slug:
                store_url = f"https://store.epicgames.com/p/{url_slug}"
            else:
                store_url = "No URL Found"
            
            # Extract an image URL
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
    # Initialize Firebase
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
        firebase_admin.initialize_app(cred)
        db = firestore.client()
    except Exception as e:
        print('Failed to initialize Firebase:', e)
        return

    # Firestore update logic
    collection_ref = db.collection('epic_free_games')
    existing_games_snapshot = collection_ref.stream()
    existing_games = {}
    for doc in existing_games_snapshot:
        existing_games[doc.id] = doc.to_dict()

    # We'll collect newly added games if needed
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
            # Fallback if no matching pattern
            game_id = sanitize(game['title'].replace(' ', '_').lower())

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
    write_static_games_file(db)


def main():
    """
    Main entry point: fetch free games, update Firestore.
    If anything fails, we send an email to info@weeklygamevault.com.
    """
    try:
        free_games = get_epic_free_games()
        print("Free games found:")
        for fg in free_games:
            print(f" - {fg['title']} => {fg['url']}")
        
        # Update Firestore
        update_firestore_with_free_games(free_games)

    except Exception as e:
        # If something fails, send an email to info@weeklygamevault.com
        error_trace = traceback.format_exc()
        subject = "Epic Free Games Script Failure"
        content = (
            f"An error occurred while running the script:\n\n"
            f"Error: {str(e)}\n\n"
            f"Traceback:\n{error_trace}\n\n"
        )

        print("Script failed. Sending error email...")
        send_email(subject, content)
        print("Email sent. Exiting with error.")
        raise  # Optionally re-raise the exception if you want the script to exit with an error code


if __name__ == "__main__":
    main()
