import os
import time

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

SECRET_KEY = os.getenv("JWT_SECRET", "change-this-secret-before-deployment")
ALGORITHM = "HS256"
TOKEN_EXPIRY_SECONDS = 3600

USERS = {
    "employee": {
        "password": "employee123",
        "role": "employee",
    },
    "manager": {
        "password": "manager123",
        "role": "manager",
    },
}

security = HTTPBearer(auto_error=True)


def authenticate(username: str, password: str) -> dict:
    user = USERS.get(username)

    if user is None or user["password"] != password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    return {
        "username": username,
        "role": user["role"],
    }


def create_token(username: str, role: str) -> str:
    payload = {
        "sub": username,
        "role": role,
        "exp": int(time.time()) + TOKEN_EXPIRY_SECONDS,
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc

    username = payload.get("sub")
    role = payload.get("role")

    if username not in USERS or role not in {"employee", "manager"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )

    # Re-check the server-side role associated with the user.
    if USERS[username]["role"] != role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid role",
        )

    return {
        "username": username,
        "role": role,
    }


def require_manager(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manager access required",
        )

    return user
