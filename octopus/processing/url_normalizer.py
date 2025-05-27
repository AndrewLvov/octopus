"""URL normalization utilities."""

import asyncio
from urllib.parse import urlparse, urlunparse
import re
from typing import Optional

from playwright.async_api import async_playwright
from playwright.async_api import TimeoutError, Error as PlaywrightError


async def get_final_url(url: str, timeout: int = 3) -> Optional[str]:
    """
    Follow redirects and get the final URL using Playwright.
    
    Args:
        url: Initial URL to follow
        timeout: Maximum time in seconds to wait for redirects
        
    Returns:
        Final URL after following redirects, or None if failed
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Go to URL and wait for navigation
            response = await page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            final_url = page.url
            
            await browser.close()
            return final_url if response and response.ok else None
            
    except TimeoutError as e:
        print(f"Error following redirects for {url}: {e}")
        return None
    except PlaywrightError as e:
        print(f"Playwright error for {url}: {e}")
        return None


async def normalize_url(url: str) -> str:
    """
    Normalize URL to a canonical form asynchronously.

    This helps with deduplication by handling common URL variations:
    - Follows redirects to get final URL
    - Removes www prefix
    - Removes trailing slashes
    - Sorts query parameters
    - Removes common tracking parameters
    - Converts to lowercase
    - Removes default ports (80, 443)

    Args:
        url: URL to normalize

    Returns:
        Normalized URL string
    """
    if not url:
        return url

    # Handle TLDR newsletter tracking URLs
    tldr_match = re.match(r'https://tracking\.tldrnewsletter\.com/CL0/(.+?)/', url)
    if tldr_match:
        # Extract and decode the embedded target URL
        target_url = tldr_match.group(1).replace('%2F', '/').replace('%3A', ':')
        if target_url.startswith('http'):
            url = target_url

    # Follow redirects to get final URL
    final_url = await get_final_url(url)
    if final_url:
        url = final_url

    # Parse URL
    parsed = urlparse(url)

    # Convert domain to lowercase (domains are case-insensitive)
    netloc = parsed.netloc.lower()
    # Keep original path case since paths can be case-sensitive
    path = parsed.path

    # Remove www.
    if netloc.startswith('www.'):
        netloc = netloc[4:]

    # Remove default ports
    if ':80' in netloc and parsed.scheme == 'http':
        netloc = netloc.replace(':80', '')
    if ':443' in netloc and parsed.scheme == 'https':
        netloc = netloc.replace(':443', '')

    # Remove trailing slashes from path
    while path.endswith('/'):
        path = path[:-1]
    if not path:
        path = '/'

    # Sort and filter query parameters
    if parsed.query:
        # Split into individual parameters
        params = parsed.query.split('&')
        
        # Remove common tracking parameters
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'fbclid', 'gclid', 'msclkid', '_hsenc', '_hsmi', 'mc_cid', 'mc_eid'
        }
        params = [p for p in params if not any(
            p.startswith(f"{t}=") for t in tracking_params
        )]
        
        # Sort parameters
        params.sort()
        query = '&'.join(params)
    else:
        query = ''

    # Reconstruct URL
    normalized = urlunparse((
        parsed.scheme,
        netloc,
        path,
        '',  # params
        query,
        ''  # fragment
    ))

    return normalized
