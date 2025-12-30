"""
HTML Harvester - Downloads complete HTML content using Playwright for JavaScript rendering
"""

from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright._impl._errors import Error as PlaywrightError
from utils.logger import setup_logger
from utils.fetch import get_browser_instance, create_browser_context, navigate_with_fallbacks
from utils.markdown_utils import clean_soup
from config import sanitize_domain

logger = setup_logger(__name__)

async def harvest_html(url, config):
    """
    Harvest complete HTML content using Playwright to render JavaScript
    
    Args:
        url (str): The URL to harvest
        config (Config): Configuration object
        
    Returns:
        str: Path to the saved index.html file, or None if failed
    """
    logger.info(f"Harvesting HTML content for: {url}")
    
    context = None
    page = None
    html_content = None
    timeout_occurred = False
    
    # Get shared browser instance from pool
    pool = await get_browser_instance()
    if not pool:
        error_msg = "Browser pool unavailable - cannot harvest HTML"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    browser = pool['browser']
    
    try:
        # Create context with user agent and SSL error bypass
        context = await create_browser_context(browser)
        
        # Create page and navigate
        page = await context.new_page()
        
        # Use reduced timeout (4 seconds) if we've already hit a timeout for this site
        effective_timeout = 4 if getattr(config, 'timeout_reduced', False) else getattr(config, 'timeout', 15)
        
        logger.debug("Loading page with Playwright...")
        response, url, timeout_occurred = await navigate_with_fallbacks(
            page, url, effective_timeout, config, raise_on_403=True
        )
        
        # Get the rendered HTML (even if timeout occurred)
        # Retry logic to handle pages that are still navigating
        html_content = None
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Wait a bit for page to settle (especially important for dynamic pages like Google Maps)
                if attempt > 0:
                    await page.wait_for_timeout(500)  # Wait 500ms between retries
                html_content = await page.content()
                if timeout_occurred:
                    logger.warning(f"Retrieved partial HTML content: {len(html_content)} characters (timeout occurred)")
                else:
                    logger.debug(f"Retrieved HTML content: {len(html_content)} characters")
                break  # Success, exit retry loop
            except Exception as e:
                error_msg = str(e)
                if "Unable to retrieve content because the page is navigating" in error_msg:
                    if attempt < max_retries - 1:
                        logger.debug(f"Page still navigating, retrying ({attempt + 1}/{max_retries})...")
                        continue
                    else:
                        logger.error(f"Failed to retrieve HTML content after {max_retries} attempts: {error_msg}")
                        raise
                else:
                    logger.error(f"Failed to retrieve HTML content: {error_msg}", exc_info=True)
                    raise  # If we can't even get the content, that's a real failure
        
    except PlaywrightError as e:
        error_msg = str(e)
        if "Executable doesn't exist" in error_msg or "BrowserType.launch" in error_msg:
            logger.error(f"Playwright browser not installed. Please run: playwright install chromium")
            logger.error(f"Error details: {error_msg}", exc_info=True)
        else:
            logger.error(f"Playwright error harvesting HTML for {url}: {error_msg}", exc_info=True)
        raise  # Re-raise to allow caller to capture full stack trace
    except Exception as e:
        logger.error(f"Error harvesting HTML for {url}: {str(e)}", exc_info=True)
        raise  # Re-raise to allow caller to capture full stack trace
    finally:
        # Clean up only context and page (browser/playwright are managed by the pool)
        try:
            if page:
                await page.close()
            if context:
                await context.close()
        except Exception as cleanup_error:
            logger.warning(f"Error during browser cleanup: {str(cleanup_error)}")
    
    # If we got here without html_content, something went wrong
    if html_content is None:
        error_msg = "Failed to retrieve HTML content"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    # Parse and rewrite URLs
    soup = BeautifulSoup(html_content, 'lxml')
    rewritten_html = rewrite_urls(soup, url)
    
    # Save to file
    domain = sanitize_domain(url)
    sites_dir = Path('sites')
    target_dir = sites_dir / domain
    target_dir.mkdir(parents=True, exist_ok=True)

    filepath = target_dir / 'index.html'
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(str(rewritten_html))
    
    if timeout_occurred:
        logger.warning(f"Saved partial HTML to: {filepath} (timeout occurred, but content captured)")
    else:
        logger.info(f"Successfully saved HTML to: {filepath}")
    
    return str(filepath)

def rewrite_urls(soup, base_url):
    """
    Rewrite relative URLs in HTML to absolute URLs pointing to original website
    
    Args:
        soup (BeautifulSoup): Parsed HTML soup
        base_url (str): Base URL for making relative URLs absolute
        
    Returns:
        BeautifulSoup: Soup with rewritten URLs
    """
    logger.debug("Rewriting relative URLs to absolute")
    
    # Tags and attributes to rewrite
    tags_to_rewrite = {
        'img': ['src'],
        'script': ['src'],
        'link': ['href'],  # CSS, favicons, etc.
        'a': ['href'],     # Links
        'source': ['src'], # Audio/video sources
        'iframe': ['src'], # Embedded content
        'form': ['action'], # Form actions
    }
    
    for tag_name, attrs in tags_to_rewrite.items():
        for tag in soup.find_all(tag_name):
            for attr in attrs:
                if attr in tag.attrs:
                    href = tag[attr]
                    if href and not href.startswith(('http://', 'https://', 'mailto:', 'tel:', 'javascript:', '#')):
                        # It's relative, make absolute
                        absolute_url = urljoin(base_url, href)
                        tag[attr] = absolute_url
                        logger.debug(f"Rewrote {tag_name} {attr}: {href} -> {absolute_url}")
    
    # Also handle style attributes (CSS within HTML)
    for tag in soup.find_all(style=True):
        # Simple regex to find url() in styles
        import re
        style_content = tag['style']
        def repl_url(match):
            url_part = match.group(2)
            if not url_part.startswith(('http://', 'https://')):
                abs_url = urljoin(base_url, url_part)
                return match.group(1) + abs_url + match.group(3)
            return match.group(0)
        
        new_style = re.sub(r'(url\([\'"]?)([^\'"]+?)([\'"]?\))', repl_url, style_content)
        if new_style != style_content:
            tag['style'] = new_style
    
    return soup
