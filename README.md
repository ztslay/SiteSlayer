# SiteSlayer

SiteSlayer is a web scraping and site replication tool that automatically scrapes websites, generates email content, and serves mock versions of scraped pages with an embedded AI chatbot.

## Quick Start (For Users)

### Prerequisites

1. **Install Fly.io CLI**
   
   Fly.io is used to deploy the web server. Install it by following the instructions at: https://fly.io/docs/getting-started/installing-flyctl/

2. **Get Fly.io API Token**
   
   You'll need a Fly.io API token for deployment:
   
   1. Log in to the [Fly.io Dashboard](https://fly.io/dashboard)
   2. Navigate to the "Tokens" section in the left-hand menu
   3. Click "Create token"
   4. Provide a descriptive name for your token (e.g., "SiteSlayer Deployment")
   5. Optionally set an expiration period
   6. Click "Create"
   7. Copy the generated token immediately (it's only shown once)
   
   **Important**: Treat your API token like a password. Do not share it publicly or commit it to version control.

3. **Get OpenAI API Key**
   
   You'll need an OpenAI API key for the AI-powered features (link ranking and chatbot):
   
   1. Sign up or log in at https://platform.openai.com/
   2. Navigate to API Keys section
   3. Create a new API key
   4. Copy the API key immediately (you may not be able to see it again)

### Initial Setup

You need to configure these API keys in two places:

#### Why Each Key is Needed

- **GitHub Actions needs `OPENAI_API_KEY`**: Used during the scraping workflow to rank URLs (determining which links to prioritize when crawling) and to generate email content based on the scraped website data.
- **GitHub Actions needs `FLY_API_TOKEN`**: Required to authenticate and deploy your application to Fly.io when changes are pushed.
- **Fly.io needs `OPENAI_API_KEY`**: Your deployed application uses this key to power the chat engine that runs on the scraped pages.

#### How to Set Up the Keys

**For GitHub Actions**:
Both `OPENAI_API_KEY` and `FLY_API_TOKEN` need to be added as GitHub Secrets:

1. Go to your GitHub repository settings
2. Navigate to Secrets and variables → Actions
3. Click "New repository secret"
4. Add each secret:
   - **For `OPENAI_API_KEY`**:
     - Name: `OPENAI_API_KEY`
     - Value: Your OpenAI API key
     - Click "Add secret"
   - **For `FLY_API_TOKEN`**:
     - Name: `FLY_API_TOKEN`
     - Value: Your Fly.io API token
     - Click "Add secret"

These secrets are used by GitHub Actions workflows and are accessed via `${{ secrets.SECRET_NAME }}`

**For Fly.io Application**:
You also need to set `OPENAI_API_KEY` as a secret in your Fly.io app so the chat engine can access it:

1. Authenticate: `flyctl auth login`
2. Navigate to your project directory
3. Set the secret:
   ```bash
   flyctl secrets set OPENAI_API_KEY=your_openai_api_key
   ```
   Replace `your_openai_api_key` with your actual OpenAI API key
4. The secret will be available as an environment variable in your deployed app

**Note**: You only need to set `OPENAI_API_KEY` in Fly.io. The `FLY_API_TOKEN` is only used by GitHub Actions for deployment.

### Using SiteSlayer

Once the setup is complete, you can use SiteSlayer entirely through GitHub:

#### 1. Edit `sites_to_scrape.txt`

To add or remove websites to scrape:

1. Navigate to your GitHub repository
2. Open the `sites_to_scrape.txt` file
3. Click the pencil icon (✏️) to edit the file
4. Add URLs (one per line) or remove existing ones
5. Add comments by starting a line with `#`
6. Click "Commit changes" at the bottom
7. Add a commit message (e.g., "Add new site to scrape")
8. Click "Commit changes" to save

#### 2. Watch the Scraper Run

After committing changes to `sites_to_scrape.txt`:

1. The scraper workflow will automatically trigger
2. Go to the **Actions** tab in your GitHub repository
3. You'll see a workflow run in progress
4. The scraper will:
   - Remove directories for URLs that are no longer in the file
   - Scrape new websites for newly added URLs
   - Update existing site data if needed
5. You can watch the progress in real-time by clicking on the workflow run

#### 3. Understanding the Scraped Content

After the scraper completes, each URL's domain will have its own directory in the `sites/` folder with the following files:

- **`index.html`**: The scraped homepage HTML with updated absolute links to styles, images, and other assets so the page displays correctly
- **`content.md`**: All text content scraped from the homepage and surrounding pages (up to 15 pages total)
- **`urls.txt`**: A list of all URLs that were scraped for this site
- **`email.txt`**: The generated email text for the site (only present if scraping was successful)
- **`error.txt`**: Error information if something went wrong during scraping or email generation (only present if there was an error)

#### 4. Deployment to Fly.io

After the scraper workflow completes:

1. The file changes in the `sites/` directory will automatically trigger the Fly.io deployment workflow
2. You can monitor this deployment in the **Actions** tab as well
3. Look for a workflow run related to deployment (it will run after the scraper completes)
4. Once the deployment workflow completes successfully, your website will be live at: **https://slaydigital.fly.dev/**

#### 5. Viewing Your Scraped Sites

Visit **https://slaydigital.fly.dev/** to:

- See a list of all scraped sites (displayed in the same order as `sites_to_scrape.txt`)
- Click on any site to view the mocked website with the embedded chat widget
- View the generated `email.txt` content for each site (if scraping was successful)
- See `error.txt` content if a site failed to scrape properly

Each mocked site page includes an AI-powered chatbot that can answer questions based on the scraped content from that site.

## Development Setup (For Contributors)

If you want to modify or contribute to SiteSlayer, you'll need additional development tools:

### Prerequisites

1. **Install Git**
   
   Git is used for version control. If you don't have it installed:
   - **macOS**: `brew install git` or download from https://git-scm.com/download/mac
   - **Linux**: `sudo apt-get install git` (Ubuntu/Debian) or use your distribution's package manager
   - **Windows**: Download from https://git-scm.com/download/win

2. **Install uv**
   
   uv is the Python package manager used by this project. Install it by following the instructions at: https://github.com/astral-sh/uv

3. **Install Fly.io CLI**
   
   If you haven't already installed it (see Quick Start), install it from: https://fly.io/docs/getting-started/installing-flyctl/

### Local Development

1. Clone the repository
2. Install dependencies using `uv`
3. Run the scraper locally to test changes
4. Run the web server locally for testing
5. Make your changes and test before deploying

## How It Works

### Main Components

**URL Scraper** (`web_scraper/`)
- Crawls websites and extracts HTML content
- Converts pages to markdown format
- Uses AI to rank and prioritize important links
- Stores scraped content in the `sites/` directory

**Web Server** (`website_server/`)
- Serves mock versions of the scraped webpages
- Displays the home page showing all sites from `sites_to_scrape.txt`
- Shows generated emails for each site
- Embeds a chatbot widget on each page

**Chat Bot** (`website_server/chat_bot/`)
- AI-powered chatbot that uses the scraped content
- Provides interactive chat experience on scraped pages
- Answers questions based on the content from each site

**Email Generator** (`web_scraper/email_writer.py`)
- Generates email content based on scraped website data
- Creates personalized email templates for each site

## File Structure

- `sites_to_scrape.txt` - List of URLs to scrape (one per line, comments with `#`)
- `sites/` - Directory containing scraped content for each site
- `web_scraper/` - Scraping and content extraction logic
- `website_server/` - FastAPI server for serving scraped pages
- `scripts/deploy_server.sh` - Deployment script

## Customization

All components are editable and modifiable. The system is designed to be as simple as possible while remaining flexible:

- Modify scraping behavior in `web_scraper/`
- Customize the web server in `website_server/main.py`
- Adjust chatbot behavior in `website_server/agent.py`
- Update email generation in `web_scraper/email_writer.py`

## Notes

- The scraper automatically runs via GitHub Actions when `sites_to_scrape.txt` is modified
- The web server deploys automatically when other files are pushed to the main branch
- Scraped content is stored locally in the `sites/` directory, organized by domain name

