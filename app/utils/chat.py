from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.chat import ChatService


def get_chat_service(
    db: Session = Depends(get_db),
) -> ChatService:
    return ChatService(db)