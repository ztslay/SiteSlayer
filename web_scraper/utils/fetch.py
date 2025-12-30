"""
HTTP fetching utilities
"""

import asyncio
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright._impl._errors import Error as PlaywrightError
from utils.logger import setup_logger
from config import USER_AGENT

logger = setup_logger(__name__)

# Browser pool for Playwright reuse
_browser_pool = None
_browser_lock = asyncio.Lock()

# Default HTTP headers for requests
DEFAULT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    # Removed Accept-Encoding to avoid binary/compressed response issues
    # requests will still handle decompression automatically if needed
    'DNT': '1',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

async def get_browser_instance():
    """
    Get or create a shared browser instance (singleton pattern with async lock)
    
    Returns:
        dict: Dictionary with 'playwright' and 'browser' keys, or None if failed
    """
    global _browser_pool
    
    async with _browser_lock:
        if _browser_pool is None:
            try:
                from playwright.async_api import async_playwright
                
                logger.info("Initializing Playwright browser pool...")
                playwright = await async_playwright().start()
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                    ]
                )
                _browser_pool = {
                    'playwright': playwright,
                    'browser': browser
                }
                logger.info("Browser pool initialized successfully")
            except ImportError:
                logger.error("Playwright not installed. Install with: pip install playwright && playwright install chromium")
                return None
            except Exception as e:
                logger.error(f"Failed to initialize browser pool: {str(e)}", exc_info=True)
                return None
        
        return _browser_pool


async def cleanup_browser_pool():
    """
    Clean up the browser pool when done with all scraping operations.
    Should be called when all fetching is complete.
    """
    global _browser_pool
    
    async with _browser_lock:
        if _browser_pool:
            try:
                logger.info("Cleaning up browser pool...")
                await _browser_pool['browser'].close()
                await _browser_pool['playwright'].stop()
                _browser_pool = None
                logger.info("Browser pool cleaned up successfully")
            except Exception as e:
                logger.error(f"Error cleaning up browser pool: {str(e)}", exc_info=True)
                _browser_pool = None


async def create_browser_context(browser):
    """
    Create a browser context with standard settings including SSL error bypass.
    
    Args:
        browser: Playwright browser instance
        
    Returns:
        Browser context with ignore_https_errors enabled
    """
    return await browser.new_context(
        user_agent=USER_AGENT,
        viewport={'width': 1920, 'height': 1080},
        ignore_https_errors=True
    )


async def navigate_with_fallbacks(page, url, timeout, config, raise_on_403=True):
    """
    Navigate to a URL with multiple fallback strategies:
    1. HTTPS with networkidle
    2. HTTPS with domcontentloaded
    3. HTTP with networkidle (if URL is HTTPS)
    4. HTTP with domcontentloaded (if URL is HTTPS)
    
    Handles SSL errors, connection errors, and timeouts gracefully.
    
    Args:
        page: Playwright page instance
        url (str): URL to navigate to
        timeout (int): Timeout in seconds
        config: Configuration object (for timeout_reduced flag)
        raise_on_403 (bool): If True, raise RuntimeError on 403. If False, return None.
        
    Returns:
        tuple: (response, successful_url, timeout_occurred)
            - response: Playwright response object or None
            - successful_url: The URL that successfully loaded (may differ from input)
            - timeout_occurred: Boolean indicating if a timeout occurred
            
    Raises:
        RuntimeError: If 403 Forbidden and raise_on_403=True
        PlaywrightError: If all strategies fail with non-connection errors
    """
    response = None
    connection_error = None
    timeout_occurred = False
    successful_url = url
    
    # Try multiple strategies to load the page
    strategies = [
        ('networkidle', url),  # Try HTTPS with networkidle first
        ('domcontentloaded', url),  # Try HTTPS with domcontentloaded if networkidle fails
    ]
    
    # If URL is HTTPS, also try HTTP as fallback
    if url.startswith('https://'):
        http_url = url.replace('https://', 'http://', 1)
        strategies.extend([
            ('networkidle', http_url),
            ('domcontentloaded', http_url),
        ])
    
    for wait_strategy, try_url in strategies:
        try:
            logger.debug(f"Trying {try_url} with wait_until='{wait_strategy}'...")
            response = await page.goto(try_url, wait_until=wait_strategy, timeout=timeout * 1000)
            if response and response.status == 403:
                error_msg = f"Received 403 Forbidden status for {try_url}"
                logger.error(error_msg)
                # Try next strategy if available
                if try_url != strategies[-1][1]:
                    continue
                if raise_on_403:
                    raise RuntimeError(error_msg)
                return None, url, False
            logger.debug(f"Page loaded successfully from {try_url}")
            # Update successful_url if we used a fallback
            if try_url != url:
                successful_url = try_url
                logger.info(f"Successfully loaded via fallback URL: {try_url}")
            # Reset timeout flag if we succeeded
            timeout_occurred = False
            break  # Success, exit strategy loop
        except PlaywrightTimeoutError as e:
            timeout_occurred = True
            # Mark config to use reduced timeout for subsequent pages
            if not getattr(config, 'timeout_reduced', False):
                config.timeout_reduced = True
                logger.info(f"Site appears slow - reducing timeout to 4 seconds for remaining pages")
            logger.warning(f"Timeout waiting for {wait_strategy} on {try_url}: {str(e)}")
            # Try next strategy if available
            if try_url != strategies[-1][1]:
                continue
            logger.info("Attempting to capture partial HTML content that has already loaded...")
            # Don't re-raise - we'll try to get whatever content is available
        except PlaywrightError as e:
            error_msg = str(e)
            connection_error = e
            # Check if it's a connection error that might be fixed by trying HTTP
            if "ERR_CONNECTION_CLOSED" in error_msg or "ERR_CONNECTION_REFUSED" in error_msg:
                logger.warning(f"Connection error with {try_url}: {error_msg}")
                # Try next strategy if available
                if try_url != strategies[-1][1]:
                    logger.info(f"Trying fallback strategy...")
                    continue
            # If it's the last strategy or not a connection error, re-raise
            if try_url == strategies[-1][1] or "ERR_CONNECTION" not in error_msg:
                raise
    
    # If we still have a connection error and no response, raise it
    if connection_error and not response:
        raise connection_error
    
    return response, successful_url, timeout_occurred

