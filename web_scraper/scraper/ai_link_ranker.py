"""
AI-powered link ranking using OpenAI
"""

import os
from pydantic import BaseModel
from openai import AsyncOpenAI
from utils.logger import setup_logger

PREVIEW_LENGTH = 100000  # Length of content preview to send to AI

logger = setup_logger(__name__)

class URLList(BaseModel):
    """Pydantic model for list of URLs"""
    urls: list[str]

async def rank_links(content: str, target_url: str, config):
    """
    Extract relevant URLs using AI based on homepage content
    
    Args:
        content (str): The homepage content (markdown text)
        target_url (str): The target URL of the site
        config (Config): Configuration object
        
    Returns:
        list[str]: List of relevant URLs
        
    Raises:
        ValueError: If OPENAI_API_KEY environment variable is not set
    """
    openai_api_key = os.getenv('OPENAI_API_KEY')
    if not openai_api_key:
        error_msg = "OPENAI_API_KEY environment variable is required for AI ranking but was not found"
        logger.error(error_msg)
        raise ValueError(error_msg)
    
    try:
        client = AsyncOpenAI()
        
        # Truncate content if too long
        content_preview = content[:PREVIEW_LENGTH] if len(content) > PREVIEW_LENGTH else content
        
        prompt = f"""Return a list of URLs that seem most relevant to understanding {target_url} based on this text:

{content_preview}

- Only include URLs that are mentioned in the text.
- Only return URLs that contain html or text content of some sort (e.g. no images, raw data, or complex document types like pdfs or word documents).
- Don't return urls with fragments like https://example.com#fragment.
- Return only unique content - for example https://www.hello.com/index.html and https://www.hello.com are the same.
- Don't return {target_url} (we already retrieved the content for this url).
- Prefer urls that are within the same domain as {target_url} unless it is obvious that they are relevant to the content of {target_url}.

Return a list of full URL strings."""

        # Try using .parse() method if available (OpenAI SDK >= 1.0)
        completion = await client.chat.completions.parse(
            model=config.ai_model,
            messages=[
                {"role": "system", "content": "You are a web content analysis assistant. Extract only the most relevant URLs from the content. Limit the number of URLs to 15 (but you can return less if there are not enough relevant urls). Return the urls in order of relevance."},
                {"role": "user", "content": prompt}
            ],
            response_format=URLList
        )
        # Get parsed response - extract the list[str] from the model
        parsed_response = completion.choices[0].message.parsed
        urls = parsed_response.urls if parsed_response else []
               
        logger.info(f"AI extracted {len(urls)} URLs")
        return urls
        
    except Exception as e:
        logger.error(f"Error ranking links with AI: {str(e)}", exc_info=True)
        logger.info("Falling back to empty list")
        return []
