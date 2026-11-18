from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from usage_scanner import scan_all
except ModuleNotFoundError:
    from backend.usage_scanner import scan_all

try:
    import tiktoken
except ImportError:  # pragma: no cover - reported through /api/health
    tiktoken = None


app = FastAPI(title="AI Token Counter", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


MODEL_PRESETS = [
    {"id": "gpt-4.1", "label": "GPT-4.1", "encoding": "o200k_base"},
    {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini", "encoding": "o200k_base"},
    {"id": "gpt-4o", "label": "GPT-4o", "encoding": "o200k_base"},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "encoding": "o200k_base"},
    {"id": "o3", "label": "o3", "encoding": "o200k_base"},
    {"id": "o4-mini", "label": "o4 mini", "encoding": "o200k_base"},
    {"id": "gpt-3.5-turbo", "label": "GPT-3.5 Turbo", "encoding": "cl100k_base"},
    {"id": "o200k_base", "label": "Generic o200k_base", "encoding": "o200k_base"},
    {"id": "cl100k_base", "label": "Generic cl100k_base", "encoding": "cl100k_base"},
]

ENCODING_BY_MODEL = {item["id"]: item["encoding"] for item in MODEL_PRESETS}


class CountRequest(BaseModel):
    model: str = "gpt-4o-mini"
    input_text: str = ""
    output_text: str = ""


def _require_tiktoken() -> Any:
    if tiktoken is None:
        raise HTTPException(
            status_code=500,
            detail="Missing tiktoken. Run: python -m pip install -r requirements.txt",
        )
    return tiktoken


@lru_cache(maxsize=32)
def _encoder_for(model: str):
    tk = _require_tiktoken()
    model = (model or "gpt-4o-mini").strip()

    if model in {"o200k_base", "cl100k_base", "p50k_base", "r50k_base"}:
        return tk.get_encoding(model)

    try:
        return tk.encoding_for_model(model)
    except KeyError:
        encoding_name = ENCODING_BY_MODEL.get(model, "o200k_base")
        return tk.get_encoding(encoding_name)


def _count(text: str, model: str) -> int:
    encoder = _encoder_for(model)
    return len(encoder.encode(text or ""))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "tokenizer": tiktoken is not None}


@app.get("/api/models")
def models() -> dict:
    return {"models": MODEL_PRESETS}


@app.post("/api/count")
def count_tokens(req: CountRequest) -> dict:
    encoder = _encoder_for(req.model)
    input_tokens = _count(req.input_text, req.model)
    output_tokens = _count(req.output_text, req.model)

    return {
        "model": req.model,
        "encoding": encoder.name,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "input_chars": len(req.input_text or ""),
        "output_chars": len(req.output_text or ""),
    }


@app.get("/api/usage/scan")
def scan_usage() -> dict:
    return scan_all()


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
