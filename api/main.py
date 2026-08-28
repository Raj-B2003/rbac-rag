from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import rag_core
from .auth import authenticate, create_token, get_current_user, require_manager

app = FastAPI(
    title="RBAC RAG API",
    version="1.0.0",
)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "documents": rag_core.get_collection().count(),
    }


@app.post("/login")
def login(request: LoginRequest):
    user = authenticate(request.username, request.password)
    token = create_token(user["username"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
    }


@app.post("/ask")
def ask_question(
    request: AskRequest,
    user: dict = Depends(get_current_user),
):
    try:
        answer, docs = rag_core.ask(request.question, user["role"])
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"RAG generation failed: {exc}",
        ) from exc

    return {
        "answer": answer,
        "role": user["role"],
        "sources": [
            doc["metadata"]["source"]
            for doc in docs
        ],
    }


@app.post("/admin/ingest")
def ingest_documents(
    _manager: dict = Depends(require_manager),
):
    count = rag_core.ingest()
    return {
        "status": "ok",
        "ingested_chunks": count,
    }
