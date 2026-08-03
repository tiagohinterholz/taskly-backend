import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers.attachments import router as attachments_router
from app.api.routers.auth import router as auth_router
from app.api.routers.groups import router as groups_router
from app.api.routers.projects import router as projects_router
from app.api.routers.tasks import router as tasks_router

app = FastAPI(title="Taskly API")

# Frontend origin allowed to make credentialed (cookie) requests. SameSite=Lax
# on the session cookies (see api/routers/auth.py) is the primary CSRF
# mitigation per design.md's Risks & Concerns; CORS here additionally
# prevents other origins' JS from reading responses at all.
_CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "http://localhost:5173")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[_CORS_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(attachments_router)
app.include_router(groups_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
