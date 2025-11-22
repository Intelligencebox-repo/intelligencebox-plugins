import base64
import html
import mimetypes
import os
import re
from typing import Literal, Optional, List

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pydantic import BaseModel, Field

from .google_api import GoogleAuthManager, AuthError


class EmailMessage(BaseModel):
    msg_id: str = Field(..., description='The ID of the email message')
    subject: str = Field(..., description='The subject of the email message')
    sender: str = Field(..., description='The sender of the email message')
    recipient: str = Field(..., description='The recipient of the email message')
    body: str = Field(..., description='The body of the email message')
    snippet: str = Field(..., description='A snippet of the email message')
    has_attachments: bool = Field(..., description='Indicates if the email has attachments')
    date: str = Field(..., description='The date the email was sent')
    star: bool = Field(..., description='Indicates if the email is starred')
    label: str = Field(..., description='Labels associated with the email message')

class EmailMessages(BaseModel):
    count: int = Field(..., description='Total number of email messages')
    messages: List[EmailMessage] = Field(..., description='List of email messages')
    next_page_token: Optional[str] = Field(None, description='Token for the next page of results')

class GmailTools:
    API_NAME = 'gmail'
    API_VERSION = 'v1'
    SCOPES = ['https://mail.google.com/']

    def __init__(self) -> None:
        """All'avvio, crea un'istanza del gestore di autenticazione."""
        self.auth_manager = GoogleAuthManager(scopes=self.SCOPES)

    # --- Metodi per l'Autenticazione Guidata ---
    def is_authenticated(self) -> bool:
        """Metodo che verifica se l'utente è già autenticato."""
        return self.auth_manager.is_authenticated()
    
    def start_authentication(self) -> str:
        """Chiama il gestore di autenticazione per ottenere l'URL di consenso."""
        return self.auth_manager.start_authentication_flow()

    def complete_authentication(self, code: str) -> None:
        """Passa il codice al gestore di autenticazione per completare il processo."""
        self.auth_manager.complete_authentication_flow(code)

    def logout(self) -> str:
        """Chiama il gestore di autenticazione per eliminare il token."""
        return self.auth_manager.logout()

    # --- Metodi per l'Interazione con Gmail ---
    def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        body_type: Literal['plain', 'html'] = 'html',
        attachment_paths: Optional[List[str]] = None,
        attachments: Optional[List[dict]] = None
    ) -> dict:
        """
        Sends an email.

        Args:
            to (str): Recipient email address.
            subject (str): Subject of the email.
            body (str): Body of the email.
            body_type (Literal['plain', 'html'], optional): Type of the email body. Defaults to 'plain'.
            attachment_paths (Optional[List[str]], optional): List of file paths to attach. Defaults to None.
            attachments (Optional[List[dict]], optional): List of attachments provided as base64 payloads with filename and optional mime_type.
                Each element should be a dict with keys 'filename', 'content_base64', and optional 'mime_type'.

        Returns:
            dict: Response from the Gmail API.
        """
        service = self.auth_manager.get_service(self.API_NAME, self.API_VERSION)
        try:
            normalized_body_type = 'html'

            message = MIMEMultipart()
            message['to'] = to
            message['subject'] = subject
            signature = os.getenv("GMAIL_EMAIL_SIGNATURE", "")

            body_content = body if body_type.lower() == 'html' else self._convert_plain_to_html(body)
            body_with_signature = self._apply_signature(body_content, 'html', signature)
            message.attach(MIMEText(body_with_signature, normalized_body_type))

            if attachments:
                error = self._attach_base64_payloads(message, attachments)
                if error:
                    return error

            if attachment_paths:
                error = self._attach_files_from_paths(message, attachment_paths)
                if error:
                    return error

            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            response = service.users().messages().send(userId='me', body={'raw': raw_message}).execute()

            return {'msg_id': response['id'], 'status': 'success'}
    
        except Exception as e:
            return {'error': f'An error occurred: {str(e)}', 'status': 'failed'}

    def _apply_signature(self, body: str, body_type: str, signature: str) -> str:
        if not signature or not signature.strip():
            return body

        if body_type.lower() == 'html':
            return f"{body}<br><br>{signature}"
        if self._contains_html(signature):
            signature = self._strip_html(signature)
        return f"{body}\n\n{signature}"

    def _contains_html(self, content: str) -> bool:
        return bool(re.search(r'<[^>]+>', content))

    def _strip_html(self, content: str) -> str:
        text = re.sub(r'<[^>]+>', '', content)
        return html.unescape(text).strip()

    def _convert_plain_to_html(self, content: str) -> str:
        escaped = html.escape(content)
        return escaped.replace("\n", "<br>")

    def _build_attachment_part(self, content: bytes, mime_type: Optional[str], filename: str) -> MIMEBase:
        maintype, subtype = ('application', 'octet-stream')
        if mime_type and '/' in mime_type:
            maintype, subtype = mime_type.split('/', 1)

        part = MIMEBase(maintype, subtype)
        part.set_payload(content)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', f'attachment; filename={filename}')
        return part

    def _attach_base64_payloads(self, message: MIMEMultipart, attachments: List[dict]) -> Optional[dict]:
        for attachment in attachments:
            filename = attachment.get('filename')
            content_base64 = attachment.get('content_base64')
            mime_type = attachment.get('mime_type')

            if not filename or not content_base64:
                return {'error': 'Each attachment must include filename and content_base64.', 'status': 'failed'}

            try:
                content_bytes = base64.b64decode(content_base64)
            except Exception as decode_err:
                return {'error': f'Invalid base64 content for attachment {filename}: {decode_err}', 'status': 'failed'}

            message.attach(self._build_attachment_part(content_bytes, mime_type, filename))

        return None

    def _attach_files_from_paths(self, message: MIMEMultipart, attachment_paths: List[str]) -> Optional[dict]:
        for attachment_path in attachment_paths:
            if not os.path.exists(attachment_path):
                return {'error': f'Attachment file {attachment_path} not found.', 'status': 'failed'}

            filename = os.path.basename(attachment_path)
            with open(attachment_path, 'rb') as attachment:
                content_bytes = attachment.read()

            mime_type, _ = mimetypes.guess_type(attachment_path)
            message.attach(self._build_attachment_part(content_bytes, mime_type, filename))

        return None
        
    def search_emails(self, query: Optional[str] = None, label: Literal['ALL', 'INBOX', 'SENT', 'DRAFT', 'SPAM', 'TRASH' ] = 'INBOX', max_results: Optional[int] = 10, next_page_token: Optional[str] = None):
        """
        Searches for emails based on the provided criteria.

        Args:
            query (Optional[str], optional): Search query string. Defaults to None, wich returns all emails.
            label (Literal['ALL', 'INBOX', 'SENT', 'DRAFT', 'SPAM', 'TRASH' ], optional): Email label to filter by. Defaults to 'INBOX'.
            max_results (Optional[int], optional): Maximum number of results to return. Defaults is 10. Max is 500.

        """
        service = self.auth_manager.get_service(self.API_NAME, self.API_VERSION)
        messages = []
        next_page_token_ = next_page_token
        label_ = [label] if label != 'ALL' else None

        while True:
            result = service.users().messages().list(
                userId='me',
                q=query,
                labelIds=label_,
                maxResults=min(500, max_results - len(messages)) if max_results else 500,
                pageToken=next_page_token_
            ).execute()

            messages.extend(result.get('messages', []))
            next_page_token_ = result.get('nextPageToken')
            if not next_page_token_ or (max_results and len(messages) >= max_results):
                break

        # compile emails details
        email_messages = []
        for message_ in messages:
            msg_id = message_['id']
            msg_details = self.get_email_message_details(msg_id)
            email_messages.append(msg_details)
        email_messages_ = email_messages[:max_results] if max_results else email_messages

        return EmailMessages(count=len(email_messages_), messages=email_messages_, next_page_token=next_page_token_)
    
    def get_email_message_details(self, msg_id: str) -> EmailMessage:
        """
        Retrieves detailed information about a specific email message.

        Args:
            msg_id (str): The ID of the email message.

        Returns:
            EmailMessage: Detailed information about the email message.
        """
        service = self.auth_manager.get_service(self.API_NAME, self.API_VERSION)
        try:
            message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            payload = message.get('payload', {})
            headers = payload.get('headers', [])

            header_map = {header['name'].lower(): header['value'] for header in headers}
            
            subject = header_map.get('subject', 'No Subject')
            sender = header_map.get('from', 'No Sender')
            recipients = header_map.get('to', 'No Recipient')
            date = header_map.get('date', 'No Date')

            snippet = message.get('snippet', 'No Snippet')
            has_attachments = any(part.get('filename') for part in payload.get('parts', []) if part.get('filename'))
            star = 'STARRED' in message.get('labelIds', [])
            label = ','.join(message.get('labelIds', []))

            return EmailMessage(
                msg_id=msg_id,
                subject=subject,
                sender=sender,
                recipient=recipients,
                body='<not included>',
                snippet=snippet,
                has_attachments=has_attachments,
                date=date,
                star=star,
                label=label
            )
        except Exception as e:
            print(f'An error occurred while fetching email details: {str(e)}')
            return None
        
    def get_emails_message_body(self, msg_id: str) -> str:
        """
        Retrieves the body content of a specific email message.

        Args:
            msg_id (str): The ID of the email message.

        Returns:
            str: The body content of the email message.
        """
        service = self.auth_manager.get_service(self.API_NAME, self.API_VERSION)
        try:
            message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            return self._extract_body(message.get('payload', {}))
        except Exception as e:
            print(f'An error occurred while fetching email body: {str(e)}')
            return '<Error Fetching Body>'

    def _extract_body(self, payload: dict) -> str:
        """
        Recursively extracts the body content from the email payload.

        Args:
            payload (dict): The email payload.

        Returns:
            str: The extracted body content.
        """
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain' and 'data' in part.get('body', {}):
                    return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                # Aggiunge una ricerca ricorsiva per formati più complessi
                if 'parts' in part:
                    body = self._extract_body(part)
                    if body != '<Text body not available>':
                        return body
        elif 'data' in payload.get('body', {}):
            return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8')
        return '<Text body not available>'
    
    def delete_email_message(self, msg_id: str) -> dict:
        """
        Deletes a specific email message using its ID.

        Args:
            msg_id (str): The ID of the email message to delete.

        Returns:
            dict: Response from the Gmail API.
        """
        service = self.auth_manager.get_service(self.API_NAME, self.API_VERSION)
        try:
            service.users().messages().delete(userId='me', id=msg_id).execute()
            return {'status': 'success'}
        
        except Exception as e:
            return {'error': f'An error occurred: {str(e)}', 'status': 'failed'}
