from fastapi import HTTPException, Header
from jose import jwt, JWTError
import os

SECRET_KEY = os.getenv("SECRET_KEY", "supersecretkey123")
ALGORITHM = "HS256"


def get_current_user(authorization: str = Header(...)):
    """
    Extract and decode the JWT from the Authorization header.
    Header format: "Bearer <token>"
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header format")

    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def require_employee(authorization: str = Header(...)):
    """Only employees can write to warehouse data."""
    user = get_current_user(authorization)
    if user.get("role") != "employee":
        raise HTTPException(
            status_code=403,
            detail="Access denied: employee role required"
        )
    return user
