# scraper_utils.py

import random
import asyncio
from typing import Optional, Dict, Any
import json
import os
from datetime import datetime, timedelta

# Common User Agents list
DESKTOP_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Edge/120.0.0.0'
]

def get_random_user_agent() -> str:
    """Returns a random user agent from the list."""
    return random.choice(DESKTOP_AGENTS)

async def setup_browser_context(playwright, cfg: Dict[str, Any]):
    """
    Sets up a browser context with enhanced anti-detection measures.
    """
    # Random viewport size within reasonable bounds
    width = random.randint(1024, 1920)
    height = random.randint(768, 1080)
    
    # Browser context options with anti-fingerprinting measures
    context_options = {
        "viewport": {"width": width, "height": height},
        "user_agent": get_random_user_agent(),
        "locale": random.choice(['en-US', 'en-GB', 'en-CA']),
        "timezone_id": random.choice(['America/New_York', 'Europe/London', 'America/Los_Angeles']),
        "geolocation": {
            "longitude": random.uniform(-122.4194, -73.9350),
            "latitude": random.uniform(37.7749, 40.7128),
        },
        "permissions": ["geolocation"],
        "color_scheme": "light",
        "device_scale_factor": random.choice([1, 2]),
        "is_mobile": False,
        "has_touch": False,
        "headless": cfg.get('headless', True),
        "proxy": cfg.get('proxy', None),
    }
    
    # Determine browser type
    browser_type = playwright.firefox
    if cfg.get('browser', 'firefox') == 'chromium':
        browser_type = playwright.chromium
    elif cfg.get('browser', 'firefox') == 'webkit':
        browser_type = playwright.webkit
    
    # Launch persistent context with the configured options
    context = await browser_type.launch_persistent_context(
        user_data_dir=cfg['browser_data_dir'],
        **context_options
    )
    
    # Get the default page
    page = context.pages[0] if context.pages else await context.new_page()
    
    # Additional page configurations
    await page.set_extra_http_headers({
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'DNT': '1',
        'Upgrade-Insecure-Requests': '1',
    })
    
    # Add common browser properties to evade detection
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => false});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        Object.defineProperty(navigator, 'plugins', {get: () => [
            {
                0: {type: "application/x-google-chrome-pdf"},
                description: "Portable Document Format",
                filename: "internal-pdf-viewer",
                length: 1,
                name: "Chrome PDF Plugin"
            }
        ]});
        // Additional properties can be added here
    """)
    
    return context, page

def get_random_delay(min_ms: int = 500, max_ms: int = 3000) -> float:
    """Returns a random delay in seconds within the specified range."""
    return random.uniform(min_ms, max_ms) / 1000

def rotate_proxy():
    """
    Implement your proxy rotation logic here.
    This is a placeholder - you would need to add your own proxy service.
    """
    proxy_list = os.getenv('PROXY_LIST', '').split(',')
    if not proxy_list or proxy_list == ['']:
        return None
    return random.choice(proxy_list)

class RequestRateLimiter:
    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.request_times = []
    
    async def wait_if_needed(self):
        """
        Implements rate limiting by tracking request times and adding delays when needed.
        """
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        
        # Remove old requests from tracking
        self.request_times = [t for t in self.request_times if t > minute_ago]
        
        if len(self.request_times) >= self.requests_per_minute:
            # Wait until we're under the limit
            wait_time = (self.request_times[0] - minute_ago).total_seconds()
            if wait_time > 0:
                print(f"Rate limit reached. Waiting for {wait_time} seconds.")
                await asyncio.sleep(wait_time)
        
        self.request_times.append(now)

async def natural_scroll(page, max_scrolls: int = 50, min_delay: int = 1500, max_delay: int = 4000):
    """
    Performs natural-looking scrolling by pressing PageDown with delays.
    """
    previous_count = 0
    for scroll in range(max_scrolls):
        # Press PageDown to scroll
        await page.keyboard.press('PageDown')
        print(f"Scroll {scroll + 1}: Pressed PageDown")
        
        # Wait for network to be idle and additional timeout
        await page.wait_for_load_state('networkidle')
        await page.wait_for_timeout(random.uniform(min_delay, max_delay))  # Wait between min_delay to max_delay
        
        # Check the number of games loaded
        current_count = await page.evaluate("""
            () => {
                const games = document.querySelectorAll('div[data-a-target="offer-list-FGWP_FULL"] a[data-a-target="learn-more-card"]');
                return games.length;
            }
        """)
        print(f"Scroll {scroll + 1}: Found {current_count} games")
        
        if current_count > previous_count:
            previous_count = current_count
        else:
            print('No new games loaded. Stopping scrolling.')
            break

    print(f"Total games found after scrolling: {current_count}")
    return current_count

async def human_like_mouse_movements(page, viewport_width: int, viewport_height: int):
    """
    Simulates human-like mouse movements across the viewport.
    """
    moves = random.randint(5, 15)  # Number of movements

    for _ in range(moves):
        x = random.randint(0, viewport_width)
        y = random.randint(0, viewport_height)
        steps = random.randint(10, 30)
        await page.mouse.move(x, y, steps=steps)
        await asyncio.sleep(random.uniform(0.05, 0.2))  # Short delay between movements
