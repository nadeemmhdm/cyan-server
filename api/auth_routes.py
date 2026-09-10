from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from security.auth import authenticate, create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(req: LoginRequest):
    user = authenticate(req.username, req.password)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token = create_token(user)
    return {"access_token": token, "token_type": "bearer", "role": user.role}
