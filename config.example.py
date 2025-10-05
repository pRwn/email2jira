"""
Configuration file for Email to JIRA Ticket Converter
COPY THIS FILE TO config.py AND SET YOUR ACTUAL VALUES
Set these values via environment variables for security
"""

import os

# ============================================================================
# MICROSOFT GRAPH API CONFIGURATION
# ============================================================================

TENANT_ID = os.getenv('TENANT_ID', 'your-tenant-id')
CLIENT_ID = os.getenv('CLIENT_ID', 'your-client-id')
CLIENT_SECRET = os.getenv('CLIENT_SECRET', 'your-client-secret')
MAILBOX_USER = os.getenv('MAILBOX_USER', 'user@domain.com')
MAILBOX_PASSWORD = os.getenv('MAILBOX_PASSWORD', 'mailbox-password')

# ============================================================================
# JIRA CONFIGURATION
# ============================================================================

JIRA_URL = os.getenv('JIRA_URL', 'https://your-company.atlassian.net')
JIRA_USER = os.getenv('JIRA_USER', 'jira-user@domain.com')
JIRA_PASSWORD = os.getenv('JIRA_PASSWORD', 'jira-password')
JIRA_PROJECT_KEY = os.getenv('JIRA_PROJECT_KEY', 'IAM')

# ============================================================================
# PROCESSING CONFIGURATION
# ============================================================================

FOLDER_NAME = os.getenv('FOLDER_NAME', '#As_JIRA_Ticket')
BATCH_SIZE = int(os.getenv('BATCH_SIZE', '10'))  # Max emails per run
