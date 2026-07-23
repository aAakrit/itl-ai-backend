from jose import jwt
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import uuid

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"

ACCESS_TOKEN_EXPIRE_HOURS = 24


def create_token(user_id: int):

    jti = str(uuid.uuid4())

    payload = {
        "sub": str(user_id),
        "jti": jti,
        "exp": datetime.utcnow() + timedelta(
            hours=ACCESS_TOKEN_EXPIRE_HOURS
        ),
    }

    token = jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM,
    )

    return token, jti