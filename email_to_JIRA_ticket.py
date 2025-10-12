#!/usr/bin/env python3
"""
Email to JIRA Ticket Converter
Processes emails from Exchange Online and creates JIRA tickets
Uses MSAL with ROPC (Resource Owner Password Credentials) flow
Admin Consent already given
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
import requests
from jira import JIRA
from jinja2 import Environment, FileSystemLoader
import base64
import msal
import os
import csv

# Import configuration
from config import (
    TENANT_ID, CLIENT_ID, CLIENT_SECRET,
    MAILBOX_USER, MAILBOX_PASSWORD,
    JIRA_URL, JIRA_USER, JIRA_PASSWORD, JIRA_PROJECT_KEY,
    FOLDER_NAME, FOLDER_NAME_ARCHIVE, BATCH_SIZE
)

# Import email utilities
from email_utils import extract_embedded_objects_from_email, convert_html_to_jira_markup

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('email_to_jira.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# JINJA2 TEMPLATE SETUP
# ============================================================================

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Set up Jinja2 environment to load templates from the script directory
jinja_env = Environment(loader=FileSystemLoader(SCRIPT_DIR))


class GraphAPIClient:
    """Handles Microsoft Graph API authentication and operations using MSAL"""
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, 
                 username: str, password: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self.access_token = None
        self.graph_endpoint = 'https://graph.microsoft.com/v1.0'
        
        # Initialize MSAL Confidential Client Application
        authority = f'https://login.microsoftonline.com/{tenant_id}'
        self.app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority
        )
    
    def get_access_token(self) -> str:
        """Obtain access token using ROPC (Resource Owner Password Credentials) flow"""
        scopes = ['https://graph.microsoft.com/.default']
        
        try:
            # Try ROPC flow
            result = self.app.acquire_token_by_username_password(
                username=self.username,
                password=self.password,
                scopes=scopes
            )
            
            if "access_token" in result:
                self.access_token = result['access_token']
                logger.info("Successfully obtained access token via ROPC")
                return self.access_token
            else:
                error = result.get("error")
                error_desc = result.get("error_description")
                logger.error(f"Failed to obtain token: {error} - {error_desc}")
                
                # If ROPC fails, try client credentials as fallback
                logger.info("Attempting client credentials flow as fallback...")
                result = self.app.acquire_token_for_client(scopes=scopes)
                
                if "access_token" in result:
                    self.access_token = result['access_token']
                    logger.info("Successfully obtained access token via client credentials")
                    return self.access_token
                else:
                    raise Exception(f"Authentication failed: {result.get('error_description')}")
                    
        except Exception as e:
            logger.error(f"Failed to obtain access token: {e}")
            raise
    
    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        if not self.access_token:
            self.get_access_token()
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_folder_id(self, folder_name: str) -> str:
        """Get the folder ID for a specific folder name"""
        # Using 'me' endpoint since we're authenticating as the user
        url = f'{self.graph_endpoint}/me/mailFolders'
        
        try:
            response = requests.get(url, headers=self._get_headers())
            response.raise_for_status()
            folders = response.json()['value']
            
            # Search in all folders including subfolders
            for folder in folders:
                if folder['displayName'] == folder_name:
                    logger.info(f"Found folder '{folder_name}' with ID: {folder['id']}")
                    return folder['id']
                
                # Check child folders
                child_url = f"{self.graph_endpoint}/me/mailFolders/{folder['id']}/childFolders"
                child_response = requests.get(child_url, headers=self._get_headers())
                if child_response.ok:
                    child_folders = child_response.json().get('value', [])
                    for child in child_folders:
                        if child['displayName'] == folder_name:
                            logger.info(f"Found folder '{folder_name}' with ID: {child['id']}")
                            return child['id']
            
            logger.error(f"Folder '{folder_name}' not found")
            return None
        except Exception as e:
            logger.error(f"Error getting folder ID: {e}")
            raise
    
    def get_messages_from_folder(self, folder_id: str, limit: int = 10) -> List[Dict]:
        """Retrieve messages from a specific folder"""
        url = f'{self.graph_endpoint}/me/mailFolders/{folder_id}/messages'
        params = {
            '$top': limit,
            '$orderby': 'receivedDateTime desc',
            '$select': 'id,subject,from,body,receivedDateTime,hasAttachments'
        }
        
        try:
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            messages = response.json()['value']
            logger.info(f"Retrieved {len(messages)} messages from folder")
            return messages
        except Exception as e:
            logger.error(f"Error retrieving messages: {e}")
            raise
    
    def get_attachments(self, message_id: str) -> List[Dict]:
        """Get all attachments from a message"""
        url = f'{self.graph_endpoint}/me/messages/{message_id}/attachments'
        
        try:
            response = requests.get(url, headers=self._get_headers())
            response.raise_for_status()
            attachments = response.json()['value']
            logger.info(f"Retrieved {len(attachments)} attachments for message {message_id}")
            return attachments
        except Exception as e:
            logger.error(f"Error retrieving attachments: {e}")
            return []
    
    def send_email(self, to_email: str, subject: str, html_body: str):
        """Send an email using Microsoft Graph API"""
        url = f'{self.graph_endpoint}/me/sendMail'
        
        message = {
            'message': {
                'subject': subject,
                'body': {
                    'contentType': 'HTML',
                    'content': html_body
                },
                'toRecipients': [
                    {
                        'emailAddress': {
                            'address': to_email
                        }
                    }
                ]
            },
            'saveToSentItems': 'true'
        }
        
        try:
            response = requests.post(url, headers=self._get_headers(), json=message)
            response.raise_for_status()
            logger.info(f"Email sent successfully to {to_email}")
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            raise
    
    def delete_message(self, message_id: str):
        """Delete a message (move to Deleted Items)"""
        url = f'{self.graph_endpoint}/me/messages/{message_id}'
        
        try:
            response = requests.delete(url, headers=self._get_headers())
            response.raise_for_status()
            logger.info(f"Message {message_id} deleted successfully")
        except Exception as e:
            logger.error(f"Error deleting message: {e}")
    
    def move_message(self, message_id: str, destination_folder_id: str):
        """Move a message to another folder"""
        url = f'{self.graph_endpoint}/me/messages/{message_id}/move'

        data = {
            'destinationId': destination_folder_id
        }

        try:
            response = requests.post(url, headers=self._get_headers(), json=data)
            response.raise_for_status()
            logger.info(f"Message {message_id} moved successfully")
        except Exception as e:
            logger.error(f"Error moving message: {e}")

    def _lookup_userid_in_cache(self, email: str, cache_file: str = 'email2userid.csv') -> Optional[str]:
        """
        Look up user ID in CSV cache file

        Args:
            email: Email address to lookup
            cache_file: Path to CSV cache file

        Returns:
            User ID if found in cache, None otherwise
        """
        cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), cache_file)

        if not os.path.exists(cache_path):
            logger.debug(f"Cache file not found: {cache_path}")
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f, quoting=csv.QUOTE_ALL)
                for row in reader:
                    # Strip any remaining quotes and whitespace from the values
                    email_from_csv = row.get('email', '').strip().strip('"').lower()
                    userid_from_csv = row.get('userid', '').strip().strip('"')

                    if email_from_csv == email.lower():
                        if userid_from_csv:
                            logger.info(f"Found userid '{userid_from_csv}' for email '{email}' in cache")
                            return userid_from_csv

            logger.debug(f"Email '{email}' not found in cache")
            return None

        except Exception as e:
            logger.warning(f"Error reading cache file: {e}")
            return None

    def get_userid_from_email(self, email: str) -> str:
        """
        Get user ID from email address, checking CSV cache first, then Graph API

        Args:
            email: Email address to lookup

        Returns:
            User ID (part before @ in userPrincipalName)

        Raises:
            Exception: If user not found or multiple users found
        """
        # First, try to get userid from CSV cache
        userid = self._lookup_userid_in_cache(email)
        if userid:
            return userid

        # If not in cache, query Graph API
        logger.info(f"Email '{email}' not in cache, querying Graph API...")
        url = f"{self.graph_endpoint}/users"
        params = {
            '$filter': f"mail eq '{email}'",
            '$select': 'userPrincipalName'
        }

        try:
            response = requests.get(url, headers=self._get_headers(), params=params)
            response.raise_for_status()
            users = response.json().get('value', [])

            if len(users) == 0:
                logger.error(f"No user found with email: {email}")
                raise Exception(f"No user found with email: {email}")

            if len(users) > 1:
                logger.error(f"Multiple users found with email: {email}")
                raise Exception(f"Multiple users found with email: {email}")

            # Extract user ID from userPrincipalName (part before @)
            user_principal_name = users[0].get('userPrincipalName', '')
            if '@' not in user_principal_name:
                logger.error(f"Invalid userPrincipalName format: {user_principal_name}")
                raise Exception(f"Invalid userPrincipalName format: {user_principal_name}")

            userid = user_principal_name.split('@')[0]
            logger.info(f"Successfully extracted userid '{userid}' from email '{email}' via Graph API")
            return userid

        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error getting user ID for {email}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error getting user ID for {email}: {e}")
            raise


class JiraTicketCreator:
    """Handles JIRA ticket creation and management"""
    
    def __init__(self, jira_url: str, username: str, password: str):
        self.jira = JIRA(server=jira_url, basic_auth=(username, password))
        logger.info("Connected to JIRA successfully")
    
    def create_ticket(self, summary: str, description: str, project_key: str = 'IAM', userid: str = None) -> Any:
        """Create a JIRA ticket"""
        issue_dict = {
            'project': {'key': project_key},
            'summary': summary[:255],  # Limit summary length
            'description': description,
            'issuetype': {'name': 'Task'}
        }

        # Add custom field for userid if provided
        if userid:
            issue_dict['customfield_12804'] = {'name': userid}
        
        try:
            issue = self.jira.create_issue(fields=issue_dict)
            logger.info(f"Created JIRA ticket: {issue.key}")
            return issue
        except Exception as e:
            logger.error(f"Error creating JIRA ticket: {e}")
            raise
    
    def add_attachment(self, issue_key: str, filename: str, file_content: bytes):
        """Add an attachment to a JIRA ticket"""
        try:
            # Create a file-like object from bytes
            from io import BytesIO
            file_obj = BytesIO(file_content)
            file_obj.name = filename
            
            self.jira.add_attachment(issue=issue_key, attachment=file_obj, filename=filename)
            logger.info(f"Added attachment {filename} to {issue_key}")
        except Exception as e:
            logger.error(f"Error adding attachment {filename}: {e}")


def extract_email_body(email_message: Dict) -> tuple[str, List[Dict]]:
    """
    Extract email body and any embedded objects

    Returns:
        Tuple of (body_content, embedded_objects)
    """
    body = email_message.get('body', {})

    # Extract embedded objects and get cleaned content
    cleaned_content, embedded_objects = extract_embedded_objects_from_email(body)

    return cleaned_content, embedded_objects


def process_email_to_jira(graph_client: GraphAPIClient, jira_client: JiraTicketCreator,
                          email_message: Dict, archive_folder_id: str):
    """Process a single email and create a JIRA ticket"""
    
    try:
        # Extract email details
        subject = email_message.get('subject', 'No Subject')
        sender = email_message['from']['emailAddress']
        sender_email = sender['address']
        sender_name = sender.get('name', sender_email)
        message_id = email_message['id']
        received_date = email_message.get('receivedDateTime', '')

        logger.info(f"Processing email from {sender_email}: {subject}")

        # Get user ID from email address
        try:
            userid = graph_client.get_userid_from_email(sender_email)
            logger.info(f"Retrieved userid: {userid} for email: {sender_email}")
        except Exception as e:
            logger.error(f"Failed to get userid for {sender_email}: {e}")
            # Continue processing even if userid lookup fails
            userid = None

        # Extract body and embedded objects
        body, embedded_objects = extract_email_body(email_message)

        # Convert HTML body to JIRA markup
        jira_body = convert_html_to_jira_markup(body)

        # Prepare description with metadata
        userid_info = f"\n*User ID:* {userid}" if userid else ""
        description = f"""*Original Email from:* {sender_name} <{sender_email}>{userid_info}
*Received:* {received_date}
*Subject:* {subject}

----

{jira_body}
"""

        # Create JIRA ticket
        jira_issue = jira_client.create_ticket(
            summary=subject,
            description=description,
            project_key=JIRA_PROJECT_KEY,
            userid=userid
        )

        # Add embedded objects as attachments
        if embedded_objects:
            for embedded_obj in embedded_objects:
                jira_client.add_attachment(
                    jira_issue.key,
                    embedded_obj['filename'],
                    embedded_obj['content']
                )

        # Get and attach files from email attachments
        if email_message.get('hasAttachments'):
            attachments = graph_client.get_attachments(message_id)
            for attachment in attachments:
                if attachment.get('@odata.type') == '#microsoft.graph.fileAttachment':
                    filename = attachment['name']
                    content_bytes = base64.b64decode(attachment['contentBytes'])
                    jira_client.add_attachment(jira_issue.key, filename, content_bytes)
        
        # Send confirmation email
        template = jinja_env.get_template('email_template.html')
        html_body = template.render(
            sender_name=sender_name,
            ticket_key=jira_issue.key,
            ticket_summary=subject,
            ticket_url=f"{JIRA_URL}/browse/{jira_issue.key}",
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
        
        graph_client.send_email(
            to_email=sender_email,
            subject=f"Your request has been converted to ticket {jira_issue.key}",
            html_body=html_body
        )

        # Move the processed email to archive folder (only if ticket creation was successful)
        graph_client.move_message(message_id, archive_folder_id)

        logger.info(f"Successfully processed email and created ticket {jira_issue.key}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing email {email_message.get('id')}: {e}", exc_info=True)
        return False


def main():
    """Main execution function"""
    logger.info("=" * 80)
    logger.info("Starting Email to JIRA Converter (MSAL ROPC)")
    logger.info("=" * 80)
    
    try:
        # Initialize clients
        graph_client = GraphAPIClient(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            username=MAILBOX_USER,
            password=MAILBOX_PASSWORD
        )
        
        jira_client = JiraTicketCreator(JIRA_URL, JIRA_USER, JIRA_PASSWORD)
        
        # Get folder IDs
        folder_id = graph_client.get_folder_id(FOLDER_NAME)
        if not folder_id:
            logger.error(f"Could not find folder '{FOLDER_NAME}'")
            return

        archive_folder_id = graph_client.get_folder_id(FOLDER_NAME_ARCHIVE)
        if not archive_folder_id:
            logger.error(f"Could not find archive folder '{FOLDER_NAME_ARCHIVE}'")
            return

        # Get messages
        messages = graph_client.get_messages_from_folder(folder_id, BATCH_SIZE)

        if not messages:
            logger.info("No messages to process")
            return

        # Process each message
        success_count = 0
        for message in messages:
            if process_email_to_jira(graph_client, jira_client, message, archive_folder_id):
                success_count += 1
        
        logger.info(f"Processed {success_count}/{len(messages)} emails successfully")
        
    except Exception as e:
        logger.error(f"Fatal error in main execution: {e}", exc_info=True)
        raise
    
    logger.info("Email to JIRA Converter finished")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
