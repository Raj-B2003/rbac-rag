# RBAC RAG API

Authentication-backed RAG API with:

- JWT authentication
- server-derived employee/manager roles
- document-level RBAC before retrieval
- ChromaDB dense retrieval
- BM25 keyword retrieval
- Reciprocal Rank Fusion (RRF)
- Qwen2.5:3b via Ollama
- Docker Compose

## Project structure

```text
rbac-rag/
├── api/
│   ├── __init__.py
│   ├── auth.py
│   ├── rag_core.py
│   ├── main.py
│   └── ingest_once.py
├── docs/
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Documents

Put these five PDFs in `docs/`:

- `employee_handbook.pdf`
- `onboarding_guide.pdf`
- `leave_policy.pdf`
- `benefits.pdf`
- `salary_bands.pdf`

Only managers can retrieve `salary_bands.pdf`.

## 1. Create the environment file

PowerShell:

```powershell
Copy-Item .env.example .env
```

Generate a secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Put the generated value into `.env`:

```text
JWT_SECRET=YOUR_GENERATED_SECRET
```

## 2. Start Docker Compose

From the project root:

```powershell
docker compose up --build -d
```

Check:

```powershell
docker compose ps
```

You should have `rbac-rag-api` and `rbac-rag-ollama` running.

## 3. Pull Qwen into Ollama

```powershell
docker compose exec ollama ollama pull qwen2.5:3b
```

## 4. Ingest the PDFs

```powershell
docker compose exec api python -m api.ingest_once
```

Expected:

```text
Ingested N chunks.
```

## 5. Check the API

Health:

```powershell
curl.exe http://localhost:8000/health
```

Interactive API docs:

```text
http://localhost:8000/docs
```

## 6. Login

Employee:

```powershell
curl.exe -X POST http://localhost:8000/login `
  -H "Content-Type: application/json" `
  -d '{"username":"employee","password":"employee123"}'
```

Manager:

```powershell
curl.exe -X POST http://localhost:8000/login `
  -H "Content-Type: application/json" `
  -d '{"username":"manager","password":"manager123"}'
```

Copy the returned `access_token`.

## 7. Test normal RAG

Replace `EMPLOYEE_TOKEN`:

```powershell
curl.exe -X POST http://localhost:8000/ask `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer EMPLOYEE_TOKEN" `
  -d '{"question":"What is the resignation notice period?"}'
```

## 8. Test RBAC

Employee asks for salary bands:

```powershell
curl.exe -X POST http://localhost:8000/ask `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer EMPLOYEE_TOKEN" `
  -d '{"question":"What is the L4 salary band?"}'
```

The employee retrieval layer excludes manager-only chunks.

Manager asks the same question:

```powershell
curl.exe -X POST http://localhost:8000/ask `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer MANAGER_TOKEN" `
  -d '{"question":"What is the L4 salary band?"}'
```

The manager can retrieve the salary-band document.

## 9. Test manager-only ingestion

Manager token:

```powershell
curl.exe -X POST http://localhost:8000/admin/ingest `
  -H "Authorization: Bearer MANAGER_TOKEN"
```

Employee token must return HTTP 403:

```powershell
curl.exe -X POST http://localhost:8000/admin/ingest `
  -H "Authorization: Bearer EMPLOYEE_TOKEN"
```

## Security boundary

The `/ask` request contains only the question. The client does not submit a role.

The server:

1. verifies the signed JWT
2. reads the server-issued role
3. applies RBAC filtering inside dense and BM25 retrieval
4. fuses only authorized results
5. sends the resulting context to Ollama

The demo uses an in-memory user store. For production, replace it with a proper identity provider and durable user/role storage.

## Stop

```powershell
docker compose down
```

To also remove persistent model/vector-store data:

```powershell
docker compose down -v
```
