from .rag_core import ingest

if __name__ == "__main__":
    count = ingest()
    print(f"Ingested {count} chunks.")
