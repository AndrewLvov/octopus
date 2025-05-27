# Octopus

Application for collecting and analyzing AI-related news and articles from various sources.

## Setup

1. Install dependencies:
```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client beautifulsoup4
```

2. Configure Gmail API:

a. Go to [Google Cloud Console](https://console.cloud.google.com/)
b. Create a new project or select existing one
c. Enable Gmail API for your project
d. Create OAuth 2.0 credentials:
   - Go to "Credentials" page
   - Click "Create Credentials" > "OAuth client ID"
   - Select "Desktop app"
   - Download the client configuration file as `client_secret.json`
   - Place it in a secure location

3. Update `.env` file with Gmail paths:
```
GMAIL_CREDENTIALS_PATH=/path/to/client_secret.json
GMAIL_TOKEN_PATH=/path/to/store/token.json
```

4. Run database migrations:
```bash
alembic upgrade head
```

## Usage

### Processing Email Digests

The application can process AI-related digest emails:

1. In Gmail, create a label called "AI"
2. Apply this label to newsletters and digests about AI
3. Run the email processor:
```bash
python -m octopus.scripts.process_digest_emails
```

This will:
- Fetch emails with the "AI" label
- Extract links and their context
- Create stories from these links
- Process them through the standard pipeline (summaries, tags, entities)

### Other Features

[Previous documentation...]
