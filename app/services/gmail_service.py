from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from app.db.models import SessionLocal, Contact, Message, Thread
from dotenv import load_dotenv
from datetime import datetime
import base64
import email
import os
import json

load_dotenv()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly"
]


def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def parse_email_body(payload):
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                data = part["body"].get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    break
    else:
        data = payload["body"].get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return body[:2000]


def get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def ingest_emails(max_results=50):
    service = get_gmail_service()
    db: Session = SessionLocal()

    try:
        results = service.users().messages().list(
            userId="me",
            maxResults=max_results,
            labelIds=["INBOX"]
        ).execute()

        messages = results.get("messages", [])
        ingested = 0

        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="full"
            ).execute()

            headers = msg["payload"]["headers"]
            msg_id = msg["id"]
            thread_id = msg["threadId"]
            subject = get_header(headers, "subject") or "(no subject)"
            sender = get_header(headers, "from")
            recipient = get_header(headers, "to")
            date_str = get_header(headers, "date")
            body = parse_email_body(msg["payload"])

            # Parse sender email
            sender_email = sender
            sender_name = ""
            if "<" in sender:
                sender_name = sender.split("<")[0].strip().strip('"')
                sender_email = sender.split("<")[1].replace(">", "").strip()

            # Determine direction
            me = service.users().getProfile(userId="me").execute()["emailAddress"]
            direction = "outbound" if sender_email.lower() == me.lower() else "inbound"
            contact_email = recipient if direction == "outbound" else sender_email
            contact_name = sender_name if direction == "inbound" else ""

            # Parse timestamp
            try:
                timestamp = datetime.fromtimestamp(int(msg["internalDate"]) / 1000)
            except:
                timestamp = datetime.now()

            # Upsert contact
            contact = db.query(Contact).filter_by(email=contact_email).first()
            if not contact:
                contact = Contact(
                    id=contact_email.replace("@", "_").replace(".", "_"),
                    email=contact_email,
                    name=contact_name
                )
                db.add(contact)

            if direction == "inbound":
                contact.last_received = timestamp
            else:
                contact.last_contacted = timestamp

            # Skip if message already exists
            existing = db.query(Message).filter_by(id=msg_id).first()
            if existing:
                continue

            # Create message
            message = Message(
                id=msg_id,
                contact_id=contact.id,
                thread_id=thread_id,
                subject=subject,
                body=body,
                direction=direction,
                timestamp=timestamp,
                is_read="UNREAD" not in msg.get("labelIds", []),
                needs_reply=direction == "inbound"
            )
            db.add(message)

            # Upsert thread
            thread = db.query(Thread).filter_by(id=thread_id).first()
            if not thread:
                thread = Thread(
                    id=thread_id,
                    subject=subject,
                    contact_id=contact.id,
                    last_message_at=timestamp,
                    awaiting_reply=direction == "inbound"
                )
                db.add(thread)
            else:
                thread.last_message_at = timestamp
                thread.awaiting_reply = direction == "inbound"

            ingested += 1

        db.commit()
        print(f"Ingested {ingested} new messages.")
        return ingested

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    ingest_emails(max_results=50)