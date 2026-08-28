FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY api/ /app/api/
COPY docs/ /app/docs/

RUN test -f /app/api/__init__.py
RUN python -m py_compile /app/api/rag_core.py /app/api/main.py /app/api/auth.py /app/api/ingest_once.py

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
