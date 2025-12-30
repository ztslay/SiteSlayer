"""
Site crawler - Navigates through website links and scrapes content
"""

import asyncio
import threading
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright._impl._errors import Error as PlaywrightError
from utils.fetch import get_browser_instance, create_browser_context, navigate_with_fallbacks
from utils.logger import setup_logger
from utils.markdown_utils import html_to_markdown, clean_soup

logger = setup_logger(__name__)

def normalize_url(url):
    """
    Normalize URL by removing fragment (hash) to ensure uniqueness
    URLs that differ only by hash are treated as the same
    """
    parsed = urlparse(url)
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        clean_url += f"?{parsed.query}"
    return clean_url

async def _process_single_url(url, index, total, visited_urls, visited_lock, config):
    """
    Process a single URL - extracted for parallel processing
    
    Args:
        url: URL to process
        index: Index of this URL in the list (for logging)
        total: Total number of URLs
        visited_urls: Set of visited URLs (thread-safe access via lock)
        visited_lock: Lock for thread-safe access to visited_urls
        config: Configuration object
        
    Returns:
        dict: Page data if successful, None otherwise
    """
    # Normalize URL (remove fragment) to check for duplicates
    normalized_url = normalize_url(url)
    
    # Check and mark as visited (thread-safe)
    with visited_lock:
        if normalized_url in visited_urls:
            return None
        visited_urls.add(normalized_url)
    
    logger.info(f"[{index}/{total}] Scraping: {url}")
    
    try:
        # Fetch page using Playwright pattern
        pool = await get_browser_instance()
        if not pool:
            logger.warning(f"Browser pool unavailable - cannot fetch: {url}")
            return None
        
        browser = pool['browser']
        context = None
        page = None
        html_content = None
        timeout_occurred = False
        
        try:
            # Create context with user agent and SSL error bypass
            context = await create_browser_context(browser)
            
            # Create page and navigate
            page = await context.new_page()
            
            # Use reduced timeout (4 seconds) if we've already hit a timeout for this site
            effective_timeout = 4 if getattr(config, 'timeout_reduced', False) else getattr(config, 'timeout', 15)
            
            response, url, timeout_occurred = await navigate_with_fallbacks(
                page, url, effective_timeout, config, raise_on_403=False
            )
            
            if response is None:
                return None
            
            # Get the rendered HTML (even if timeout occurred)
            html_content = await page.content()
            if timeout_occurred:
                logger.warning(f"Retrieved partial HTML content: {len(html_content)} characters (timeout occurred)")
        except PlaywrightError as e:
            error_msg = str(e)
            if "Executable doesn't exist" in error_msg or "BrowserType.launch" in error_msg:
                logger.error(f"Playwright browser not installed. Please run: playwright install chromium")
            else:
                logger.error(f"Playwright error fetching {url}: {error_msg}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}", exc_info=True)
            return None
        finally:
            # Clean up only context and page (browser/playwright are managed by the pool)
            try:
                if page:
                    await page.close()
                if context:
                    await context.close()
            except Exception as cleanup_error:
                logger.warning(f"Error during browser cleanup: {str(cleanup_error)}")
        
        if not html_content:
            logger.warning(f"Failed to fetch: {url}")
            return None
        
        # Parse and extract content
        soup = BeautifulSoup(html_content, 'lxml')
        clean_soup(soup)
        
        # Extract title
        title = soup.title.string if soup.title else "No title"
        
        # Convert to markdown
        markdown_content = html_to_markdown(str(soup))
        
        # Check minimum content length
        if len(markdown_content) < config.min_content_length:
            logger.info(f"Content too short, skipping: {url}")
            return None
        
        # Return page data
        page_data = {
            'url': url,
            'title': title,
            'content': markdown_content
        }
        
        return page_data
        
    except Exception as e:
        logger.error(f"Error crawling {url}: {str(e)}", exc_info=True)
        return None


async def crawl_urls(links_to_crawl, config):
    """
    Crawl URLs from the provided list of links in parallel
    
    Args:
        links_to_crawl (list[str]): List of URL strings to crawl (already ranked/processed)
        config (Config): Configuration object
        
    Returns:
        list: List of scraped page data
    """
    visited_urls = set()
    visited_lock = threading.Lock()  # Thread-safe lock for visited_urls set
    results = []
    
    logger.info(f"Starting crawl of {len(links_to_crawl)} links (max concurrent: {config.max_concurrent_requests})")
    
    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(config.max_concurrent_requests)
    
    async def process_with_semaphore(url, index):
        """Wrapper to process URL with semaphore control"""
        async with semaphore:
            # Process URL asynchronously
            result = await _process_single_url(
                url,
                index,
                len(links_to_crawl),
                visited_urls,
                visited_lock,
                config
            )
            return result
    
    # Create tasks for all URLs
    tasks = [
        process_with_semaphore(url, i + 1)
        for i, url in enumerate(links_to_crawl)
    ]
    
    # Process all tasks and collect results
    task_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filter out None results and exceptions
    for result in task_results:
        if isinstance(result, Exception):
            logger.error(f"Task raised exception: {str(result)}", exc_info=True)
        elif result is not None:
            results.append(result)
    
    logger.info(f"Crawl complete. Successfully scraped {len(results)} pages")
    return results
