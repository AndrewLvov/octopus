"""Gmail API data provider for fetching digest emails."""

import os
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import base64
from bs4 import BeautifulSoup

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the token.json file
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


class GmailDigestProvider:
    """Provider for fetching digest emails from Gmail API."""

    def __init__(self, credentials_path: str, token_path: str):
        """
        Initialize the Gmail provider.

        Args:
            credentials_path: Path to client_secret.json file
            token_path: Path to store/load token.json
        """
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.service = None

    def authenticate(self) -> None:
        """Authenticate with Gmail API using OAuth 2.0."""
        creds = None

        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)

            # Save the credentials for the next run
            with open(self.token_path, 'w') as token:
                token.write(creds.to_json())

        self.service = build('gmail', 'v1', credentials=creds)

    def get_digest_emails(
        self,
        days: int = 7,
        max_results: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get digest emails from the AI label.

        Args:
            days: Number of days to look back
            max_results: Maximum number of emails to return

        Returns:
            List of message metadata
        """
        if not self.service:
            self.authenticate()

        try:
            # Query for emails with AI or tech label from last N days
            query = f'(label:AI OR label:tech) newer_than:{days}d'
            response = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()

            messages = response.get('messages', [])
            return messages

        except HttpError as error:
            print(f'Error fetching digest emails: {error}')
            return []

    def get_message_details(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Get full details of an email message.

        Args:
            message_id: Gmail message ID

        Returns:
            Message details including content
        """
        if not self.service:
            self.authenticate()

        try:
            message = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            return message

        except HttpError as error:
            print(f'Error fetching message {message_id}: {error}')
            return None

    def get_message_content(self, message: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract text and HTML content from a message.

        Args:
            message: Gmail message resource

        Returns:
            Dict with 'text' and 'html' content
        """
        content = {'text': '', 'html': ''}

        if 'payload' not in message:
            return content

        parts = [message['payload']]
        while parts:
            part = parts.pop()

            if 'parts' in part:
                parts.extend(part['parts'])
            elif 'body' in part and 'data' in part['body']:
                data = base64.urlsafe_b64decode(
                    part['body']['data'].encode('UTF-8')
                ).decode('UTF-8')

                mime_type = part['mimeType']
                if mime_type == 'text/plain':
                    content['text'] = data
                elif mime_type == 'text/html':
                    content['html'] = data

        # If we have HTML but no text, extract text from HTML
        if content['html'] and not content['text']:
            soup = BeautifulSoup(content['html'], 'html.parser')
            content['text'] = soup.get_text(separator=' ', strip=True)

        return content

    def extract_links_from_content(
        self,
        content: Dict[str, str]
    ) -> List[Dict[str, str]]:
        """
        Extract links and their context from email content.

        Args:
            content: Dict with 'text' and 'html' content

        Returns:
            List of dicts with 'url', 'title', and 'context'
        """
        links = []
        if content['html']:
            soup = BeautifulSoup(content['html'], 'html.parser')
            for a in soup.find_all('a', href=True):
                url = a['href']
                # Get link text as title
                title = a.get_text(strip=True)
                # Get surrounding text (parent paragraph or div)
                parent = a.find_parent(['p', 'div'])
                context = parent.get_text(strip=True) if parent else title
                
                if url and title:  # Only include links with text
                    links.append({
                        'url': url,
                        'title': title,
                        'context': context
                    })

        return links

    def parse_message_metadata(
        self,
        message: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Parse message metadata from headers.

        Args:
            message: Gmail message resource

        Returns:
            Dict with sender, subject, and received_at
        """
        headers = message.get('payload', {}).get('headers', [])
        
        # Get sender
        from_header = next(
            (h['value'] for h in headers if h['name'].lower() == 'from'),
            'Unknown'
        )
        
        # Get subject
        subject = next(
            (h['value'] for h in headers if h['name'].lower() == 'subject'),
            'No Subject'
        )
        
        # Get date
        date_header = next(
            (h['value'] for h in headers if h['name'].lower() == 'date'),
            None
        )

        if date_header:
            # Parse the email date header
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_header)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            received_at = dt
        else:
            # Fallback to internal date
            internal_date = int(message.get('internalDate', '0')) / 1000
            received_at = datetime.fromtimestamp(internal_date, tz=timezone.utc)

        return {
            'sender': from_header,
            'subject': subject,
            'received_at': received_at
        }
