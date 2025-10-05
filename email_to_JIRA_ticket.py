#!/usr/bin/env python3
"""
Email to JIRA Ticket Converter
Processes emails from Exchange Online and creates JIRA tickets
Uses MSAL with ROPC (Resource Owner Password Credentials) flow
"""

import os
import logging
from datetime import datetime
from typing import List, Dict, Any
import requests
from jira import JIRA
from jinja2 import Template
import base64
import msal

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
# CONFIGURATION - Set these via environment variables or update here
# ============================================================================

# Microsoft Graph API Configuration
TENANT_ID = os.getenv('TENANT_ID', 'your-tenant-id')
CLIENT_ID = os.getenv('CLIENT_ID', 'your-client-id')
CLIENT_SECRET = os.getenv('CLIENT_SECRET', 'your-client-secret')
MAILBOX_USER = os.getenv('MAILBOX_USER', 'user@domain.com')
MAILBOX_PASSWORD = os.getenv('MAILBOX_PASSWORD', 'mailbox-password')

# JIRA Configuration
JIRA_URL = os.getenv('JIRA_URL', 'https://your-company.atlassian.net')
JIRA_USER = os.getenv('JIRA_USER', 'jira-user@domain.com')
JIRA_PASSWORD = os.getenv('JIRA_PASSWORD', 'jira-password')
JIRA_PROJECT_KEY = 'IAM'

# Processing Configuration
FOLDER_NAME = '#As_JIRA_Ticket'
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '10'))  # Max emails per run

# ============================================================================
# EMAIL TEMPLATE
# ============================================================================

EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            background-color: #f4f4f4;
        }
        .container {
            background-color: white;
            padding: 30px;
            margin: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .header {
            background: linear-gradient(135deg, #0052CC 0%, #0747A6 100%);
            color: white;
            padding: 20px;
            border-radius: 8px 8px 0 0;
            margin: -30px -30px 20px -30px;
        }
        .ticket-box {
            background-color: #f8f9fa;
            border-left: 4px solid #0052CC;
            padding: 15px;
            margin: 20px 0;
            border-radius: 4px;
        }
        .ticket-id {
            font-size: 24px;
            font-weight: bold;
            color: #0052CC;
            margin: 10px 0;
        }
        .info-box {
            background-color: #E3FCEF;
            border: 1px solid #00875A;
            padding: 15px;
            border-radius: 4px;
            margin: 20px 0;
        }
        .footer {
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            font-size: 12px;
            color: #666;
        }
        a {
            color: #0052CC;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0;">✓ Request Confirmed</h1>
        </div>
        
        <p>Dear {{ sender_name }},</p>
        
        <p>Thank you for your request. Your email has been successfully converted into a JIRA ticket for tracking and processing.</p>
        
        <div class="ticket-box">
            <div>Your Ticket ID:</div>
            <div class="ticket-id">{{ ticket_key }}</div>
            <div style="margin-top: 10px;">
                <strong>Summary:</strong> {{ ticket_summary }}
            </div>
        </div>
        
        <div class="info-box">
            <strong>📌 Important:</strong> Please use the JIRA ticket for all further communication regarding this request. 
            Do not reply to this email.
        </div>
        
        <p>You can view and update your ticket here:<br>
        <a href="{{ ticket_url }}" style="font-weight: bold;">{{ ticket_url }}</a></p>
        
        <p>Our team will review your request and provide updates in the ticket.</p>
        
        <div class="footer">
            <p>This is an automated message from the IAM Team.<br>
            Generated on {{ timestamp }}</p>
        </div>
    </div>
</body>
</html>
"""


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


class JiraTicketCreator:
    """Handles JIRA ticket creation and management"""
    
    def __init__(self, jira_url: str, username: str, password: str):
        self.jira = JIRA(server=jira_url, basic_auth=(username, password))
        logger.info("Connected to JIRA successfully")
    
    def create_ticket(self, summary: str, description: str, project_key: str = 'IAM') -> Any:
        """Create a JIRA ticket"""
        issue_dict = {
            'project': {'key': project_key},
            'summary': summary[:255],  # Limit summary length
            'description': description,
            'issuetype': {'name': 'Task'}
        }
        
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


def extract_email_body(email_message: Dict) -> str:
    """Extract plain text body from email message"""
    body = email_message.get('body', {})
    content = body.get('content', '')
    content_type = body.get('contentType', 'text')
    
    # JIRA supports some HTML, but let's keep it clean
    if content_type == 'html':
        # For better HTML parsing, you could use BeautifulSoup
        # For now, return as-is
        return content
    
    return content


def process_email_to_jira(graph_client: GraphAPIClient, jira_client: JiraTicketCreator, 
                          email_message: Dict):
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
        
        # Extract body
        body = extract_email_body(email_message)
        
        # Prepare description with metadata
        description = f"""*Original Email from:* {sender_name} <{sender_email}>
*Received:* {received_date}
*Subject:* {subject}

----

{body}
"""
        
        # Create JIRA ticket
        jira_issue = jira_client.create_ticket(
            summary=subject,
            description=description,
            project_key=JIRA_PROJECT_KEY
        )
        
        # Get and attach files
        if email_message.get('hasAttachments'):
            attachments = graph_client.get_attachments(message_id)
            for attachment in attachments:
                if attachment.get('@odata.type') == '#microsoft.graph.fileAttachment':
                    filename = attachment['name']
                    content_bytes = base64.b64decode(attachment['contentBytes'])
                    jira_client.add_attachment(jira_issue.key, filename, content_bytes)
        
        # Send confirmation email
        template = Template(EMAIL_TEMPLATE)
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
        
        # Delete the processed email from the folder
        graph_client.delete_message(message_id)
        
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
        
        # Get folder ID
        folder_id = graph_client.get_folder_id(FOLDER_NAME)
        if not folder_id:
            logger.error(f"Could not find folder '{FOLDER_NAME}'")
            return
        
        # Get messages
        messages = graph_client.get_messages_from_folder(folder_id, BATCH_SIZE)
        
        if not messages:
            logger.info("No messages to process")
            return
        
        # Process each message
        success_count = 0
        for message in messages:
            if process_email_to_jira(graph_client, jira_client, message):
                success_count += 1
        
        logger.info(f"Processed {success_count}/{len(messages)} emails successfully")
        
    except Exception as e:
        logger.error(f"Fatal error in main execution: {e}", exc_info=True)
        raise
    
    logger.info("Email to JIRA Converter finished")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
