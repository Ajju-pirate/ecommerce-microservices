from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from .database import get_db, create_tables, User
from .auth import hash_password, verify_password, create_access_token, decode_token

app = FastAPI(title="User Service", version="1.0.0")


@app.on_event("startup")
def startup():
    create_tables()


# ── Pydantic schemas (what the API accepts / returns) ──────────────────────

class UserCreate(BaseModel):
    username: str
    password: str
    role: Optional[str] = "customer"   # "customer" or "employee"


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True
        model_config = {"from_attributes": True}


class TokenVerifyRequest(BaseModel):
    token: str


# ── Routes ─────────────────────────────────────────────────────────────────

@app.post("/register", response_model=UserOut, status_code=201)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """Register a new user. Role can be 'customer' or 'employee'."""
    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already taken")

    new_user = User(
        username=user_data.username,
        hashed_password=hash_password(user_data.password),
        role=user_data.role
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Login endpoint. Returns a JWT token.
    Uses OAuth2PasswordRequestForm so it's compatible with Swagger UI's 'Authorize' button.
    """
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password"
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Account is disabled")

    token = create_access_token({"sub": user.username, "role": user.role, "user_id": user.id})
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@app.post("/verify-token")
def verify_token(request: TokenVerifyRequest):
    """
    Called by the API Gateway to validate a token.
    Returns the decoded payload (username, role) if valid.
    """
    try:
        payload = decode_token(request.token)
        return {
            "valid": True,
            "username": payload.get("sub"),
            "role": payload.get("role"),
            "user_id": payload.get("user_id")
        }
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@app.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    """List all users — employee-only in production, open here for dev."""
    return db.query(User).all()


@app.get("/health")
def health():
    return {"status": "ok", "service": "user_service"}
