"""
FastAPI web server for serving scraped sites from the sites/ directory.
Includes chatbot widget integration with mock endpoints.
"""
from website_server.agent import ChatBot
import html
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from urllib.parse import urlparse

app = FastAPI(title="SiteSlayer Web Server")

# Enable CORS if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get the base directory (project root)
BASE_DIR = Path(__file__).parent.parent
SITES_DIR = BASE_DIR / "sites"
CHAT_BOT_DIR = Path(__file__).parent / "chat_bot"
CHAT_BOT_ASSETS_DIR = CHAT_BOT_DIR / "assets"
SITES_TO_SCRAPE_FILE = BASE_DIR / "sites_to_scrape.txt"


def sanitize_domain(url):
    """Sanitize a URL to create a safe directory name"""
    parsed = urlparse(url)
    domain = parsed.netloc or parsed.path
    domain = domain.replace('.', '_').replace(':', '_').replace('/', '_')
    return domain


# Chatbot endpoints
@app.get("/chatbot/widget.js")
async def serve_widget_js():
    """Serve the chatbot widget JavaScript."""
    widget_js_path = CHAT_BOT_DIR / "widget.js"
    if not widget_js_path.exists():
        raise HTTPException(status_code=404, detail="Widget JavaScript not found")
    return FileResponse(
        widget_js_path,
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )


@app.get("/chatbot/api/chatwidget/{site}/")
async def get_chatwidget_config(site: str):
    """Get chatbot widget configuration."""
    # Return mock configuration
    return {
        "chat_bubble_img": "/chatbot/assets/images/chat_bubble.png",
        "close": "/chatbot/assets/images/close.svg",
        "chat_bubble_color": "#3a7ba8",
        "user_msg_text_color": "#69707A",
        "default_icon": False,
        "show_popup_messages_only_once": True,
        "popup_type": None,  # Can be 'initial_messages_popup' or 'chatwidget_popup'
        "initial_message_popup_delay": -1,  # -1 means don't show
        "chatwidget_popup_delay": -1,
        "mobile_popup_type": None,
        "mobile_initial_message_popup_delay": -1,
        "mobile_chatwidget_popup_delay": -1,
        "mobile_initial_messages": [],
        "initial_messages": [
            "Hello! 👋 How can I help you today?",
            "Feel free to ask me anything about our services!"
        ],
        "font_family": "Montserrat, sans-serif",
        "font_size": 14,
        "size_of_widget": "medium"
    }


@app.get("/chatbot/embed/{site}")
async def serve_chat_interface(site: str):#TODO! needs to be actual site
    """Serve the chat interface HTML page."""
    chat_interface_path = CHAT_BOT_DIR / "chat_interface.html"
    if not chat_interface_path.exists():
        raise HTTPException(status_code=404, detail="Chat interface not found")
    
    # Read the HTML template
    with open(chat_interface_path, "r") as f:
        html_content = f.read()
    
    # The site is already handled by JavaScript in the HTML
    # No need to modify the template
    
    return HTMLResponse(content=html_content)


@app.post("/chatbot/api/chats/")
async def handle_chat_message(request: Request, body: dict = Body(...)):
    """Handle chat messages and return responses with full message history."""
    message = body.get("message", "")
    site = body.get("site", "default")
    history = body.get("history", [])  # Get message history from request
    
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")
    
    # Validate history format
    if not isinstance(history, list):
        history = []
    
    # Ensure history contains valid message objects
    validated_history = []
    for msg in history:
        if isinstance(msg, dict) and "role" in msg and "content" in msg:
            validated_history.append({
                "role": msg["role"],
                "content": msg["content"]
            })
    
    # Check if the last message in history is already the current user message
    # (to avoid duplicates if frontend already added it)
    last_message_is_current = (
        validated_history and 
        validated_history[-1].get("role") == "user" and 
        validated_history[-1].get("content") == message
    )
    
    # Generate response with history (excluding the current message if it's already there)
    history_for_agent = validated_history[:-1] if last_message_is_current else validated_history
    chat_bot = ChatBot(site, history=history_for_agent)
    reply_text = await chat_bot.respond(message)
    
    return {"response": reply_text}


# Static file serving for chatbot assets
@app.get("/chatbot/assets/{file_path:path}")
async def serve_chatbot_asset(file_path: str):
    """Serve chatbot static assets (CSS, images, etc.)."""
    asset_path = CHAT_BOT_ASSETS_DIR / file_path
    
    # Prevent directory traversal
    try:
        asset_path.resolve().relative_to(CHAT_BOT_ASSETS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not asset_path.exists():
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Determine media type
    media_type = "application/octet-stream"
    if file_path.endswith(".css"):
        media_type = "text/css"
    elif file_path.endswith(".js"):
        media_type = "application/javascript"
    elif file_path.endswith(".png"):
        media_type = "image/png"
    elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
        media_type = "image/jpeg"
    elif file_path.endswith(".gif"):
        media_type = "image/gif"
    elif file_path.endswith(".svg"):
        media_type = "image/svg+xml"
    
    return FileResponse(
        asset_path,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=86400"}
    )


@app.get("/site/{site_path:path}")
async def serve_site(site_path: str):
    """
    Serve a site from the sites/ directory.
    
    Args:
        site_path: The site identifier (e.g., 'www.bigthunderevents.com')
                   Can include subdirectories if needed (e.g., 'www.example.com/subdir')
    
    Returns:
        The index.html file from the corresponding site directory.
    """
    # Normalize the path to prevent directory traversal attacks
    # Remove any leading/trailing slashes and normalize
    site_path = site_path.strip("/")
    
    # Prevent directory traversal
    if ".." in site_path or site_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid site path")
    
    # Construct the path to the site directory
    site_dir = SITES_DIR / site_path
    
    # Check if the directory exists
    if not site_dir.exists() or not site_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"Site '{site_path}' not found in sites directory"
        )
    
    # Look for index.html in the site directory
    index_file = site_dir / "index.html"
    
    if not index_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"index.html not found for site '{site_path}'"
        )
    
    # Read the HTML file
    with open(index_file, "r", encoding="utf-8", errors="ignore") as f:
        html_content = f.read()
    
    # Escape site_path for use in HTML attribute
    escaped_site_path = html.escape(site_path, quote=True)
    
    # Inject chatbot script before </body>
    chatbot_script = f'''
    <!-- SiteSlayer Chatbot Widget -->
    <script src="/chatbot/widget.js" data-id="{escaped_site_path}" data-position="right"></script>
</body>'''
    
    if "</body>" in html_content:
        html_content = html_content.replace("</body>", chatbot_script)
    else:
        html_content += chatbot_script
    
    # Return the modified HTML
    return HTMLResponse(
        content=html_content,
        headers={"Cache-Control": "no-cache"}
    )


@app.get("/raw/{site_path:path}")
async def serve_raw_file(site_path: str):
    """
    Serve raw files (like email.txt) from site directories.
    
    Args:
        site_path: The site identifier and filename (e.g., 'www.bigthunderevents.com/email.txt')
    
    Returns:
        The raw file content as plain text.
    """
    # Normalize the path to prevent directory traversal attacks
    site_path = site_path.strip("/")
    
    # Prevent directory traversal
    if ".." in site_path or site_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid site path")
    
    # Split the path into site directory and filename
    parts = site_path.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=400, detail="Invalid file path format")
    
    site_name, filename = parts
    
    # Construct the path to the file
    file_path = SITES_DIR / site_name / filename
    
    # Prevent directory traversal
    try:
        file_path.resolve().relative_to(SITES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    # Determine media type
    media_type = "text/plain"
    if filename.endswith(".txt"):
        media_type = "text/plain"
    elif filename.endswith(".md"):
        media_type = "text/markdown"
    elif filename.endswith(".html"):
        media_type = "text/html"
    
    return FileResponse(
        file_path,
        media_type=media_type,
        headers={"Cache-Control": "no-cache"}
    )


@app.get("/")
async def root():
    """Root endpoint listing all available websites."""
    # Track which sites we've processed from sites_to_scrape.txt
    processed_sites = set()
    links_html = ""
    
    # First, process sites from sites_to_scrape.txt
    if SITES_TO_SCRAPE_FILE.exists():
        with open(SITES_TO_SCRAPE_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                # Remove comments (everything after #)
                if '#' in line:
                    line = line[:line.index('#')]
                url = line.strip()
                # Skip empty lines
                if not url:
                    continue
                
                # Ensure URL has proper scheme for sanitize_domain
                if not url.startswith(('http://', 'https://')):
                    url = f"https://{url}"
                
                sanitized = sanitize_domain(url)
                processed_sites.add(sanitized)
                
                # Check if this site exists in the sites directory
                site_dir = SITES_DIR / sanitized
                if site_dir.exists() and site_dir.is_dir():
                    # Site exists - use same link rules as before
                    index_file = site_dir / "index.html"
                    has_index = index_file.exists()
                    error_file = site_dir / "error.txt"
                    has_error = error_file.exists()
                    email_file = site_dir / "email.txt"
                    has_email = email_file.exists()
                    
                    escaped_site_name = html.escape(sanitized, quote=True)
                    
                    # If site has error.txt, don't link to the site, just show the name
                    if has_error:
                        site_display = sanitized
                        error_link = f' <a href="/raw/{escaped_site_name}/error.txt">(error.txt)</a>'
                        links_html += f'    <li>{site_display}{error_link}</li>\n'
                    else:
                        # Normal site with index.html
                        site_display = f'<a href="/site/{escaped_site_name}">{sanitized}</a>'
                        email_link = ""
                        if has_email:
                            email_link = f' <a href="/raw/{escaped_site_name}/email.txt">(email.txt)</a>'
                        links_html += f'    <li>{site_display}{email_link}</li>\n'
                else:
                    # Site doesn't exist - show with MISSING
                    escaped_site_name = html.escape(sanitized, quote=True)
                    links_html += f'    <li>{escaped_site_name} <strong style="font-size: 1.2em;">MISSING</strong></li>\n'
    
    # Now, find all sites in the directory that are NOT in sites_to_scrape.txt
    unlisted_sites = []
    if SITES_DIR.exists() and SITES_DIR.is_dir():
        for item in SITES_DIR.iterdir():
            if item.is_dir():
                site_name = item.name
                # Skip if we already processed this site
                if site_name in processed_sites:
                    continue
                
                # Check if it has an index.html file or error.txt
                index_file = item / "index.html"
                has_index = index_file.exists()
                error_file = item / "error.txt"
                has_error = error_file.exists()
                
                # Include sites that have either index.html or error.txt
                if has_index or has_error:
                    email_file = item / "email.txt"
                    has_email = email_file.exists()
                    unlisted_sites.append((site_name, has_index, has_error, has_email))
    
    # Sort unlisted sites alphabetically
    unlisted_sites.sort(key=lambda x: x[0])
    
    # Add unlisted sites with UNLISTED label
    for site_name, has_index, has_error, has_email in unlisted_sites:
        escaped_site_name = html.escape(site_name, quote=True)
        
        # If site has error.txt, don't link to the site, just show the name
        if has_error:
            site_display = site_name
            error_link = f' <a href="/raw/{escaped_site_name}/error.txt">(error.txt)</a>'
            links_html += f'    <li>{site_display}{error_link} <strong style="font-size: 1.2em;">UNLISTED</strong></li>\n'
        else:
            # Normal site with index.html
            site_display = f'<a href="/site/{escaped_site_name}">{site_name}</a>'
            email_link = ""
            if has_email:
                email_link = f' <a href="/raw/{escaped_site_name}/email.txt">(email.txt)</a>'
            links_html += f'    <li>{site_display}{email_link} <strong style="font-size: 1.2em;">UNLISTED</strong></li>\n'
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>SiteSlayer - Available Websites</title>
</head>
<body>
    <h1>Available Websites</h1>
    <ul>
{links_html}    </ul>
</body>
</html>"""
    
    return HTMLResponse(content=html_content)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

