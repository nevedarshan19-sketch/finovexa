import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User
from .services.business_context import BUSINESS_HEADER, bind_business

PBKDF2_ITERATIONS = 390_000
_bearer = HTTPBearer(auto_error=False)

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("ascii"), PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, email: str) -> tuple[str, int]:
    expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expires_at = datetime.now(timezone.utc) + expires_delta
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)
    return token, int(expires_delta.total_seconds())


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise jwt.InvalidTokenError("wrong token type")
        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    try:
        user_id = int(payload.get("sub", ""))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid session.") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account is unavailable.")
    if user.role == "employee":
        owner = db.get(User, user.owner_id) if user.owner_id else None
        if owner is None or not owner.is_active:
            raise HTTPException(status_code=401, detail="Business account is unavailable.")
    return user


async def get_current_owner(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if user.role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Owner access required. Employee accounts must use the employee portal.",
        )
    bind_business(db, user, request.headers.get(BUSINESS_HEADER))
    return user


async def get_current_employee(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if user.role != "employee":
        raise HTTPException(status_code=403, detail="Employee portal access required.")
    if user.owner_id is None:
        raise HTTPException(status_code=403, detail="Employee account is not linked to a business.")
    bind_business(db, user, request.headers.get(BUSINESS_HEADER))
    return user


def get_current_developer(user: User = Depends(get_current_user)) -> User:
    if user.role != "developer":
        raise HTTPException(status_code=403, detail="Developer console access required.")
    return user


ACCOUNTANT_ROLES = ("senior_accountant", "junior_accountant")


def get_current_accountant(user: User = Depends(get_current_user)) -> User:
    if user.role not in ACCOUNTANT_ROLES:
        raise HTTPException(status_code=403, detail="Accountant portal access required.")
    return user


def get_current_senior_accountant(user: User = Depends(get_current_user)) -> User:
    if user.role != "senior_accountant":
        raise HTTPException(
            status_code=403,
            detail="Senior accountant access required for this action.",
        )
    return user


def get_current_junior_accountant(user: User = Depends(get_current_user)) -> User:
    if user.role != "junior_accountant":
        raise HTTPException(
            status_code=403,
            detail="Junior accountant workspace access required.",
        )
    return user


def get_current_customer(user: User = Depends(get_current_user)) -> User:
    if user.role != "customer":
        raise HTTPException(status_code=403, detail="Customer portal access required.")
    return user


class SlidingWindowLimiter:
    """In-process limiter suitable for a single node. Use Redis in multi-node deployments."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])))
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many requests. Try again in {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )
            bucket.append(now)


limiter = SlidingWindowLimiter()


def rate_limit(scope: str, limit: int, window_seconds: int):
    def dependency(request: Request) -> None:
        client = request.client.host if request.client else "unknown"
        limiter.check(f"{scope}:{client}", limit, window_seconds)

    return dependency
