from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.analysis_runs import boundary_error_response
from app.api.v1.analysis_runs import router as analysis_runs_router
from app.api.v1.analyses import router as analyses_router
from app.api.v1.bulk_uploads import router as bulk_uploads_router
from app.api.v1.companies import router as companies_router
from app.api.v1.documents import router as documents_router
from app.api.v1.periods import router as periods_router
from app.api.v1.trial_balances import router as trial_balances_router
from app.trial_balance.service import analyze_trial_balance
from app.integrations.analysis_http.dependencies import get_analysis_api_runtime
from app.integrations.analysis_http.errors import ApiBoundaryError


app = FastAPI(
    title="FINOS API",
    version="0.5.0",
    description="Financial Intelligence & Operating System",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(companies_router)
app.include_router(periods_router)
app.include_router(trial_balances_router)
app.include_router(documents_router)
app.include_router(analyses_router)
app.include_router(bulk_uploads_router)
app.include_router(analysis_runs_router)


@app.exception_handler(ApiBoundaryError)
async def analysis_api_boundary_error_handler(_request: Request, error: ApiBoundaryError):
    return boundary_error_response(error)


@app.exception_handler(RequestValidationError)
async def analysis_api_validation_error_handler(request: Request, error: RequestValidationError):
    if not request.url.path.startswith("/api/v1/analysis-runs"):
        return await request_validation_exception_handler(request, error)
    correlation_id = request.headers.get("X-Correlation-ID", "invalid")
    safe_fields = tuple(".".join(str(item) for item in issue.get("loc", ())[-2:]) for issue in error.errors())
    boundary = ApiBoundaryError(
        "MALFORMED_REQUEST", 422, "The request payload is invalid.",
        correlation_id, False, {"fields": safe_fields},
    )
    return boundary_error_response(boundary)


@app.get("/")
def root():
    return {
        "application": "FINOS",
        "status": "running",
        "version": "0.5.0",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/health/live", include_in_schema=False)
def health_live():
    return {"status": "live"}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    try:
        runtime = get_analysis_api_runtime()
        runtime.validate()
        deadline = runtime.clock.now_audit_time()
        required = (
            runtime.authentication_context_provider,
            runtime.authorization,
            runtime.security_audit,
            runtime.clock,
            runtime.document_inputs,
            runtime.result_inputs,
            runtime.admission,
            runtime.cursor_codec,
        )
        ready = all(binding.readiness_check(deadline) for binding in required)
    except Exception:
        ready = False
    return JSONResponse(
        {"ready": ready, "status": "ready" if ready else "not_ready"},
        status_code=200 if ready else 503,
    )


@app.post("/api/v1/trial-balance/validate")
async def validate_trial_balance(
    file: UploadFile = File(...),
):
    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="Dosya adı bulunamadı.",
        )

    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Şimdilik yalnızca .xlsx dosyaları kabul edilir.",
        )

    content = await file.read()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Yüklenen dosya boş.",
        )

    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Dosya boyutu 10 MB sınırını aşıyor.",
        )

    try:
        return analyze_trial_balance(
            content=content,
            filename=file.filename,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Excel dosyası analiz edilemedi: {error}",
        ) from error
