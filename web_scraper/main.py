"""
SiteSlayer - Main Entry Point
Web scraper for extracting website HTML and markdown content
"""

import sys
from dotenv import load_dotenv
load_dotenv()
import shutil
import traceback
import asyncio
from pathlib import Path
from datetime import datetime
from config import Config, sanitize_domain
from harvester import harvest_html
from scraper.homepage import scrape_homepage
from scraper.crawler import crawl_urls
from scraper.ai_link_ranker import rank_links
from utils.logger import setup_logger
from utils.fetch import cleanup_browser_pool
from utils.markdown_utils import remove_duplicate_lines

from email_writer import EmailWriter

def write_error_to_file(site_dir, error_message, exception=None):
    """
    Write an error message to error.txt in the site directory.
    
    Args:
        site_dir (Path): Path to the site directory where error.txt should be written
        error_message (str): Human-readable error message
        exception (Exception, optional): The exception object if available
    """
    try:
        # Ensure the site directory exists
        site_dir = Path(site_dir)
        site_dir.mkdir(parents=True, exist_ok=True)
        
        error_file = site_dir / 'error.txt'
        
        with open(error_file, 'w', encoding='utf-8') as f:
            f.write(f"ERROR REPORT\n")
            f.write(f"{'='*50}\n")
            f.write(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"\nError Message:\n{error_message}\n\n")
            
            if exception:
                f.write(f"Exception Type: {type(exception).__name__}\n")
                f.write(f"\nTraceback:\n")
                # Use format_exception to properly format the exception outside of handler context
                exc_type, exc_value, exc_tb = type(exception), exception, exception.__traceback__
                if exc_tb is None:
                    # If no traceback attached, try to get current traceback
                    import sys
                    exc_tb = sys.exc_info()[2]
                f.write(''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))
            else:
                # Even without an exception, try to capture current stack trace
                f.write(f"\nStack Trace:\n")
                f.write(''.join(traceback.format_stack()))
        
    except Exception as e:
        # If we can't write the error file, log it but don't fail
        logger = setup_logger(__name__)
        logger.error(f"Failed to write error.txt file: {str(e)}", exc_info=True)

async def execute(target_url):
    """Execute scraping for a single URL"""
    logger = setup_logger(__name__)

    # Ensure URL has proper scheme
    if not target_url.startswith(('http://', 'https://')):
        target_url = f"https://{target_url}"

    # Get the site directory path (where final output goes) - do this before Config
    # in case Config fails, we still need to know where to write errors
    domain = sanitize_domain(target_url)
    site_dir = Path('sites') / domain
    
    # Check if site directory already exists - fast return if it does
    if site_dir.exists() and site_dir.is_dir():
        logger.info(f"Site directory already exists: {site_dir}. Skipping processing.")
        return

    # Load configuration with target URL (now that we know site_dir)
    try:
        config = Config(target_url)
    except Exception as e:
        error_msg = f"Failed to initialize configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        write_error_to_file(site_dir, error_msg, e)
        return

    logger.info(f"Starting to harvest HTML: {target_url}")

    try:
        # Step 1: Harvest HTML from homepage
        logger.info("Step 1: Harvesting homepage HTML...")
        try:
            html_file = await harvest_html(target_url, config)
        except Exception as harvest_error:
            error_msg = f"HTML harvesting failed with exception: {str(harvest_error)}"
            logger.error(error_msg, exc_info=True)
            write_error_to_file(site_dir, error_msg, harvest_error)
            return

        if html_file:
            logger.info(f"Homepage HTML harvested: {html_file}")
        else:
            error_msg = "HTML harvesting failed - no HTML file was produced"
            logger.error(error_msg)
            write_error_to_file(site_dir, error_msg)
            return

        # Step 2: Crawl the site
        logger.info("Step 2: Crawling site...")
        crawl_results, content_file = await crawl_site(target_url, domain, config)
        
        if crawl_results is None:
            error_msg = "Failed to crawl site - no results returned"
            logger.error(error_msg)
            write_error_to_file(site_dir, error_msg)
            return
        
        # Check if content file exists and has sufficient content
        if content_file and Path(content_file).exists():
            try:
                with open(content_file, 'r', encoding='utf-8') as f:
                    content_length = len(f.read())
                if content_length < 1000:
                    error_msg = f"Content file is too small ({content_length} characters) - likely incomplete or blocked"
                    logger.error(error_msg)
                    write_error_to_file(site_dir, error_msg)
                    return
            except Exception as e:
                logger.warning(f"Failed to check content file length: {str(e)}")
            
        logger.info(f"Crawl complete. Total pages scraped: {len(crawl_results)}")

        email_writer_path = site_dir / 'email.txt'
        if content_file and Path(content_file).exists():
            # Step 3: Generate email using EmailWriter
            logger.info("Step 3: Generating email from aggregated content...")
            email_writer = EmailWriter(site=domain)
            email_text = await email_writer.write()
            # Save email to file
            with open(email_writer_path, 'w', encoding='utf-8') as f:
                f.write(email_text)
            
            logger.info(f"Email generated and saved to: {email_writer_path}")

        # Display results summary
        print("\n" + "="*50)
        print(f"PROCESSING COMPLETE: {target_url}")
        print("="*50)
        print(f"HTML file: {html_file or 'N/A'}")
        print(f"Total pages scraped: {len(crawl_results)}")
        if content_file:
            print(f"Aggregated content: {content_file}")
        print("="*50 + "\n")

    except KeyboardInterrupt:
        logger.info("\nProcess interrupted by user (Ctrl+C)")
        # Remove the site directory since processing was interrupted
        try:
            if site_dir.exists() and site_dir.is_dir():
                shutil.rmtree(site_dir)
                logger.info(f"Removed incomplete site directory: {site_dir}")
        except Exception as cleanup_error:
            logger.warning(f"Failed to remove site directory: {str(cleanup_error)}")
        raise  # Re-raise to stop processing
    except Exception as e:
        error_msg = f"Error during processing: {str(e)}"
        logger.error(error_msg, exc_info=True)
        write_error_to_file(site_dir, error_msg, e)


async def crawl_site(target_url, domain, config):
    """
    Crawl the site by scraping homepage, crawling URLs, and aggregating markdown content.
    
    Args:
        target_url (str): The target URL to crawl
        domain (str): The sanitized domain name
        config (Config): Configuration object
        
    Returns:
        tuple: (crawl_results, content_file) or (None, None) on error
    """
    logger = setup_logger(__name__)
    
    # Scrape homepage for markdown
    logger.info("Scraping homepage...")
    homepage_data = await scrape_homepage(target_url, config)
    
    if not homepage_data:
        error_msg = "Failed to scrape homepage - no data returned"
        logger.error(error_msg)
        return None, None
    
    logger.info(f"Homepage scraped successfully: {homepage_data['title']}")
    
    # Rank links if AI ranking is enabled
    if config.use_ai_ranking:
        logger.info("Ranking links using AI...")
        links_to_crawl = await rank_links(homepage_data['content'], target_url, config)
    else:
        links_to_crawl = homepage_data['links']
    
    # Limit to max_pages
    links_to_crawl = links_to_crawl[:config.max_pages]
    
    # Crawl URLs (async)
    logger.info(f"Crawling {len(links_to_crawl)} URLs...")
    crawl_results = await crawl_urls(links_to_crawl, config)
    
    logger.info(f"Crawl complete. Total pages scraped: {len(crawl_results)}")
    
    # Save list of scraped URLs to the same directory as content.md
    site_dir = Path('sites') / domain
    site_dir.mkdir(parents=True, exist_ok=True)
    urls_file = site_dir / 'urls.txt'
    
    try:
        # Extract URLs from crawl_results (include homepage URL as well)
        scraped_urls = [target_url]  # Start with homepage
        scraped_urls.extend([result['url'] for result in crawl_results if result and 'url' in result])
        
        with open(urls_file, 'w', encoding='utf-8') as f:
            for url in scraped_urls:
                f.write(f"{url}\n")
        
        logger.info(f"Saved {len(scraped_urls)} URLs to: {urls_file}")
    except Exception as e:
        logger.warning(f"Failed to save URLs list: {str(e)}", exc_info=True)
    
    # Concatenate homepage content followed by other pages' content
    logger.info("Concatenating markdown content...")
    site_dir = Path('sites') / domain
    site_dir.mkdir(parents=True, exist_ok=True)
    content_file = site_dir / 'content.md'
    
    try:
        # Start with homepage content
        aggregated_content = [homepage_data['content']]
        
        # Add other pages' content
        for result in crawl_results:
            if result:
                aggregated_content.append(f"\n---\n({result['url']})\n\n{result['content']}")

        logger.info(f"Aggregated {len(aggregated_content)} pages (1 homepage + {len(crawl_results)} other pages)")
        aggregated_content = '\n'.join(aggregated_content)
        aggregated_content = remove_duplicate_lines(aggregated_content)

        # Write to content.md
        with open(content_file, 'w', encoding='utf-8') as f:
            f.write(aggregated_content)
        
        logger.info(f"Successfully created content.md at: {content_file}")
        
        
    except Exception as e:
        logger.error(f"Error writing content.md: {str(e)}", exc_info=True)
        content_file = None
    
    return crawl_results, str(content_file) if content_file else None


async def execute_with_semaphore(semaphore, url):
    """Execute a URL with semaphore control for concurrency limiting"""
    async with semaphore:
        await execute(url)


def cleanup_orphaned_directories(urls):
    """
    Clean up site directories that don't correspond to any provided URLs.
    
    Args:
        urls (list): List of URLs to compare against existing directories
    """
    logger = setup_logger(__name__)
    logger.info("Cleaning up orphaned site directories")
    
    # Convert URLs to directory names and find directories to keep
    expected_dirs = set()
    for url in urls:
        # Ensure URL has proper scheme for sanitize_domain
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
        domain = sanitize_domain(url)
        expected_dirs.add(domain)
    
    # Get all directories in sites folder
    sites_dir = Path('sites')
    if sites_dir.exists() and sites_dir.is_dir():
        existing_dirs = [d.name for d in sites_dir.iterdir() if d.is_dir()]
        
        # Find directories that don't match any expected directory
        dirs_to_delete = [d for d in existing_dirs if d not in expected_dirs]
        
        if dirs_to_delete:
            logger.info(f"Found {len(dirs_to_delete)} orphaned directory(ies) to delete")
            for dir_name in dirs_to_delete:
                dir_path = sites_dir / dir_name
                try:
                    shutil.rmtree(dir_path)
                    logger.info(f"Deleted orphaned directory: {dir_path}")
                except Exception as e:
                    logger.error(f"Failed to delete directory {dir_path}: {str(e)}", exc_info=True)
        else:
            logger.info("No orphaned directories found")
    else:
        logger.info("Sites directory does not exist - nothing to clean up")


def main():
    """Main entry point - handles command line args or loads sites_to_scrape.txt"""
    logger = setup_logger(__name__)
    
    # Get URLs from command line or sites_to_scrape.txt
    urls = []
    urls_from_command_line = False
    if len(sys.argv) > 1:
        # Use command line arguments as URLs
        urls = [url.strip() for url in sys.argv[1:] if url.strip()]

        # Remove site directories for command line URLs
        sites_dir = Path('sites')
        if not sites_dir.exists() or not sites_dir.is_dir():
            raise FileNotFoundError(f"Sites directory does not exist: {sites_dir}")
        for url in urls:
            # Ensure URL has proper scheme for sanitize_domain
            domain = sanitize_domain(url)
            site_dir = sites_dir / domain
            if site_dir.exists() and site_dir.is_dir():
                try:
                    shutil.rmtree(site_dir)
                    logger.info(f"Removed site directory: {site_dir}")
                except Exception as e:
                    logger.error(f"Failed to remove directory {site_dir}: {str(e)}", exc_info=True)
        urls_from_command_line = True
    else:
        # Load from sites_to_scrape.txt
        sites_file = Path('sites_to_scrape.txt')
        if not sites_file.exists():
            logger.error(f"sites_to_scrape.txt not found at {sites_file.absolute()}")
            return
        
        try:
            with open(sites_file, 'r', encoding='utf-8') as f:
                urls = []
                for line in f:
                    line_no_comment = line.partition("#")[0].strip()
                    if line_no_comment:
                        urls.append(line_no_comment)
        except Exception as e:
            logger.error(f"Failed to read sites_to_scrape.txt: {str(e)}", exc_info=True)
            return
    
    if not urls_from_command_line:
        cleanup_orphaned_directories(urls)
    
    logger.info(f"Processing {len(urls)} URL(s)...")
    
    # Create semaphore to limit concurrent workers to 5
    semaphore = asyncio.Semaphore(10)
    
    # Run all URLs asynchronously
    async def run_all():
        tasks = [execute_with_semaphore(semaphore, url) for url in urls]
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            logger.info("\nProcess interrupted by user (Ctrl+C)")
            # Cancel remaining tasks
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Wait for cancellations to complete
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            # Clean up browser pool when all tasks are done
            await cleanup_browser_pool()
    
    # Run the async main function
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logger.info("Shutting down...")

if __name__ == "__main__":
    # python web_scraper/main.py https://www.jessehall.com
    # python web_scraper/main.py  # processes sites_to_scrape.txt
    main()
