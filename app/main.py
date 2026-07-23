from fastapi import FastAPI

app = FastAPI(title="Taskly API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
