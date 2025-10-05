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

                    # Replace img tag with placeholder or remove
                    img.replace_with(f"[Embedded Image: {filename}]")

                    logger.info(f"Extracted embedded base64 image: {filename}")

            except Exception as e:
                logger.error(f"Error extracting base64 image: {e}")

        # Handle CID (Content-ID) referenced images
        elif src.startswith('cid:'):
            # CID images need to be matched with actual attachments
            # We'll just note them here - they should be in the message attachments
            cid = src.replace('cid:', '')
            logger.info(f"Found CID referenced image: {cid} (should be in attachments)")
            # Replace with placeholder
            img.replace_with(f"[Image: {cid}]")

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
