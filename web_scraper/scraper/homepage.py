"""
Homepage scraper - Extracts content and links from website homepage
"""

from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright._impl._errors import Error as PlaywrightError
from utils.fetch import get_browser_instance, create_browser_context, navigate_with_fallbacks
from utils.logger import setup_logger
from scraper.link_rewriter import clean_and_filter_links
from utils.markdown_utils import html_to_markdown, clean_soup

logger = setup_logger(__name__)

async def scrape_homepage(url, config):
    """
    Scrape the homepage and extract content and links
    
    Args:
        url (str): Homepage URL
        config (Config): Configuration object
        
    Returns:
        dict: Contains title, content, and links (links is list[str] of URLs)
    """
    try:
        # Fetch the page using Playwright pattern
        pool = await get_browser_instance()
        if not pool:
            logger.error(f"Browser pool unavailable - cannot fetch homepage: {url}")
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
                logger.error(f"Playwright error fetching homepage {url}: {error_msg}")
            return None
        except Exception as e:
            logger.error(f"Error fetching homepage {url}: {str(e)}", exc_info=True)
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
            logger.error(f"Failed to fetch homepage: {url}")
            return None
        
        # Parse HTML
        soup = BeautifulSoup(html_content, 'lxml')
        clean_soup(soup)
        
        # Extract title
        title = soup.title.string if soup.title else urlparse(url).netloc
        logger.info(f"Page title: {title}")
        
        # Extract and clean links
        all_links = extract_links(soup, url)
        filtered_links = clean_and_filter_links(all_links, url, config)
        
        # Convert to markdown
        markdown_content = html_to_markdown(str(soup))
        
        logger.info(f"Found {len(all_links)} total links, {len(filtered_links)} after filtering")
        
        return {
            'url': url,
            'title': title,
            'content': markdown_content,
            'links': filtered_links
        }
        
    except Exception as e:
        logger.error(f"Error scraping homepage {url}: {str(e)}", exc_info=True)
        return None

def extract_main_content(soup):
    """Extract main content from the page, removing unnecessary elements"""
    
    # Remove unwanted elements (keeping nav for navigation links)
    for element in soup(['script', 'style', 'aside', 'noscript']):
        element.decompose()
    
    # Try to find main content area
    main_content = (
        soup.find('main') or
        soup.find('article') or
        soup.find('div', {'id': 'content'}) or
        soup.find('div', {'class': ['content', 'main-content', 'post-content']}) or
        soup.find('body')
    )
    
    return main_content if main_content else soup

def extract_links(soup, base_url):
    """Extract all links from the page"""
    links = []
    
    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        
        # Skip empty, anchor-only, javascript, and mailto links
        if not href or href.startswith(('#', 'javascript:', 'mailto:', 'tel:')):
            continue
        
        # Convert to absolute URL
        absolute_url = urljoin(base_url, href)
        
        links.append(absolute_url)
    
    return links
