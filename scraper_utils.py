# scraper_utils.py

import random
import asyncio
import time  # Added import to fix the "time is not defined" error
from typing import Optional, Dict, Any
import json
import os
from datetime import datetime, timedelta

# Common User Agents list
DESKTOP_AGENTS = [
    # Chrome on Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/118.0.0.0 Safari/537.36',

    # Chrome on macOS
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_6) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/118.0.0.0 Safari/537.36',

    # Chrome on Linux
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/118.0.0.0 Safari/537.36',

    # Edge on Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',

    # Opera on Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/120.0.0.0 Safari/537.36 OPR/120.0.0.0',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/119.0.0.0 Safari/537.36 OPR/119.0.0.0',

    # Additional Chromium-based browsers
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/120.0.0.0 Safari/537.36 Brave/120.0.0.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Chrome/120.0.0.0 Safari/537.36 Vivaldi/5.8.2678.49',
]

def get_random_user_agent() -> str:
    """Returns a random user agent from the list."""
    return random.choice(DESKTOP_AGENTS)

def rotate_proxy() -> Optional[str]:
    """
    Rotate proxy by selecting a random proxy from the PROXY_LIST environment variable.
    Returns None if no proxies are set.
    """
    proxy_list = os.getenv('PROXY_LIST', '').split(',')
    proxy_list = [proxy.strip() for proxy in proxy_list if proxy.strip()]
    if not proxy_list:
        return None
    return random.choice(proxy_list)

class SyncRequestRateLimiter:
    """Synchronous Rate Limiter for synchronous scripts like epic.py."""
    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.request_times = []

    def wait_if_needed(self):
        """
        Implements rate limiting by tracking request times and adding delays when needed.
        """
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)

        # Remove old requests from tracking
        self.request_times = [t for t in self.request_times if t > minute_ago]

        if len(self.request_times) >= self.requests_per_minute:
            # Calculate wait time until we can make a new request
            earliest_request = self.request_times[0]
            wait_seconds = (earliest_request + timedelta(minutes=1) - now).total_seconds()
            if wait_seconds > 0:
                print(f"Rate limit reached. Waiting for {wait_seconds:.2f} seconds.")
                time.sleep(wait_seconds)

        self.request_times.append(now)

class AsyncRequestRateLimiter:
    """Asynchronous Rate Limiter for asynchronous scripts like crawler.py and gog.py."""
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
            # Calculate wait time until we can make a new request
            earliest_request = self.request_times[0]
            wait_seconds = (earliest_request + timedelta(minutes=1) - now).total_seconds()
            if wait_seconds > 0:
                print(f"Rate limit reached. Waiting for {wait_seconds:.2f} seconds.")
                await asyncio.sleep(wait_seconds)

        self.request_times.append(now)

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
        "locale": random.choice(['en-US', 'en-GB']),
        "timezone_id": random.choice([
            'Europe/London',
            'Europe/Berlin',
            'Europe/Paris',
            'Europe/Madrid',
            'Europe/Rome',
            'Europe/Dublin',
            'Europe/Amsterdam',
            'Europe/Copenhagen',
            'Europe/Stockholm',
            'Europe/Vienna'
        ]),
        "geolocation": {
            "longitude": random.uniform(-10.0, 30.0),
            "latitude": random.uniform(35.0, 60.0),
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
    // Existing overrides
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-GB', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [
        {
            0: { type: "application/x-google-chrome-pdf" },
            description: "Portable Document Format",
            filename: "internal-pdf-viewer",
            length: 1,
            name: "Chrome PDF Plugin"
        }
    ]});
    Object.defineProperty(navigator, 'mimeTypes', { get: () => [
        {
            type: 'application/pdf',
            suffixes: 'pdf',
            description: 'Portable Document Format'
        }
    ]});
    Object.defineProperty(navigator, 'permissions', { get: () => ({
        query: (parameters) => Promise.resolve({ state: 'granted' })
    })});
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 0 });
    Object.defineProperty(navigator, 'clipboard', { get: () => ({
        writeText: () => {},
        readText: () => Promise.resolve('')
    })});
    Object.defineProperty(navigator, 'mediaDevices', { get: () => ({
        getUserMedia: () => Promise.resolve({})
    })});
    Object.defineProperty(navigator, 'storage', { get: () => ({
        estimate: () => Promise.resolve({ quota: 1000000000, usage: 0 })
    })});
    Object.defineProperty(window, 'chrome', { get: () => ({ runtime: {} }) });
    window.addEventListener('devtoolschange', function() {});
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'userAgent', { get: () => navigator.userAgent });
    
    // Additional overrides
    Object.defineProperty(navigator, 'connection', { get: () => ({
        effectiveType: '4g',
        downlink: 10,
        rtt: 50,
        saveData: false
    })});
    
    Object.defineProperty(navigator, 'mediaQueryList', { get: () => ({
        matches: false,
        media: '',
        onchange: null,
        addListener: () => {},
        removeListener: () => {}
    })});
    
    Object.defineProperty(window, 'navigator', { get: () => navigator });
    
    Object.defineProperty(navigator, 'getBattery', { get: () => () => Promise.resolve({
        charging: true,
        chargingTime: 0,
        dischargingTime: Infinity,
        level: 1
    })});
    
    // Mock WebGL renderer information
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, ...args) {
        const context = getContext.apply(this, [type, ...args]);
        if (type === 'webgl' || type === 'experimental-webgl') {
            const getParameter = context.getParameter;
            context.getParameter = function(parameter) {
                if (parameter === 37445) { // UNMASKED_VENDOR_WEBGL
                    return 'Intel Inc.';
                }
                if (parameter === 37446) { // UNMASKED_RENDERER_WEBGL
                    return 'Intel Iris OpenGL Engine';
                }
                return getParameter.apply(this, arguments);
            };
        }
        return context;
    };
    """)
    
    return context, page

def get_random_delay(min_ms: int = 500, max_ms: int = 3000) -> float:
    """Returns a random delay in seconds within the specified range."""
    return random.uniform(min_ms, max_ms) / 1000

async def natural_scroll(page, max_scrolls: int = 50, min_delay: int = 1500, max_delay: int = 4000):
    """
    Performs natural-looking scrolling by pressing PageDown with delays.
    """
    previous_count = 0
    for scroll in range(max_scrolls):
        # Press PageDown to scroll
        await page.keyboard.press('PageDown')
        print(f"Scroll {scroll + 1}/{max_scrolls}: Pressed PageDown")
        
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
