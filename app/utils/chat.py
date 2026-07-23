from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.chat import ChatService

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_chat_service(
    db: Session = Depends(get_db),
) -> ChatService:
    return ChatService(db)