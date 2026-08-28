import hashlib
import os
import re

import chromadb
import requests
from pypdf import PdfReader
from rank_bm25 import BM25Okapi


DOCS_PATH = os.getenv("DOCS_PATH", "./docs")
DB_PATH = os.getenv("DB_PATH", "./chroma_db")

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://ollama:11434",
).rstrip("/")

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen2.5:3b",
)

EMBEDDING_MODEL = "nomic-embed-text"
COLLECTION_NAME = "rbac_docs"
RRF_K = 60
DEFAULT_TOP_K = 5

ROLE_MAP = {
    "employee_handbook.pdf": {"employee", "manager"},
    "onboarding_guide.pdf": {"employee", "manager"},
    "leave_policy.pdf": {"employee", "manager"},
    "benefits.pdf": {"employee", "manager"},
    "salary_bands.pdf": {"manager"},
}


# ============================================================
# CHROMA
# ============================================================

client = chromadb.PersistentClient(path=DB_PATH)


def get_collection():
    """Always retrieve the current collection by name."""
    return client.get_or_create_collection(name=COLLECTION_NAME)


# ============================================================
# OLLAMA EMBEDDINGS
# ============================================================

def embed_texts(texts):
    """Generate embeddings through Ollama's /api/embed endpoint."""
    if not texts:
        return []

    response = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={
            "model": EMBEDDING_MODEL,
            "input": texts,
        },
        timeout=180,
    )
    response.raise_for_status()

    data = response.json()
    embeddings = data.get("embeddings")

    if not embeddings:
        raise RuntimeError(f"Ollama returned no embeddings: {data}")

    return embeddings


def embed_query(query):
    embeddings = embed_texts([query])
    if not embeddings:
        raise RuntimeError("No embedding returned for query")
    return embeddings[0]


# ============================================================
# BM25 CACHE
# ============================================================

_bm25 = None
_bm25_data = None


def invalidate_bm25_cache():
    global _bm25, _bm25_data
    _bm25 = None
    _bm25_data = None


# ============================================================
# PDF / TEXT
# ============================================================

def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_text(text, max_chars=900):
    text = clean_text(text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    chunks = []
    current = ""

    for line in lines:
        candidate = line if not current else f"{current}\n{line}"

        if current and len(candidate) > max_chars:
            chunks.append(current.strip())
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current.strip())

    return chunks


def load_pdf(path):
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ============================================================
# INGESTION
# ============================================================

def ingest():
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = get_collection()
    total = 0

    for filename, allowed_roles in ROLE_MAP.items():
        path = os.path.join(DOCS_PATH, filename)

        if not os.path.isfile(path):
            print(f"WARNING: missing {filename}")
            continue

        text = load_pdf(path)
        chunks = split_text(text)

        if not chunks:
            print(f"WARNING: no text in {filename}")
            continue

        embeddings = embed_texts(chunks)
        ids = []
        documents = []
        metadatas = []

        for index, chunk in enumerate(chunks):
            chunk_id = hashlib.sha256(
                f"{filename}:{index}:{chunk}".encode("utf-8")
            ).hexdigest()

            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "source": filename,
                "role_employee": "employee" in allowed_roles,
                "role_manager": "manager" in allowed_roles,
            })

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        total += len(chunks)
        print(filename, ":", len(chunks), "chunks")

    invalidate_bm25_cache()
    print("TOTAL CHUNKS:", total)
    return total


# ============================================================
# BM25
# ============================================================

def _get_bm25():
    global _bm25, _bm25_data

    if _bm25 is not None:
        return _bm25, _bm25_data

    collection = get_collection()
    data = collection.get(include=["documents", "metadatas"])
    documents = data.get("documents", [])
    tokenized = [document.lower().split() for document in documents]

    _bm25 = BM25Okapi(tokenized) if tokenized else None
    _bm25_data = data
    return _bm25, _bm25_data


# ============================================================
# DENSE SEARCH
# ============================================================

def dense_search(query, role, k=DEFAULT_TOP_K):
    if role not in {"employee", "manager"}:
        raise ValueError("Invalid role")

    collection = get_collection()
    count = collection.count()

    if count == 0:
        return []

    query_embedding = embed_query(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(k * 2, count),
        where={f"role_{role}": True},
    )

    ids = results.get("ids")
    return ids[0] if ids else []


# ============================================================
# BM25 SEARCH
# ============================================================

def bm25_search(query, role, k=DEFAULT_TOP_K):
    if role not in {"employee", "manager"}:
        raise ValueError("Invalid role")

    bm25, data = _get_bm25()
    if bm25 is None:
        return []

    role_field = f"role_{role}"
    scores = bm25.get_scores(query.lower().split())
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    results = []

    for index in ranked:
        metadata = data["metadatas"][index] or {}
        if metadata.get(role_field, False):
            results.append(data["ids"][index])
        if len(results) >= k * 2:
            break

    return results


# ============================================================
# HYBRID RRF
# ============================================================

def hybrid_search(query, role, k=DEFAULT_TOP_K):
    dense_ids = dense_search(query, role, k)
    bm25_ids = bm25_search(query, role, k)
    scores = {}

    for rank, doc_id in enumerate(dense_ids):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    for rank, doc_id in enumerate(bm25_ids):
        scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (RRF_K + rank + 1)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return [doc_id for doc_id, _ in ranked[:k]]


# ============================================================
# DOCUMENTS
# ============================================================

def get_documents(ids):
    if not ids:
        return []

    collection = get_collection()
    data = collection.get(ids=ids, include=["documents", "metadatas"])

    return [
        {
            "id": data["ids"][index],
            "document": data["documents"][index],
            "metadata": data["metadatas"][index],
        }
        for index in range(len(data["ids"]))
    ]


# ============================================================
# QWEN GENERATION
# ============================================================

def generate_answer(query, docs):
    if not docs:
        return "The information is not available in the accessible documents."

    context = "\n\n".join(
        f"[Source: {doc['metadata']['source']}]\n{doc['document']}"
        for doc in docs
    )

    prompt = f"""
You are a company document assistant.

Use ONLY the supplied context.

Rules:
- Do not use outside knowledge.
- Do not invent facts.
- If the answer is not in the context, say:
  "The information is not available in the accessible documents."
- Give a concise answer.
- Do not reveal restricted information.

Context:
{context}

Question:
{query}

Answer:
""".strip()

    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        },
        timeout=180,
    )
    response.raise_for_status()

    answer = response.json().get("response", "").strip()

    if not answer:
        return "The information is not available in the accessible documents."

    return answer


# ============================================================
# PUBLIC RAG
# ============================================================

def ask(query, role):
    if role not in {"employee", "manager"}:
        raise ValueError("Invalid role")

    ids = hybrid_search(
        query=query,
        role=role,
        k=DEFAULT_TOP_K,
    )

    docs = get_documents(ids)
    answer = generate_answer(query, docs)
    return answer, docs
