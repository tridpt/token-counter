from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAX_RECORDS = 2000
MAX_SCAN_FILE_BYTES = 80 * 1024 * 1024


@dataclass
class UsageRecord:
    source: str
    kind: str
    timestamp: str | None = None
    model: str | None = None
    path: str | None = None
    request_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    credits: float = 0.0
    context_percent: float | None = None
    note: str | None = None


@dataclass
class SourceScan:
    id: str
    name: str
    status: str
    paths: list[str]
    files_scanned: int = 0
    records: int = 0
    note: str | None = None
    totals: dict[str, Any] | None = None


def scan_all() -> dict[str, Any]:
    sources = [
        scan_claude_code(),
        scan_kiro(),
        scan_antigravity(),
    ]

    all_records: list[UsageRecord] = []
    for source in sources:
        all_records.extend(source.pop("_records", []))

    all_records.sort(key=lambda r: r.timestamp or "", reverse=True)
    all_records = all_records[:MAX_RECORDS]

    totals = _totals(all_records)
    totals["files_scanned"] = sum(source["files_scanned"] for source in sources)
    totals["sources"] = len(sources)

    return {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "totals": totals,
        "sources": sources,
        "records": [asdict(record) for record in all_records],
    }


def scan_claude_code() -> dict[str, Any]:
    roots = _existing_paths(
        [
            Path.home() / ".claude" / "projects",
            Path(os.getenv("APPDATA", "")) / "Claude" / "local-agent-mode-sessions",
        ]
    )
    source = SourceScan(
        id="claude",
        name="Claude Code",
        status="missing" if not roots else "no_usage",
        paths=[str(path) for path in roots],
        note="Reads Claude Code JSONL records with provider usage metadata when present.",
    )

    records: list[UsageRecord] = []
    files_scanned = 0
    seen: set[str] = set()

    for root in roots:
        for file_path in _iter_files(root, ["*.jsonl", "*.log"]):
            files_scanned += 1
            for line in _iter_matching_lines(file_path, "usage|input_tokens|output_tokens|total_tokens|prompt_tokens"):
                obj = _parse_json_line(line)
                if obj is None:
                    continue

                direct = _first_dict_path(obj, [["message", "usage"], ["usage"]])
                usage = direct or _find_usage_object(obj)
                if not usage:
                    continue

                message = obj.get("message") if isinstance(obj, dict) else None
                model = _first_text(
                    [
                        _get_path(message, ["model"]) if isinstance(message, dict) else None,
                        _get_path(obj, ["model"]) if isinstance(obj, dict) else None,
                    ]
                )
                request_id = _first_text(
                    [
                        _get_path(obj, ["requestId"]) if isinstance(obj, dict) else None,
                        _get_path(obj, ["request_id"]) if isinstance(obj, dict) else None,
                        _get_path(obj, ["uuid"]) if isinstance(obj, dict) else None,
                    ]
                )
                timestamp = _first_text(
                    [
                        _get_path(obj, ["timestamp"]) if isinstance(obj, dict) else None,
                        _get_path(obj, ["created_at"]) if isinstance(obj, dict) else None,
                    ]
                )

                fingerprint = f"{file_path}:{request_id or timestamp}:{json.dumps(usage, sort_keys=True, default=str)}"
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)

                records.append(
                    _record_from_usage(
                        source="Claude Code",
                        kind="token_usage",
                        usage=usage,
                        model=model,
                        timestamp=timestamp or _timestamp_from_path(file_path),
                        request_id=request_id,
                        path=file_path,
                    )
                )

    source.files_scanned = files_scanned
    source.records = len(records)
    if records:
        source.status = "ok"
        source.totals = _totals(records)
    elif roots:
        source.status = "no_usage"
    data = asdict(source)
    data["_records"] = records
    return data


def scan_kiro() -> dict[str, Any]:
    roots = _existing_paths(
        [
            Path(os.getenv("APPDATA", "")) / "Kiro" / "logs",
            Path.home() / ".kiro",
        ]
    )
    source = SourceScan(
        id="kiro",
        name="Kiro",
        status="missing" if not roots else "no_usage",
        paths=[str(path) for path in roots],
        note="This Kiro build exposes actual metered credits and context percentage in local logs; input/output token split was not present.",
    )

    records: list[UsageRecord] = []
    files_scanned = 0
    seen_requests: set[str] = set()

    for root in roots:
        for file_path in _iter_files(root, ["5-Q Chat API*.log"]):
            files_scanned += 1
            for line in _iter_matching_lines(file_path, "meteringEvent|usageSummaryEntry|contextUsageEvent"):
                obj = _parse_json_line(line)
                if obj is None:
                    continue

                response = obj.get("response", {}) if isinstance(obj, dict) else {}
                metadata = response.get("metadata", {}) if isinstance(response, dict) else {}
                request_id = _first_text([metadata.get("requestId"), metadata.get("request_id")])
                if request_id and request_id in seen_requests:
                    continue

                events = response.get("events", []) if isinstance(response, dict) else []
                credits = 0.0
                context_percent: float | None = None
                model: str | None = None

                if isinstance(events, list):
                    for event in events:
                        if not isinstance(event, dict):
                            continue
                        metering = event.get("meteringEvent")
                        if isinstance(metering, dict):
                            credits += _float(metering.get("usage"))
                        context = event.get("contextUsageEvent")
                        if isinstance(context, dict):
                            context_percent = _optional_float(context.get("contextUsagePercentage"))
                        assistant = event.get("assistantResponseEvent")
                        if isinstance(assistant, dict) and not model:
                            model = _clean_model(_first_text([assistant.get("modelId"), assistant.get("model")]))

                if credits <= 0:
                    summary = _get_path(response, ["fullMessage", "message", "kwargs", "additional_kwargs", "usageSummaryEntry"])
                    if isinstance(summary, dict):
                        credits = _float(summary.get("usage"))
                    context_percent = context_percent or _optional_float(
                        _get_path(response, ["fullMessage", "message", "kwargs", "additional_kwargs", "contextUsagePercentage"])
                    )

                if credits <= 0 and context_percent is None:
                    continue

                if request_id:
                    seen_requests.add(request_id)

                records.append(
                    UsageRecord(
                        source="Kiro",
                        kind="credit_usage",
                        timestamp=_timestamp_from_path(file_path),
                        model=model,
                        path=str(file_path),
                        request_id=request_id,
                        credits=credits,
                        context_percent=context_percent,
                        note="Kiro log reports credits, not exact token split.",
                    )
                )

    source.files_scanned = files_scanned
    source.records = len(records)
    if records:
        source.status = "ok"
        source.totals = _totals(records)
    elif roots:
        source.status = "no_usage"
    data = asdict(source)
    data["_records"] = records
    return data


def scan_antigravity() -> dict[str, Any]:
    roots = _existing_paths(
        [
            Path(os.getenv("APPDATA", "")) / "Antigravity",
            Path.home() / ".antigravity",
        ]
    )
    source = SourceScan(
        id="antigravity",
        name="Google Antigravity",
        status="missing" if not roots else "no_usage",
        paths=[str(path) for path in roots],
        note="Antigravity exposes quota in the app settings; exact local token metadata is only shown here if present in logs.",
    )

    records: list[UsageRecord] = []
    files_scanned = 0
    seen: set[str] = set()
    pattern = (
        "usageMetadata|promptTokenCount|candidatesTokenCount|totalTokenCount|"
        "input_tokens|output_tokens|total_tokens|prompt_tokens|completion_tokens"
    )

    for root in roots:
        candidates = list(_iter_files(root / "logs", ["*.log", "*.jsonl"])) if (root / "logs").exists() else []
        for extra in [root / "app_storage.json", root / "Local State"]:
            if extra.exists() and extra.is_file():
                candidates.append(extra)

        for file_path in candidates:
            files_scanned += 1
            for line in _iter_matching_lines(file_path, pattern):
                obj = _parse_json_line(line)
                if obj is None:
                    continue
                for usage in _find_all_usage_objects(obj):
                    fingerprint = f"{file_path}:{json.dumps(usage, sort_keys=True, default=str)}"
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    records.append(
                        _record_from_usage(
                            source="Google Antigravity",
                            kind="token_usage",
                            usage=usage,
                            model=_first_text([_get_path(obj, ["model"]), _get_path(obj, ["modelId"])]),
                            timestamp=_timestamp_from_path(file_path),
                            path=file_path,
                        )
                    )

    source.files_scanned = files_scanned
    source.records = len(records)
    if records:
        source.status = "ok"
        source.totals = _totals(records)
    elif roots:
        source.status = "no_usage"
    data = asdict(source)
    data["_records"] = records
    return data


def _existing_paths(paths: list[Path]) -> list[Path]:
    return [path for path in paths if str(path) and path.exists()]


def _iter_files(root: Path, patterns: list[str]):
    if not root.exists():
        return
    for pattern in patterns:
        yield from root.rglob(pattern)


def _iter_matching_lines(file_path: Path, pattern: str):
    try:
        if file_path.stat().st_size > MAX_SCAN_FILE_BYTES:
            return
        regex = re.compile(pattern, re.IGNORECASE)
        with file_path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if regex.search(line):
                    yield line
    except (OSError, UnicodeError):
        return


def _parse_json_line(line: str) -> Any | None:
    line = line.strip()
    if not line:
        return None
    candidates = [line]
    first_brace = line.find("{")
    if first_brace > 0:
        candidates.append(line[first_brace:])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    return None


def _record_from_usage(
    *,
    source: str,
    kind: str,
    usage: dict[str, Any],
    model: str | None = None,
    timestamp: str | None = None,
    request_id: str | None = None,
    path: Path | str | None = None,
) -> UsageRecord:
    input_tokens = _int_first(usage, ["input_tokens", "prompt_tokens", "inputTokenCount", "promptTokenCount"])
    output_tokens = _int_first(
        usage,
        ["output_tokens", "completion_tokens", "outputTokenCount", "candidatesTokenCount", "completionTokenCount"],
    )
    cache_read = _int_first(
        usage,
        ["cache_read_input_tokens", "cacheReadInputTokens", "cache_read_tokens", "cacheReadTokens"],
    )
    cache_creation = _int_first(
        usage,
        ["cache_creation_input_tokens", "cacheCreationInputTokens", "cache_write_tokens", "cacheWriteTokens"],
    )
    reasoning = _int_first(
        usage,
        ["reasoning_tokens", "thoughtsTokenCount", "thinking_tokens", "thinkingTokenCount"],
    )
    explicit_total = _int_first(usage, ["total_tokens", "totalTokenCount", "totalTokens"])
    total = explicit_total or (input_tokens + output_tokens + cache_read + cache_creation + reasoning)

    return UsageRecord(
        source=source,
        kind=kind,
        timestamp=timestamp,
        model=_clean_model(model),
        path=str(path) if path else None,
        request_id=request_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read,
        cache_creation_tokens=cache_creation,
        reasoning_tokens=reasoning,
        total_tokens=total,
    )


def _find_usage_object(obj: Any) -> dict[str, Any] | None:
    found = _find_all_usage_objects(obj)
    return found[0] if found else None


def _find_all_usage_objects(obj: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any):
        if isinstance(value, dict):
            if _looks_like_usage(value):
                found.append(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    return found


def _looks_like_usage(value: dict[str, Any]) -> bool:
    keys = set(value.keys())
    usage_keys = {
        "usage",
        "usageMetadata",
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
        "inputTokenCount",
        "promptTokenCount",
        "candidatesTokenCount",
        "totalTokenCount",
    }
    if keys & usage_keys:
        return True
    nested = value.get("usageMetadata")
    return isinstance(nested, dict) and _looks_like_usage(nested)


def _first_dict_path(obj: Any, paths: list[list[str]]) -> dict[str, Any] | None:
    for path in paths:
        value = _get_path(obj, path)
        if isinstance(value, dict):
            return value
    return None


def _get_path(obj: Any, path: list[str]) -> Any:
    current = obj
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_text(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _int_first(mapping: dict[str, Any], keys: list[str]) -> int:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, dict) and key == "usageMetadata":
            continue
        number = _optional_float(value)
        if number is not None:
            return int(number)
    nested = mapping.get("usageMetadata")
    if isinstance(nested, dict):
        return _int_first(nested, keys)
    return 0


def _float(value: Any) -> float:
    number = _optional_float(value)
    return number if number is not None else 0.0


def _optional_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _totals(records: list[UsageRecord]) -> dict[str, Any]:
    return {
        "records": len(records),
        "input_tokens": sum(item.input_tokens for item in records),
        "output_tokens": sum(item.output_tokens for item in records),
        "cache_read_tokens": sum(item.cache_read_tokens for item in records),
        "cache_creation_tokens": sum(item.cache_creation_tokens for item in records),
        "reasoning_tokens": sum(item.reasoning_tokens for item in records),
        "total_tokens": sum(item.total_tokens for item in records),
        "credits": round(sum(item.credits for item in records), 6),
    }


def _timestamp_from_path(path: Path) -> str | None:
    match = re.search(r"(\d{8}T\d{6})", str(path))
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%dT%H%M%S").isoformat()
        except ValueError:
            pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def _clean_model(model: str | None) -> str | None:
    if not model:
        return None
    text = model.strip()
    # Some Kiro stream events concatenate the same model id repeatedly.
    for marker in ["claude-", "gemini-", "gpt-"]:
        second = text.find(marker, len(marker))
        if text.startswith(marker) and second > 0:
            return text[:second]
    return text
