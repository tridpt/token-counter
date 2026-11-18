# AI Usage Monitor

Local web app for checking AI coding-tool usage.

It has two modes:

- **Actual usage scanner**: reads local logs and provider usage metadata when available.
- **Manual tokenizer estimate**: counts pasted input/output text with `tiktoken`.

## Supported Sources

| Source | What can be read locally |
| --- | --- |
| Claude Code | Actual token usage if Claude Code JSONL/telemetry records are present |
| Kiro | Actual metered credits and context percentage from local Kiro logs |
| Google Antigravity | Exact token usage only if local logs contain usage metadata; otherwise the app reports no local usage metadata found |
| API JSON | Actual provider usage if you paste a response containing a `usage` object |

Important: if a vendor only exposes quota/credits and does not write input/output token metadata locally, this app will not pretend to have exact tokens.

## Run

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8031
```

Open:

```text
http://127.0.0.1:8031
```

Or double-click:

```text
start_token_counter.bat
```

## Privacy

The scanner is local-only and read-only. It aggregates metadata such as token counts, credits, model, timestamp, request id, and log path. It does not send data to any external service.
