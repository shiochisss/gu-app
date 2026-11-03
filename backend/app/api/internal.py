import hmac

from fastapi import APIRouter, Request

from app.errors import ApiError
from app.schemas.operations import JobsInput, JobsResult
from app.services.jobs import run_jobs

router = APIRouter(tags=["internal jobs"])


@router.post("/internal/jobs/run", response_model=JobsResult)
def jobs(request: Request, data: JobsInput | None = None):
    if not hmac.compare_digest(
        request.headers.get("X-Job-Secret", "").encode(),
        request.app.state.settings.job_secret.get_secret_value().encode(),
    ):
        raise ApiError(403, "FORBIDDEN")
    return run_jobs(request.app, data.jobs if data else None)
