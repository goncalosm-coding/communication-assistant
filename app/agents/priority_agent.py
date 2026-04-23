from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from app.db.models import SessionLocal, Message, Contact, Insight
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

llm = ChatOpenAI(model="gpt-4o", temperature=0)


def score_message(subject: str, body: str, sender: str, days_waiting: int) -> dict:
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are an expert communication assistant that analyses emails 
        and determines their urgency and required action.

        Given an email, return a JSON object with exactly these fields:
        {{
            "urgency_score": <float between 0 and 1>,
            "needs_reply": <true or false>,
            "urgency_reason": <one sentence explaining the urgency level>,
            "suggested_action": <one specific action to take>
        }}

        Urgency scoring guide:
        - 0.9 to 1.0: Immediate action required, time-sensitive, important sender
        - 0.7 to 0.8: Should reply today, clear question or request
        - 0.5 to 0.6: Should reply this week, informational but needs acknowledgment
        - 0.2 to 0.4: Low priority, newsletters, notifications, no reply needed
        - 0.0 to 0.1: Spam, promotions, automated emails

        Consider:
        - How many days the email has been waiting for a reply
        - Whether it contains a direct question or request
        - Whether it's from a known professional contact vs automated system
        - The tone and language of the subject and body

        Return only valid JSON. No explanation outside the JSON."""),
        ("human", """Sender: {sender}
        Subject: {subject}
        Days waiting: {days_waiting}
        Body preview: {body}""")
    ])

    chain = prompt | llm

    result = chain.invoke({
        "sender": sender,
        "subject": subject,
        "days_waiting": days_waiting,
        "body": body[:500]
    })

    import json
    try:
        content = result.content.strip()
        # Strip markdown code blocks if present
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        return json.loads(content.strip())
    
    except Exception as e:
        print(f"  Parse error: {e}")
        print(f"  Raw response: {result.content[:200]}")
        return {
            "urgency_score": 0.3,
            "needs_reply": False,
            "urgency_reason": "Could not parse response",
            "suggested_action": "Review manually"
        }


def run_priority_agent():
    db = SessionLocal()

    try:
        # Get unprocessed inbound messages from last 7 days
        since = datetime.now() - timedelta(days=7)
        messages = db.query(Message).filter(
            Message.direction == "inbound",
            Message.timestamp >= since,
            Message.urgency_score == 0.0
        ).order_by(Message.timestamp.desc()).limit(30).all()

        print(f"Scoring {len(messages)} messages...")

        scored = []
        for msg in messages:
            contact = db.query(Contact).filter_by(id=msg.contact_id).first()
            sender = contact.email if contact else "unknown"

            days_waiting = (datetime.now() - msg.timestamp).days

            result = score_message(
                subject=msg.subject,
                body=msg.body,
                sender=sender,
                days_waiting=days_waiting
            )

            msg.urgency_score = result["urgency_score"]
            msg.needs_reply = result["needs_reply"]
            scored.append((msg, result))

            print(f"  [{result['urgency_score']:.2f}] {msg.subject[:60]}")

        db.commit()

        # Surface top 5 as insights
        high_priority = sorted(scored, key=lambda x: x[1]["urgency_score"], reverse=True)[:5]

        for msg, result in high_priority:
            if result["urgency_score"] >= 0.6:
                insight = Insight(
                    type="priority",
                    title=f"Action needed: {msg.subject[:60]}",
                    body=f"{result['urgency_reason']} — {result['suggested_action']}",
                    contact_id=msg.contact_id,
                    priority=int(result["urgency_score"] * 10)
                )
                db.add(insight)

        db.commit()

        print(f"\nTop priority messages:")
        for msg, result in high_priority[:3]:
            if result["urgency_score"] >= 0.6:
                print(f"  {msg.subject[:50]}")
                print(f"  → {result['suggested_action']}")
                print()

        return scored

    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    run_priority_agent()