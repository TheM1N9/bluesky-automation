# Alma AI (Bluesky Newsletter Bot)

A bot that automatically generates and posts content to Bluesky from newsletters and web research.

## Features

- **Newsletter Processing**: Automatically processes email newsletters and creates thread drafts
- **Web Research**: Generates content from web searches on specified topics
- **Draft Management**: Review and edit drafts before posting
- **Auto-Posting**: Optional automatic posting of generated content
- **Auto-Reply**: Intelligent responses to mentions and replies
- **Source Tracking**: Maintains references to original sources (newsletters/web pages)

## Setup

1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Set up environment variables:
```bash
BLUESKY_HANDLE=your_handle
BLUESKY_PASSWORD=your_password
GMAIL_CLIENT_ID=your_client_id
GMAIL_CLIENT_SECRET=your_client_secret
MONGO_URL=your_mongodb_url
SECRET_KEY=your_secret_key
```

## Usage

1. Start the server:
```bash
uvicorn main:app --reload
```

2. Access the dashboard at `http://localhost:8000`

3. Configure your:
   - Bluesky credentials
   - Topics of interest
   - Auto-posting preferences
   - Email newsletter settings

##issues
- need to fix the web search agent and make it more accurate
