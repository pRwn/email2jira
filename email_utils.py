"""
Email utilities for processing email bodies and extracting embedded content
"""

import re
import base64
import logging
from typing import List, Dict, Tuple
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def extract_embedded_images(html_body: str) -> Tuple[str, List[Dict[str, any]]]:
    """
    Extract embedded images from HTML email body

    Looks for:
    - Base64 encoded images in <img> tags (data:image/...)
    - CID (Content-ID) referenced images (cid:...)

    Args:
        html_body: HTML content of the email body

    Returns:
        Tuple of (cleaned_html, list of embedded objects)
        - cleaned_html: HTML with embedded images removed/replaced
        - embedded_objects: List of dicts with 'filename', 'content' (bytes), 'content_type'
    """
    if not html_body:
        return html_body, []

    embedded_objects = []
    soup = BeautifulSoup(html_body, 'html.parser')

    # Find all img tags
    img_tags = soup.find_all('img')

    for idx, img in enumerate(img_tags):
        src = img.get('src', '')

        # Handle base64 encoded images
        if src.startswith('data:image/'):
            try:
                # Extract content type and base64 data
                # Format: data:image/png;base64,iVBORw0KGgoAAAANS...
                match = re.match(r'data:image/([^;]+);base64,(.+)', src)
                if match:
                    image_type = match.group(1)
                    base64_data = match.group(2)

                    # Decode base64
                    image_bytes = base64.b64decode(base64_data)

                    # Generate filename
                    filename = f"embedded_image_{idx + 1}.{image_type}"

                    embedded_objects.append({
                        'filename': filename,
                        'content': image_bytes,
                        'content_type': f'image/{image_type}'
                    })

                    # Replace img tag with JIRA image syntax
                    img.replace_with(f"!{filename}|thumbnail!")

                    logger.info(f"Extracted embedded base64 image: {filename}")

            except Exception as e:
                logger.error(f"Error extracting base64 image: {e}")

        # Handle CID (Content-ID) referenced images
        elif src.startswith('cid:'):
            # CID images need to be matched with actual attachments
            # We'll just note them here - they should be in the message attachments
            cid = src.replace('cid:', '')
            logger.info(f"Found CID referenced image: {cid} (should be in attachments)")
            # Replace with JIRA image syntax - extract clean filename from CID
            # CID format is often like "image002.png@01DB1234.5678ABCD"
            clean_filename = cid.split('@')[0] if '@' in cid else cid
            img.replace_with(f"!{clean_filename}|thumbnail!")

    # Convert back to HTML string
    cleaned_html = str(soup)

    return cleaned_html, embedded_objects


def extract_embedded_objects_from_email(email_body: Dict) -> Tuple[str, List[Dict[str, any]]]:
    """
    Extract embedded objects from email body structure

    Args:
        email_body: Email body dict with 'content' and 'contentType'

    Returns:
        Tuple of (cleaned_content, list of embedded objects)
    """
    content = email_body.get('content', '')
    content_type = email_body.get('contentType', 'text')

    if content_type == 'html':
        return extract_embedded_images(content)

    # For plain text, no embedded objects
    return content, []


def convert_html_to_jira_markup(html_content: str) -> str:
    """
    Convert HTML content to JIRA markup format

    JIRA supports its own wiki-style markup language. This function converts
    common HTML elements to their JIRA equivalents.

    Args:
        html_content: HTML string to convert

    Returns:
        JIRA markup formatted string
    """
    if not html_content:
        return ''

    soup = BeautifulSoup(html_content, 'html.parser')

    # Convert common HTML tags to JIRA markup
    # Images (in case any weren't already converted)
    for img in soup.find_all('img'):
        src = img.get('src', '')
        alt = img.get('alt', '')

        # Extract filename from src
        if src:
            # Handle various URL formats
            if '/' in src:
                filename = src.split('/')[-1]
            else:
                filename = src

            # Clean up query params and fragments
            filename = filename.split('?')[0].split('#')[0]

            # Use alt text if available, otherwise use filename
            if alt:
                img.replace_with(f"!{filename}|alt={alt},thumbnail!")
            else:
                img.replace_with(f"!{filename}|thumbnail!")
        else:
            img.replace_with(alt if alt else '[Image]')

    # Headers
    for i in range(1, 7):
        for tag in soup.find_all(f'h{i}'):
            tag.replace_with(f'h{i}. {tag.get_text()}\n')

    # Bold
    for tag in soup.find_all(['b', 'strong']):
        tag.replace_with(f'*{tag.get_text()}*')

    # Italic
    for tag in soup.find_all(['i', 'em']):
        tag.replace_with(f'_{tag.get_text()}_')

    # Underline
    for tag in soup.find_all('u'):
        tag.replace_with(f'+{tag.get_text()}+')

    # Strikethrough
    for tag in soup.find_all(['s', 'strike', 'del']):
        tag.replace_with(f'-{tag.get_text()}-')

    # Links
    for tag in soup.find_all('a'):
        href = tag.get('href', '')
        text = tag.get_text()
        if href:
            tag.replace_with(f'[{text}|{href}]')
        else:
            tag.replace_with(text)

    # Unordered lists
    for ul in soup.find_all('ul'):
        items = []
        for li in ul.find_all('li', recursive=False):
            items.append(f'* {li.get_text().strip()}')
        ul.replace_with('\n' + '\n'.join(items) + '\n')

    # Ordered lists
    for ol in soup.find_all('ol'):
        items = []
        for idx, li in enumerate(ol.find_all('li', recursive=False), 1):
            items.append(f'# {li.get_text().strip()}')
        ol.replace_with('\n' + '\n'.join(items) + '\n')

    # Code blocks
    for tag in soup.find_all('pre'):
        code_text = tag.get_text()
        tag.replace_with(f'{{code}}\n{code_text}\n{{code}}\n')

    # Inline code
    for tag in soup.find_all('code'):
        if tag.parent.name != 'pre':  # Skip if already inside pre
            tag.replace_with(f'{{{{{tag.get_text()}}}}}')

    # Blockquotes
    for tag in soup.find_all('blockquote'):
        lines = tag.get_text().strip().split('\n')
        quoted = '\n'.join([f'bq. {line}' for line in lines])
        tag.replace_with(f'\n{quoted}\n')

    # Line breaks
    for br in soup.find_all('br'):
        br.replace_with('\n')

    # Paragraphs
    for p in soup.find_all('p'):
        p.replace_with(f'\n{p.get_text()}\n')

    # Divs (just extract text with newlines)
    for div in soup.find_all('div'):
        div.replace_with(f'\n{div.get_text()}\n')

    # Extract text and clean up
    text = soup.get_text()

    # Clean up excessive newlines
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Clean up excessive spaces
    text = re.sub(r' {2,}', ' ', text)

    # Strip leading/trailing whitespace
    text = text.strip()

    return text
