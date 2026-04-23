from sqlalchemy import create_engine, Column, String, Text, DateTime, Boolean, Integer, Float, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.sql import func
from dotenv import load_dotenv
import os

load_dotenv()

Base = declarative_base()
engine = create_engine(os.getenv("DATABASE_URL"))
SessionLocal = sessionmaker(bind=engine)


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String)
    company = Column(String)
    role = Column(String)
    first_seen = Column(DateTime, server_default=func.now())
    last_contacted = Column(DateTime)
    last_received = Column(DateTime)
    relationship_strength = Column(Float, default=0.0)
    notes = Column(Text)

    messages = relationship("Message", back_populates="contact")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    contact_id = Column(String, ForeignKey("contacts.id"))
    thread_id = Column(String)
    subject = Column(String)
    body = Column(Text)
    direction = Column(String)  # 'inbound' or 'outbound'
    timestamp = Column(DateTime)
    is_read = Column(Boolean, default=False)
    needs_reply = Column(Boolean, default=False)
    urgency_score = Column(Float, default=0.0)
    source = Column(String, default="gmail")

    contact = relationship("Contact", back_populates="messages")


class Thread(Base):
    __tablename__ = "threads"

    id = Column(String, primary_key=True)
    subject = Column(String)
    contact_id = Column(String, ForeignKey("contacts.id"))
    last_message_at = Column(DateTime)
    last_reply_at = Column(DateTime)
    awaiting_reply = Column(Boolean, default=False)
    days_waiting = Column(Integer, default=0)
    summary = Column(Text)


class Insight(Base):
    __tablename__ = "insights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(String)  # 'pattern', 'alert', 'relationship', 'priority'
    title = Column(String)
    body = Column(Text)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    is_read = Column(Boolean, default=False)
    priority = Column(Integer, default=0)


class DraftResponse(Base):
    __tablename__ = "draft_responses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String, ForeignKey("messages.id"))
    thread_id = Column(String)
    draft_body = Column(Text)
    tone = Column(String)
    created_at = Column(DateTime, server_default=func.now())
    approved = Column(Boolean, default=False)
    sent = Column(Boolean, default=False)


def init_db():
    Base.metadata.create_all(engine)
    print("Database tables created.")


if __name__ == "__main__":
    init_db()