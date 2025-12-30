"""
HTML to Markdown conversion utilities
"""

from bs4 import BeautifulSoup
from markdownify import markdownify as md
from utils.logger import setup_logger

logger = setup_logger(__name__)

ALLOWED_TAGS = {
    "title",
    "main",
    "section",
    "article",
    "header",
    "footer",
    "nav",
    "h1", "h2", "h3",
    "p",
    "ul", "ol", "li",
    "a",
}

def clean_soup(soup: BeautifulSoup) -> BeautifulSoup:
    """
    Remove unsemantic tags from BeautifulSoup, keeping only semantic HTML tags.
    
    Args:
        soup: BeautifulSoup object to clean
        
    Returns:
        BeautifulSoup: The same soup object with non-allowed tags unwrapped
    """
    # Strip unwanted tags completely
    for tag in soup(["style", "script", "noscript", "template", "svg", "link"]):
        tag.decompose()
    
    # Unwrap other non-semantic tags
    for tag in soup.find_all(True):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
    return soup

def html_to_markdown(html_content):
    """
    Convert HTML content to Markdown
    
    Args:
        html_content (str): HTML content to convert
        base_url (str, optional): Base URL for resolving relative links
        
    Returns:
        str: Markdown formatted content
    """
    try:
        # Convert HTML to Markdown
        markdown = md(
            html_content,
            heading_style="ATX",  # Use # style headings
            bullets="-",  # Use - for bullet lists
            strip=['script', 'style'],  # Remove script and style tags
            escape_asterisks=False,
            escape_underscores=False,
        )
        
        return markdown
        
    except Exception as e:
        logger.error(f"Error converting HTML to Markdown: {str(e)}", exc_info=True)
        return ""

def remove_duplicate_lines(content):
    """
    Remove duplicate lines from content, keeping empty lines.
    Then combine consecutive newlines to a maximum of two.
    
    Args:
        content (str): The content string to process
        
    Returns:
        str: Processed content with duplicates removed and newlines normalized
    """
    # Split content into lines
    lines = content.split('\n')
    
    # Track seen non-empty lines, keep empty lines always
    seen_lines = set()
    deduplicated_lines = []
    
    for line in lines:
        line = line.strip()
        # Empty lines (line returns only) are always kept
        if line == '' or line == '---':
            deduplicated_lines.append(line)
        else:
            # For non-empty lines, only keep if not seen before
            if line not in seen_lines:
                seen_lines.add(line)
                deduplicated_lines.append(line)
    
    # Combine consecutive newlines to maximum of two
    result_lines = []
    i = 0
    while i < len(deduplicated_lines):
        line = deduplicated_lines[i]
        
        if line == '':
            # Count consecutive empty lines
            empty_count = 0
            j = i
            while j < len(deduplicated_lines) and deduplicated_lines[j] == '':
                empty_count += 1
                j += 1
            
            # Add maximum of 2 empty lines
            result_lines.extend([''] * min(empty_count, 2))
            i = j
        else:
            result_lines.append(line)
            i += 1
    
    # Join back with newlines
    return '\n'.join(result_lines)

