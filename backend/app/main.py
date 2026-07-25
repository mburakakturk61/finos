from fastapi import FastAPI, File, HTTPException, UploadFile

from app.api.v1.companies import router as companies_router
from app.api.v1.periods import router as periods_router
from app.trial_balance.service import analyze_trial_balance


app = FastAPI(
    title="FINOS API",
    version="0.4.0",
    description="Financial Intelligence & Operating System",
)

app.include_router(companies_router)
app.include_router(periods_router)


@app.get("/")
def root():
    return {
        "application": "FINOS",
        "status": "running",
        "version": "0.4.0",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


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
