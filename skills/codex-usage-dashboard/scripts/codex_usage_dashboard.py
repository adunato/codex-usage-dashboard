#!/usr/bin/env python3
"""Local read-only dashboard for Codex session token usage.

The server reads Codex JSONL logs from:
  - ~/.codex/sessions
  - ~/.codex/archived_sessions
  - Windows ~/.codex when running under WSL and the directory is mounted

It does not modify Codex files. Bind address defaults to 127.0.0.1.
"""

from __future__ import annotations

import argparse
import importlib.util
import concurrent.futures
import datetime as dt
import hashlib
import json
import math
import multiprocessing
import os
import platform
import re
import secrets
import socket
import signal
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator, NamedTuple
from urllib.parse import parse_qs, urlparse


TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)

ZERO_COST_MODEL_PRICES_USD_PER_M_TOKENS = {
    # Auto-review has no public API list price; show it as zero by dashboard convention.
    "codex-auto-review": {"input": 0.0, "cached_input": 0.0, "output": 0.0},
}

LEGACY_MODEL_PRICES_USD_PER_M_TOKENS = {
    "gpt-5.5": {"input": 5.00, "cached_input": 0.50, "output": 30.00},
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.00},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    "gpt-5.3-codex": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-5.3-chat-latest": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-5.2": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-5.2-codex": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-5.2-chat-latest": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
    "gpt-5.1-codex": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5.1-codex-max": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
    "gpt-5-codex": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
}

# 2026-07-10 01:00 in Asia/Shanghai.
GPT_5_6_PRICING_EFFECTIVE_AT = dt.datetime(2026, 7, 9, 17, 0, 0, tzinfo=dt.UTC)
GPT_5_6_LAUNCH_MODEL_PRICES_USD_PER_M_TOKENS = {
    "gpt-5.6": {"input": 5.00, "cached_input": 0.50, "cache_write_input": 6.25, "output": 30.00},
    "gpt-5.6-sol": {"input": 5.00, "cached_input": 0.50, "cache_write_input": 6.25, "output": 30.00},
    "gpt-5.6-terra": {"input": 2.50, "cached_input": 0.25, "cache_write_input": 3.125, "output": 15.00},
    "gpt-5.6-luna": {"input": 1.00, "cached_input": 0.10, "cache_write_input": 1.25, "output": 6.00},
}
# OpenAI's changelog dates the Terra/Luna reduction to July 30. Use the
# pricing Markdown's Last-Modified time as the exact boundary: 2026-07-31
# 00:38:10 UTC (2026-07-31 08:38:10 in Asia/Shanghai).
GPT_5_6_REPRICING_EFFECTIVE_AT = dt.datetime(2026, 7, 31, 0, 38, 10, tzinfo=dt.UTC)
GPT_5_6_MODEL_PRICES_USD_PER_M_TOKENS = {
    "gpt-5.6": {"input": 5.00, "cached_input": 0.50, "cache_write_input": 6.25, "output": 30.00},
    "gpt-5.6-sol": {"input": 5.00, "cached_input": 0.50, "cache_write_input": 6.25, "output": 30.00},
    "gpt-5.6-terra": {"input": 2.00, "cached_input": 0.20, "cache_write_input": 2.50, "output": 12.00},
    "gpt-5.6-luna": {"input": 0.20, "cached_input": 0.02, "cache_write_input": 0.25, "output": 1.20},
}
# The long-context tier applies to the full request above 272K input tokens.
GPT_5_6_LONG_CONTEXT_INPUT_THRESHOLD = 272_000
GPT_5_6_LAUNCH_LONG_CONTEXT_MODEL_PRICES_USD_PER_M_TOKENS = {
    "gpt-5.6": {"input": 10.00, "cached_input": 1.00, "cache_write_input": 12.50, "output": 45.00},
    "gpt-5.6-sol": {"input": 10.00, "cached_input": 1.00, "cache_write_input": 12.50, "output": 45.00},
    "gpt-5.6-terra": {"input": 5.00, "cached_input": 0.50, "cache_write_input": 6.25, "output": 22.50},
    "gpt-5.6-luna": {"input": 2.00, "cached_input": 0.20, "cache_write_input": 2.50, "output": 9.00},
}
GPT_5_6_LONG_CONTEXT_MODEL_PRICES_USD_PER_M_TOKENS = {
    "gpt-5.6": {"input": 10.00, "cached_input": 1.00, "cache_write_input": 12.50, "output": 45.00},
    "gpt-5.6-sol": {"input": 10.00, "cached_input": 1.00, "cache_write_input": 12.50, "output": 45.00},
    "gpt-5.6-terra": {"input": 4.00, "cached_input": 0.40, "cache_write_input": 5.00, "output": 18.00},
    "gpt-5.6-luna": {"input": 0.40, "cached_input": 0.04, "cache_write_input": 0.50, "output": 1.80},
}
GPT_5_6_LONG_CONTEXT_PRICE_SCHEDULES = (
    (GPT_5_6_PRICING_EFFECTIVE_AT, GPT_5_6_LAUNCH_LONG_CONTEXT_MODEL_PRICES_USD_PER_M_TOKENS),
    (GPT_5_6_REPRICING_EFFECTIVE_AT, GPT_5_6_LONG_CONTEXT_MODEL_PRICES_USD_PER_M_TOKENS),
)
# Public xAI API list prices for Grok 4.5 (docs.x.ai).
# Long-context tier applies to requests that exceed 200K input tokens.
GROK_4_5_MODEL_PRICES_USD_PER_M_TOKENS = {
    "grok-4.5": {"input": 2.00, "cached_input": 0.30, "output": 6.00},
}
GROK_4_5_LONG_CONTEXT_INPUT_THRESHOLD = 200_000
GROK_4_5_LONG_CONTEXT_MODEL_PRICES_USD_PER_M_TOKENS = {
    "grok-4.5": {"input": 4.00, "cached_input": 0.60, "output": 12.00},
}
MODEL_PRICES_USD_PER_M_TOKENS = {
    **ZERO_COST_MODEL_PRICES_USD_PER_M_TOKENS,
    **LEGACY_MODEL_PRICES_USD_PER_M_TOKENS,
    **GPT_5_6_MODEL_PRICES_USD_PER_M_TOKENS,
    **GROK_4_5_MODEL_PRICES_USD_PER_M_TOKENS,
}
GPT_5_6_LAUNCH_PRICES_USD_PER_M_TOKENS = {
    **ZERO_COST_MODEL_PRICES_USD_PER_M_TOKENS,
    **LEGACY_MODEL_PRICES_USD_PER_M_TOKENS,
    **GPT_5_6_LAUNCH_MODEL_PRICES_USD_PER_M_TOKENS,
    **GROK_4_5_MODEL_PRICES_USD_PER_M_TOKENS,
}
MODEL_PRICE_SCHEDULES = (
    (
        None,
        {
            **ZERO_COST_MODEL_PRICES_USD_PER_M_TOKENS,
            **LEGACY_MODEL_PRICES_USD_PER_M_TOKENS,
            **GROK_4_5_MODEL_PRICES_USD_PER_M_TOKENS,
        },
    ),
    (GPT_5_6_PRICING_EFFECTIVE_AT, GPT_5_6_LAUNCH_PRICES_USD_PER_M_TOKENS),
    (GPT_5_6_REPRICING_EFFECTIVE_AT, MODEL_PRICES_USD_PER_M_TOKENS),
)

PERIOD_KEYS = {"today", "7d", "30d", "week", "month", "all"}
APP_NAME = "cousash"
SNAPSHOT_SCHEMA = "cousash.remote-snapshot"
SNAPSHOT_VERSION = 1
PARSE_CACHE_VERSION = 6
PARSE_CACHE_SAMPLE_BYTES = 4096
DEFAULT_PARSE_WORKERS = min(4, max(1, os.cpu_count() or 2))
DEFAULT_PARSE_MIN_FILES = 8
DEFAULT_PARSE_MIN_BYTES = 256 * 1024 * 1024


def environment_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


DASHBOARD_FEATURES = [
    "session-analysis-v1",
    "periods",
    "period-deltas",
    "period-token-label",
    "all-period",
    "calendar-range-v2",
    "multi-codex-home",
    "wsl-windows-autodiscovery",
    "windows-cwd-folder-name",
    "project-grouped-default-view",
    "project-compact-layout-v2",
    "project-env-tag-in-conversation-column",
    "git-worktree-project-grouping",
    "remote-snapshot-import-v1",
    "effective-dated-pricing-v1",
    "bounded-period-scan-v1",
    "fork-aware-subagent-usage-v1",
    "expandable-agent-task-rollups-v1",
    "compact-agent-task-tree-v1",
    "aligned-agent-task-tree-v1",
    "main-agent-child-usage-row-v1",
    "aligned-task-title-gutter-v1",
    "project-session-indent-v1",
    "clickable-task-rows-and-gutter-v1",
    "main-agent-title-alignment-v1",
    "compact-subagent-indent-v1",
    "project-folder-aggregate-columns-v1",
    "filtered-summary-metrics-v1",
    "fast-rollout-projection-v1",
    "snapshot-detail-token-v1",
    "persistent-parse-cache-v1",
    "append-resume-v1",
    "parallel-cold-parse-v1",
]

SUMMARY_KEYS = (
    "uid",
    "session_id",
    "root_session_id",
    "parent_thread_id",
    "forked_from_id",
    "thread_source",
    "is_subagent",
    "agent_path",
    "agent_nickname",
    "agent_role",
    "title",
    "source",
    "environment",
    "environment_id",
    "is_remote",
    "remote_device_short_code",
    "remote_imported_at",
    "remote_exported_at",
    "codex_home",
    "path",
    "file_size",
    "parse_errors",
    "created_at",
    "start_at",
    "end_at",
    "updated_at",
    "cwd",
    "project",
    "project_root",
    "workspace_root",
    "project_branch",
    "is_git_worktree",
    "model",
    "models",
    "effort",
    "total_token_usage",
    "last_token_usage",
    "branch_total_token_usage",
    "inherited_token_usage",
    "inherited_token_event_count",
    "fork_usage_resolved",
    "estimated_cost_usd",
    "estimated_cost_breakdown_usd",
    "price_model_known",
    "cached_input_percent",
    "token_event_count",
    "turn_count",
    "completed_turn_count",
    "duration_ms_total",
    "time_to_first_token_ms_avg",
)


def zero_usage() -> dict[str, int]:
    return {key: 0 for key in TOKEN_KEYS}


def model_from_payload(payload: Any) -> str:
    """Extract the active model name from common Codex log payload shapes."""
    if not isinstance(payload, dict):
        return ""

    candidates: list[Any] = [
        payload.get("model"),
        payload.get("model_slug"),
    ]

    thread_settings = payload.get("thread_settings")
    if isinstance(thread_settings, dict):
        candidates.extend(
            [
                thread_settings.get("model"),
                thread_settings.get("model_slug"),
            ]
        )
        collab = thread_settings.get("collaboration_mode")
        if isinstance(collab, dict):
            settings = collab.get("settings")
            if isinstance(settings, dict):
                candidates.append(settings.get("model"))

    collab = payload.get("collaboration_mode")
    if isinstance(collab, dict):
        settings = collab.get("settings")
        if isinstance(settings, dict):
            candidates.append(settings.get("model"))

    for value in candidates:
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return ""


def unique_models(*sources: Any) -> list[str]:
    """Collect model names in first-appearance order, de-duplicated."""
    models: list[str] = []

    def add(name: Any) -> None:
        if not isinstance(name, str):
            return
        cleaned = name.strip()
        if cleaned and cleaned not in models:
            models.append(cleaned)

    for source in sources:
        if isinstance(source, str):
            add(source)
        elif isinstance(source, list):
            for item in source:
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, dict):
                    add(item.get("model") or model_from_payload(item))
        elif isinstance(source, dict):
            add(source.get("model") or model_from_payload(source))
    return models


def normalize_usage(value: Any) -> dict[str, int]:
    usage = zero_usage()
    if isinstance(value, dict):
        for key in TOKEN_KEYS:
            raw = value.get(key, 0)
            if key == "cache_write_tokens" and key not in value:
                raw = value.get("cache_write_input_tokens", 0)
            if isinstance(raw, int) and not isinstance(raw, bool):
                usage[key] = max(raw, 0)
            elif isinstance(raw, float) and math.isfinite(raw) and raw.is_integer():
                usage[key] = max(int(raw), 0)
    return usage


def add_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {key: int(left.get(key, 0)) + int(right.get(key, 0)) for key in TOKEN_KEYS}


def subtract_usage(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    return {key: max(int(left.get(key, 0)) - int(right.get(key, 0)), 0) for key in TOKEN_KEYS}


def pricing_model_key(model: str) -> str:
    """Normalize provider-prefixed model ids for price lookup.

    Third-party routers often emit names like ``jws/gpt-5.6-sol`` or
    ``grok-xyz/grok-4.5``. Price tables key on the bare model name after the
    final ``/``.
    """
    model_key = (model or "").strip().lower()
    if "/" in model_key:
        model_key = model_key.rsplit("/", 1)[-1].strip()
    return model_key


def rate_entry_for_model(
    model: str,
    rates: dict[str, dict[str, float]],
) -> tuple[str, dict[str, float]] | None:
    model_key = pricing_model_key(model)
    if not model_key:
        return None
    if model_key in rates:
        return model_key, rates[model_key]
    for key in sorted(rates, key=len, reverse=True):
        if model_key.startswith(key + "-"):
            return key, rates[key]
    return None


def rate_for_model(model: str, rates: dict[str, dict[str, float]]) -> dict[str, float] | None:
    entry = rate_entry_for_model(model, rates)
    return entry[1] if entry else None


def price_schedule_at(timestamp: Any = None) -> tuple[dt.datetime | None, dict[str, dict[str, float]]]:
    if timestamp is None:
        return MODEL_PRICE_SCHEDULES[-1]
    if isinstance(timestamp, dt.datetime):
        moment = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=dt.UTC)
        moment = moment.astimezone(dt.UTC)
    else:
        moment = parse_timestamp(timestamp)
    if moment is None:
        return MODEL_PRICE_SCHEDULES[-1]
    for effective_at, rates in reversed(MODEL_PRICE_SCHEDULES):
        if effective_at is None or moment >= effective_at:
            return effective_at, rates
    return MODEL_PRICE_SCHEDULES[0]


def gpt_5_6_long_context_rates_at(
    effective_at: dt.datetime | None,
) -> dict[str, dict[str, float]]:
    for starts_at, rates in reversed(GPT_5_6_LONG_CONTEXT_PRICE_SCHEDULES):
        if effective_at is None or effective_at >= starts_at:
            return rates
    return GPT_5_6_LAUNCH_LONG_CONTEXT_MODEL_PRICES_USD_PER_M_TOKENS


def model_rate_effective_at(
    model: str,
    selected_effective_at: dt.datetime | None,
    selected_prices: dict[str, float],
    schedules: tuple[tuple[dt.datetime | None, dict[str, dict[str, float]]], ...],
) -> dt.datetime | None:
    selected_index = next(
        (
            index
            for index, (effective_at, _rates) in enumerate(schedules)
            if effective_at == selected_effective_at
        ),
        len(schedules) - 1,
    )
    rate_effective_at = selected_effective_at
    for earlier_effective_at, earlier_rates in reversed(schedules[:selected_index]):
        earlier_entry = rate_entry_for_model(model, earlier_rates)
        if earlier_entry is None or earlier_entry[1] != selected_prices:
            break
        rate_effective_at = earlier_effective_at
    return rate_effective_at


def price_entry_for_model(
    model: str,
    timestamp: Any = None,
    input_tokens: int | None = None,
) -> dict[str, Any] | None:
    effective_at, rates = price_schedule_at(timestamp)
    entry = rate_entry_for_model(model, rates)
    if not entry:
        return None
    canonical_model, prices = entry
    rate_effective_at = model_rate_effective_at(
        model,
        effective_at,
        prices,
        MODEL_PRICE_SCHEDULES,
    )
    context_tier = None
    if canonical_model in GPT_5_6_MODEL_PRICES_USD_PER_M_TOKENS:
        context_tier = "short"
        if input_tokens is not None and input_tokens > GPT_5_6_LONG_CONTEXT_INPUT_THRESHOLD:
            long_entry = rate_entry_for_model(
                model,
                gpt_5_6_long_context_rates_at(effective_at),
            )
            if long_entry is not None:
                canonical_model, prices = long_entry
                rate_effective_at = model_rate_effective_at(
                    model,
                    effective_at,
                    prices,
                    GPT_5_6_LONG_CONTEXT_PRICE_SCHEDULES,
                )
                context_tier = "long"
    elif canonical_model in GROK_4_5_MODEL_PRICES_USD_PER_M_TOKENS:
        context_tier = "short"
        if input_tokens is not None and input_tokens > GROK_4_5_LONG_CONTEXT_INPUT_THRESHOLD:
            long_entry = rate_entry_for_model(
                model,
                GROK_4_5_LONG_CONTEXT_MODEL_PRICES_USD_PER_M_TOKENS,
            )
            if long_entry is not None:
                canonical_model, prices = long_entry
                context_tier = "long"
    return {
        "model": canonical_model,
        "effective_at": utc_iso(rate_effective_at) if rate_effective_at is not None else None,
        "context_tier": context_tier,
        "prices": prices,
    }


def price_for_model(
    model: str,
    timestamp: Any = None,
    input_tokens: int | None = None,
) -> dict[str, float] | None:
    entry = price_entry_for_model(model, timestamp, input_tokens)
    return entry["prices"] if entry else None


def usage_cost_parts(usage: dict[str, int], price: dict[str, float]) -> dict[str, float] | None:
    input_tokens = max(int(usage.get("input_tokens", 0)), 0)
    cached_tokens = min(max(int(usage.get("cached_input_tokens", 0)), 0), input_tokens)
    cache_write_tokens = min(
        max(int(usage.get("cache_write_tokens", usage.get("cache_write_input_tokens", 0))), 0),
        input_tokens - cached_tokens,
    )
    uncached_tokens = input_tokens - cached_tokens - cache_write_tokens
    output_tokens = max(int(usage.get("output_tokens", 0)), 0)
    reasoning_tokens = min(max(int(usage.get("reasoning_output_tokens", 0)), 0), output_tokens)
    cache_write_price = price.get("cache_write_input", price["input"])
    return {
        "input_tokens": uncached_tokens * price["input"] / 1_000_000,
        "cached_input_tokens": cached_tokens * price["cached_input"] / 1_000_000,
        "cache_write_tokens": cache_write_tokens * cache_write_price / 1_000_000,
        "output_tokens": output_tokens * price["output"] / 1_000_000,
        "reasoning_output_tokens": reasoning_tokens * price["output"] / 1_000_000,
    }


def total_cost_from_parts(parts: dict[str, float]) -> float:
    return sum(
        parts.get(key, 0.0)
        for key in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens")
    )


def estimate_cost_usd(usage: dict[str, int], model: str, timestamp: Any = None) -> float | None:
    price = price_for_model(model, timestamp, max(int(usage.get("input_tokens", 0)), 0))
    if not price:
        return None
    parts = usage_cost_parts(usage, price)
    if parts is None:
        return None
    return round(total_cost_from_parts(parts), 6)


def estimate_cost_breakdown_usd(
    usage: dict[str, int],
    model: str,
    timestamp: Any = None,
) -> dict[str, float] | None:
    price = price_for_model(model, timestamp, max(int(usage.get("input_tokens", 0)), 0))
    if not price:
        return None
    parts = usage_cost_parts(usage, price)
    if parts is None:
        return None
    return {key: round(value, 6) for key, value in parts.items()}


def usage_has_tokens(usage: dict[str, int]) -> bool:
    return any(int(usage.get(key, 0)) > 0 for key in TOKEN_KEYS)


def timeline_usage_delta(current: dict[str, int], previous: dict[str, int]) -> dict[str, int]:
    counters = ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "total_tokens")
    current_total = int(current.get("total_tokens", 0))
    previous_total = int(previous.get("total_tokens", 0))
    if current_total or previous_total:
        if current_total < previous_total:
            return current
    elif any(int(current.get(key, 0)) < int(previous.get(key, 0)) for key in counters):
        return current
    return subtract_usage(current, previous)


def timeline_rows_with_deltas(
    timeline: Any,
) -> list[tuple[dict[str, Any], dt.datetime, dict[str, int], dict[str, int]]]:
    if not isinstance(timeline, list):
        return []
    rows: list[tuple[dict[str, Any], dt.datetime]] = []
    ordered = True
    previous_timestamp: dt.datetime | None = None
    for row in timeline:
        if not isinstance(row, dict):
            continue
        timestamp = parse_timestamp(row.get("timestamp"))
        if timestamp is None:
            continue
        if previous_timestamp is not None and timestamp < previous_timestamp:
            ordered = False
        previous_timestamp = timestamp
        rows.append((row, timestamp))
    if not ordered:
        rows.sort(key=lambda item: item[1])

    result: list[tuple[dict[str, Any], dt.datetime, dict[str, int], dict[str, int]]] = []
    previous_usage = zero_usage()
    for row, timestamp in rows:
        cumulative_usage = normalize_usage(row.get("total_token_usage"))
        delta_usage = timeline_usage_delta(cumulative_usage, previous_usage)
        previous_usage = cumulative_usage
        result.append((row, timestamp, cumulative_usage, delta_usage))
    return result


def timeline_usage_fingerprint(row: dict[str, Any]) -> tuple[int, ...]:
    total = normalize_usage(row.get("total_token_usage"))
    last = normalize_usage(row.get("last_token_usage"))
    return tuple(total[key] for key in TOKEN_KEYS) + tuple(last[key] for key in TOKEN_KEYS)


def inherited_timeline_prefix_length(
    child_timeline: Any,
    parent_timeline: Any,
) -> int:
    if not isinstance(child_timeline, list) or not isinstance(parent_timeline, list):
        return 0
    child_rows = [row for row in child_timeline if isinstance(row, dict)]
    parent_rows = [row for row in parent_timeline if isinstance(row, dict)]
    if not child_rows or not parent_rows:
        return 0

    child_fingerprints = [timeline_usage_fingerprint(row) for row in child_rows]
    parent_fingerprints = [timeline_usage_fingerprint(row) for row in parent_rows]
    best = 0
    for start, fingerprint in enumerate(parent_fingerprints):
        if fingerprint != child_fingerprints[0]:
            continue
        length = 0
        while (
            length < len(child_fingerprints)
            and start + length < len(parent_fingerprints)
            and child_fingerprints[length] == parent_fingerprints[start + length]
        ):
            length += 1
        best = max(best, length)
    return best


def rebase_timeline_after_prefix(
    timeline: Any,
    inherited_event_count: int,
    inherited_usage_override: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int], dict[str, int]]:
    rows = [row for row in timeline if isinstance(row, dict)] if isinstance(timeline, list) else []
    inherited_event_count = min(max(int(inherited_event_count), 0), len(rows))
    if inherited_usage_override is not None:
        inherited_usage = normalize_usage(inherited_usage_override)
    else:
        inherited_usage = (
            normalize_usage(rows[inherited_event_count - 1].get("total_token_usage"))
            if inherited_event_count
            else zero_usage()
        )
    previous_usage = dict(inherited_usage)
    total_usage = zero_usage()
    last_usage = zero_usage()
    rebased: list[dict[str, Any]] = []

    for row in rows[inherited_event_count:]:
        current_usage = normalize_usage(row.get("total_token_usage"))
        delta_usage = timeline_usage_delta(current_usage, previous_usage)
        previous_usage = current_usage
        total_usage = add_usage(total_usage, delta_usage)
        last_usage = delta_usage
        relative_row = dict(row)
        relative_row["total_token_usage"] = dict(total_usage)
        relative_row["last_token_usage"] = dict(delta_usage)
        rebased.append(relative_row)

    return rebased, total_usage, last_usage, inherited_usage


def pricing_for_timeline(
    timeline: list[dict[str, Any]],
    fallback_model: str,
    fallback_usage: dict[str, int] | None = None,
    fallback_timestamp: Any = None,
) -> dict[str, Any]:
    items: list[tuple[dict[str, int], str, Any, bool]] = []
    for row, _timestamp, _cumulative_usage, delta_usage in timeline_rows_with_deltas(timeline):
        if usage_has_tokens(delta_usage):
            items.append(
                (
                    delta_usage,
                    str(row.get("model") or fallback_model),
                    row.get("timestamp"),
                    True,
                )
            )

    if not items:
        items.append((normalize_usage(fallback_usage), fallback_model, fallback_timestamp, False))

    known = True
    total_parts = {
        key: 0.0
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
    }
    segments_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}

    for usage, model, timestamp, is_request_usage in items:
        request_input_tokens = max(int(usage.get("input_tokens", 0)), 0) if is_request_usage else None
        entry = price_entry_for_model(model, timestamp, request_input_tokens)
        if entry is None:
            known = False
            continue
        parts = usage_cost_parts(usage, entry["prices"])
        if parts is None:
            known = False
            continue
        for key, value in parts.items():
            total_parts[key] += value

        if not usage_has_tokens(usage):
            continue
        prices = entry["prices"]
        segment_key = (
            entry["model"],
            entry["effective_at"],
            entry["context_tier"],
            prices.get("input"),
            prices.get("cached_input"),
            prices.get("cache_write_input"),
            prices.get("output"),
        )
        segment = segments_by_key.setdefault(
            segment_key,
            {
                "model": entry["model"],
                "effective_at": entry["effective_at"],
                "context_tier": entry["context_tier"],
                "prices": dict(prices),
                "usage": zero_usage(),
                "estimated_cost_usd": 0.0,
                "estimated_cost_breakdown_usd": {
                    key: 0.0 for key in total_parts
                },
            },
        )
        segment["usage"] = add_usage(segment["usage"], usage)
        segment["estimated_cost_usd"] += total_cost_from_parts(parts)
        for key, value in parts.items():
            segment["estimated_cost_breakdown_usd"][key] += value

    segments = list(segments_by_key.values())
    for segment in segments:
        segment["estimated_cost_usd"] = round(segment["estimated_cost_usd"], 6)
        segment["estimated_cost_breakdown_usd"] = {
            key: round(value, 6)
            for key, value in segment["estimated_cost_breakdown_usd"].items()
        }

    return {
        "estimated_cost_usd": round(total_cost_from_parts(total_parts), 6) if known else None,
        "estimated_cost_breakdown_usd": (
            {key: round(value, 6) for key, value in total_parts.items()} if known else None
        ),
        "price_model_known": known,
        "applied_price_segments": segments,
    }


def utc_from_epoch(seconds: float | int | None) -> str | None:
    if seconds is None:
        return None
    try:
        return dt.datetime.fromtimestamp(float(seconds), tz=dt.UTC).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None


def utc_from_mtime(path: Path) -> str | None:
    try:
        return utc_from_epoch(path.stat().st_mtime)
    except OSError:
        return None


def utc_iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


def parse_local_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def local_range_bounds(start_date: str | None, end_date: str | None) -> tuple[dt.datetime, dt.datetime, str, str]:
    now_local = dt.datetime.now().astimezone()
    tzinfo = now_local.tzinfo
    start_day = parse_local_date(start_date) or now_local.date()
    end_day = parse_local_date(end_date) or start_day
    if end_day < start_day:
        start_day, end_day = end_day, start_day

    start_local = dt.datetime.combine(start_day, dt.time.min, tzinfo=tzinfo)
    if end_day >= now_local.date():
        end_local = now_local
    else:
        next_day = end_day + dt.timedelta(days=1)
        end_local = dt.datetime.combine(next_day, dt.time.min, tzinfo=tzinfo) - dt.timedelta(microseconds=1)
    return start_local.astimezone(dt.UTC), end_local.astimezone(dt.UTC), start_day.isoformat(), end_day.isoformat()


def local_period_bounds(
    period: str | None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> tuple[str, dt.datetime | None, dt.datetime, str | None, str | None]:
    key = period if period in PERIOD_KEYS or period == "custom" else "today"
    now_local = dt.datetime.now().astimezone()
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if key == "all":
        return key, None, now_local.astimezone(dt.UTC), None, None
    if key == "custom":
        start_at, end_at, start_key, end_key = local_range_bounds(start_date, end_date)
        return key, start_at, end_at, start_key, end_key
    if key == "7d":
        start_local = midnight - dt.timedelta(days=6)
    elif key == "30d":
        start_local = midnight - dt.timedelta(days=29)
    elif key == "week":
        start_local = midnight - dt.timedelta(days=midnight.weekday())
    elif key == "month":
        start_local = midnight.replace(day=1)
    else:
        start_local = midnight

    start_key = start_local.date().isoformat()
    end_key = now_local.date().isoformat()
    return key, start_local.astimezone(dt.UTC), now_local.astimezone(dt.UTC), start_key, end_key


def timestamp_in_range(value: Any, start_at: dt.datetime, end_at: dt.datetime) -> bool:
    timestamp = parse_timestamp(value)
    return timestamp is not None and start_at <= timestamp <= end_at


def clean_text(value: str, limit: int = 260) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def folder_name_from_path(value: str) -> str:
    text = str(value or "").strip().strip('"').rstrip("\\/")
    if not text:
        return ""
    parts = [part for part in re.split(r"[\\/]+", text) if part]
    return parts[-1] if parts else text


class ProjectInfo(NamedTuple):
    project: str
    project_root: str
    workspace_root: str
    project_branch: str
    is_git_worktree: bool


def _path_from_cwd(value: str) -> Path | None:
    text = str(value or "").strip().strip('"')
    if not text:
        return None
    if re.match(r"^[A-Za-z]:[\\/]", text):
        if platform.system() == "Windows":
            path = Path(text).expanduser()
            return path if path.exists() else None
        converted = windows_path_to_wsl_path(text)
        return converted if converted is not None and converted.exists() else None
    path = Path(text).expanduser()
    return path if path.exists() else None


def _git_output(cwd: Path, *args: str) -> str:
    git = shutil.which("git")
    if not git:
        return ""
    return run_text_quiet([git, "-C", str(cwd), *args])


def _git_common_dir(workspace: Path) -> Path | None:
    output = _git_output(workspace, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not output:
        return None
    try:
        return Path(output.splitlines()[-1]).expanduser().resolve()
    except OSError:
        return None


def _git_workspace_root(cwd: Path) -> Path | None:
    output = _git_output(cwd, "rev-parse", "--show-toplevel")
    if not output:
        return None
    try:
        return Path(output.splitlines()[-1]).expanduser().resolve()
    except OSError:
        return None


def _parse_git_worktree_list(output: str) -> tuple[Path | None, dict[str, str]]:
    main_workspace: Path | None = None
    branches: dict[str, str] = {}
    current_workspace: Path | None = None
    current_bare = False
    current_branch = ""

    def finish_entry() -> None:
        nonlocal main_workspace, current_workspace, current_bare, current_branch
        if current_workspace is None:
            return
        workspace_key = str(current_workspace)
        branches[workspace_key] = current_branch
        if main_workspace is None and not current_bare:
            main_workspace = current_workspace

    for line in output.splitlines():
        if not line.strip():
            finish_entry()
            current_workspace = None
            current_bare = False
            current_branch = ""
            continue
        if line.startswith("worktree "):
            finish_entry()
            current_bare = False
            current_branch = ""
            raw_path = line.removeprefix("worktree ").strip()
            try:
                current_workspace = Path(raw_path).expanduser().resolve()
            except OSError:
                current_workspace = None
        elif line == "bare":
            current_bare = True
        elif line.startswith("branch "):
            current_branch = line.removeprefix("branch ").strip().removeprefix("refs/heads/")

    finish_entry()
    return main_workspace, branches


def git_project_info(cwd: str) -> ProjectInfo:
    fallback_project = folder_name_from_path(cwd)
    fallback_root = str(cwd or "").strip()
    path = _path_from_cwd(cwd)
    if path is None:
        return ProjectInfo(fallback_project, fallback_root, fallback_root, "", False)

    workspace = _git_workspace_root(path)
    if workspace is None:
        root = str(path.resolve()) if path.exists() else fallback_root
        return ProjectInfo(folder_name_from_path(root), root, root, "", False)

    branch = _git_output(workspace, "branch", "--show-current")
    branch = branch.splitlines()[-1].strip() if branch else ""
    project_root = workspace
    is_worktree = False
    common_dir = _git_common_dir(workspace)
    if common_dir is not None:
        output = _git_output(workspace, "worktree", "list", "--porcelain")
        main_workspace, branches = _parse_git_worktree_list(output)
        workspace_key = str(workspace)
        if branches.get(workspace_key):
            branch = branches[workspace_key]
        if main_workspace is not None:
            project_root = main_workspace
            is_worktree = workspace != main_workspace

    project_root_text = str(project_root)
    return ProjectInfo(
        folder_name_from_path(project_root_text),
        project_root_text,
        str(workspace),
        branch,
        is_worktree,
    )


def safe_print(*values: Any) -> None:
    try:
        if sys.stdout is not None and not sys.stdout.closed:
            print(*values)
    except Exception:
        pass


def app_config_dir() -> Path:
    override = os.environ.get("COUSASH_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if system == "Windows":
        root = os.environ.get("APPDATA")
        return Path(root) / APP_NAME if root else Path.home() / "AppData" / "Roaming" / APP_NAME
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root) / APP_NAME if root else Path.home() / ".config" / APP_NAME


def remote_snapshots_dir() -> Path:
    return app_config_dir() / "remotes"


def parse_cache_path() -> Path:
    return app_config_dir() / "parsed-files-v2.sqlite3"


def safe_json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def run_text_quiet(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def mac_platform_uuid() -> str:
    output = run_text_quiet(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"])
    match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', output)
    return match.group(1).strip() if match else ""


def windows_machine_guid() -> str:
    output = run_text_quiet(
        [
            "reg",
            "query",
            r"HKLM\SOFTWARE\Microsoft\Cryptography",
            "/v",
            "MachineGuid",
        ]
    )
    match = re.search(r"MachineGuid\s+REG_\w+\s+([^\r\n]+)", output)
    if match:
        return match.group(1).strip()
    output = run_text_quiet(["powershell", "-NoProfile", "-Command", "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Cryptography').MachineGuid"])
    return output.splitlines()[-1].strip() if output else ""


def linux_machine_id() -> str:
    for path in (Path("/etc/machine-id"), Path("/var/lib/dbus/machine-id")):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def device_code_prefix() -> str:
    system = platform.system()
    if system == "Darwin":
        return "mac"
    if system == "Windows":
        return "win"
    if running_in_wsl():
        return "wsl"
    if system == "Linux":
        return "linux"
    return slugify_source_id(system or "device")


def stable_device_identity() -> str:
    system = platform.system()
    if system == "Darwin":
        value = mac_platform_uuid()
    elif system == "Windows":
        value = windows_machine_guid()
    else:
        value = linux_machine_id()
    return value.strip()


def fallback_device_seed() -> str:
    path = app_config_dir() / "device-seed.json"
    payload = read_json_file(path)
    if payload and isinstance(payload.get("seed"), str) and payload["seed"]:
        return payload["seed"]
    seed = hashlib.sha256(f"{time.time_ns()}:{os.urandom(16).hex()}".encode("utf-8")).hexdigest()
    safe_json_dump(path, {"seed": seed, "created_at": utc_iso(dt.datetime.now(dt.UTC))})
    return seed


def current_device_short_code() -> str:
    prefix = device_code_prefix()
    identity = stable_device_identity()
    if not identity:
        identity = fallback_device_seed()
    digest = hashlib.sha256(f"{prefix}:{identity}".encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"{prefix}-{digest}"


def default_device_label() -> str:
    node = platform.node().strip()
    system = platform.system() or "Device"
    if node:
        return node
    if system == "Darwin":
        return "Mac"
    if system == "Windows":
        return "Windows PC"
    if running_in_wsl():
        return "WSL"
    return system


def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("text", "message", "content"):
            if isinstance(content.get(key), str):
                return content[key]
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("text", "message", "content"):
                    value = item.get(key)
                    if isinstance(value, str):
                        parts.append(value)
                        break
        return "\n".join(parts)
    return ""


def is_synthetic_user_context(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("# AGENTS.md instructions for ") or stripped.startswith("<environment_context>")


FAST_ROLLOUT_MIN_BYTES = 4096
FAST_ROLLOUT_HEADER = re.compile(
    rb'^\{"timestamp":"(?P<timestamp>[0-9T:.+Z-]+)",'
    rb'"type":"(?P<outer>response_item|event_msg)",'
    rb'"payload":\{"type":"(?P<inner>[a-zA-Z0-9_-]+)"(?:,|\})'
)
FAST_IGNORED_ROLLOUT_TYPES = {
    ("response_item", "custom_tool_call_output"),
    ("response_item", "function_call_output"),
    ("response_item", "image_generation_call"),
    ("response_item", "reasoning"),
    ("response_item", "tool_search_output"),
    ("event_msg", "image_generation_end"),
}


class RolloutReadStats:
    def __init__(self) -> None:
        self.fast_skipped_line_count = 0
        self.fast_skipped_bytes = 0
        self.bytes_read = 0


def fast_ignored_rollout_projection(raw_line: bytes) -> dict[str, Any] | None:
    if len(raw_line) < FAST_ROLLOUT_MIN_BYTES or not raw_line.endswith((b"}}\n", b"}}\r\n")):
        return None
    match = FAST_ROLLOUT_HEADER.match(raw_line)
    if match is None:
        return None
    outer = match.group("outer").decode("ascii")
    inner = match.group("inner").decode("ascii")
    if (outer, inner) not in FAST_IGNORED_ROLLOUT_TYPES:
        return None
    return {
        "timestamp": match.group("timestamp").decode("ascii"),
        "type": outer,
        "payload": {"type": inner},
    }


def read_rollout_jsonl(
    path: Path,
    start_offset: int = 0,
    stats: RolloutReadStats | None = None,
    end_offset: int | None = None,
    *,
    full_payload: bool = False,
    with_source: bool = False,
) -> Iterator[dict[str, Any]]:
    stats = stats or RolloutReadStats()
    first_line = start_offset == 0
    if end_offset is None:
        end_offset = path.stat().st_size
    with path.open("rb") as handle:
        if start_offset:
            handle.seek(start_offset)
        remaining = max(0, end_offset - start_offset)
        line_number = 0
        while remaining:
            offset = handle.tell()
            raw_line = handle.readline(remaining)
            line_number += 1
            source = {"line": line_number, "offset": offset, "length": len(raw_line)}
            if not raw_line:
                break
            remaining -= len(raw_line)
            complete_line = raw_line.endswith(b"\n")
            projection = None if full_payload else fast_ignored_rollout_projection(raw_line)
            if projection is not None:
                stats.bytes_read += len(raw_line)
                stats.fast_skipped_line_count += 1
                stats.fast_skipped_bytes += len(raw_line)
                first_line = False
                if with_source:
                    projection["_source"] = source
                yield projection
                continue

            encoding = "utf-8-sig" if first_line else "utf-8"
            first_line = False
            line = raw_line.decode(encoding, errors="replace").strip()
            if not line:
                if complete_line:
                    stats.bytes_read += len(raw_line)
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                if not complete_line:
                    return
                stats.bytes_read += len(raw_line)
                yield {"__parse_error__": True, **({"_source": source} if with_source else {})}
                continue
            stats.bytes_read += len(raw_line)
            if isinstance(item, dict):
                if with_source:
                    item["_source"] = source
                yield item


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                rows.append({"__parse_error__": True})
                continue
            if isinstance(item, dict):
                rows.append(item)
    return rows


def first_session_meta_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= 32:
                    break
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if item.get("type") != "session_meta":
                    continue
                payload = item.get("payload")
                return payload if isinstance(payload, dict) else {}
    except OSError:
        return {}
    return {}


class CodexLogSource(NamedTuple):
    id: str
    label: str
    codex_home: Path


def slugify_source_id(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "codex"


def path_has_codex_logs(path: Path) -> bool:
    home = path.expanduser()
    return (
        (home / "sessions").exists()
        or (home / "archived_sessions").exists()
        or (home / "session_index.jsonl").exists()
    )


def running_in_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        release = platform.uname().release.lower()
    return "microsoft" in release or "wsl" in release


def windows_path_to_wsl_path(value: str) -> Path | None:
    text = value.strip().strip('"').replace("\r", "")
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
    if not match:
        return None
    drive = match.group(1).lower()
    rest = match.group(2).replace("\\", "/").strip("/")
    return Path("/mnt") / drive / rest


def windows_codex_home_candidates() -> list[Path]:
    candidates: list[Path] = []
    userprofile = run_text(["cmd.exe", "/c", "echo", "%USERPROFILE%"])
    if userprofile:
        profile = windows_path_to_wsl_path(userprofile.splitlines()[-1])
        if profile is not None:
            candidates.append(profile / ".codex")

    for username in (os.environ.get("USER"), os.environ.get("USERNAME")):
        if username:
            candidates.append(Path("/mnt/c/Users") / username / ".codex")

    if not any(path_has_codex_logs(path) for path in candidates):
        users_dir = Path("/mnt/c/Users")
        try:
            matches = [path for path in users_dir.glob("*/.codex") if path_has_codex_logs(path)]
        except OSError:
            matches = []
        if len(matches) == 1:
            candidates.extend(matches)

    seen: set[str] = set()
    deduped: list[Path] = []
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def label_for_codex_home(path: Path) -> str:
    text = str(path)
    if running_in_wsl():
        if text.startswith("/mnt/c/Users/"):
            return "Windows"
        return "WSL"
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system:
        return system
    return "Local"


def make_log_source(path: Path, label: str | None = None, source_id: str | None = None) -> CodexLogSource:
    resolved = path.expanduser().resolve()
    source_label = label or label_for_codex_home(resolved)
    return CodexLogSource(source_id or slugify_source_id(source_label), source_label, resolved)


def dedupe_codex_sources(sources: list[CodexLogSource]) -> list[CodexLogSource]:
    seen_paths: set[str] = set()
    seen_ids: set[str] = set()
    deduped: list[CodexLogSource] = []
    for source in sources:
        path_key = str(source.codex_home)
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)

        source_id = source.id
        if source_id in seen_ids:
            suffix = 2
            while f"{source_id}-{suffix}" in seen_ids:
                suffix += 1
            source_id = f"{source_id}-{suffix}"
        seen_ids.add(source_id)
        deduped.append(CodexLogSource(source_id, source.label, source.codex_home))
    return deduped


def codex_sources_from_homes(homes: list[Path]) -> list[CodexLogSource]:
    return dedupe_codex_sources([make_log_source(path) for path in homes])


def default_codex_sources(include_windows: bool = True) -> list[CodexLogSource]:
    local_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    sources = [make_log_source(local_home)]
    if include_windows and running_in_wsl():
        for path in windows_codex_home_candidates():
            if path_has_codex_logs(path):
                sources.append(make_log_source(path, "Windows", "windows"))
    return dedupe_codex_sources(sources)


def codex_source_payloads(sources: list[CodexLogSource]) -> list[dict[str, Any]]:
    return [
        {"id": source.id, "label": source.label, "codex_home": str(source.codex_home), "is_remote": False}
        for source in sources
    ]


def codex_home_display(sources: list[CodexLogSource]) -> str:
    if len(sources) == 1:
        return str(sources[0].codex_home)
    return " · ".join(f"{source.label}: {source.codex_home}" for source in sources)


def safe_device_code(value: Any) -> str:
    code = str(value or "").strip().lower()
    code = re.sub(r"[^a-z0-9_-]+", "-", code).strip("-")
    return code[:80]


def snapshot_session_key(session: dict[str, Any]) -> str:
    for key in ("session_id", "uid", "path"):
        value = session.get(key)
        if isinstance(value, str) and value:
            return value
    return hashlib.sha1(json.dumps(session, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def clone_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def normalize_usage_fields(row: dict[str, Any]) -> None:
    for key in (
        "total_token_usage",
        "last_token_usage",
        "branch_total_token_usage",
        "inherited_token_usage",
    ):
        if isinstance(row.get(key), dict):
            row[key] = normalize_usage(row[key])
    timeline = row.get("timeline")
    if isinstance(timeline, list):
        for item in timeline:
            if not isinstance(item, dict):
                continue
            for key in ("total_token_usage", "last_token_usage"):
                if isinstance(item.get(key), dict):
                    item[key] = normalize_usage(item[key])


def path_state_signature(path: Path) -> tuple[str, int | None, int | None]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), None, None)
    return (str(path), stat.st_mtime_ns, stat.st_size)


def file_stat_tuple(stat: os.stat_result) -> tuple[int, int, int, int]:
    return int(stat.st_dev), int(stat.st_ino), stat.st_mtime_ns, stat.st_size


def sqlite_file_identity(value: int) -> int | str:
    """Return an exact, SQLite-bindable representation of a file identity."""
    normalized = int(value)
    if -(1 << 63) <= normalized <= (1 << 63) - 1:
        return normalized
    return f"identity:{normalized}"


def file_identity_from_sqlite(value: object) -> int:
    if isinstance(value, str) and value.startswith("identity:"):
        return int(value.removeprefix("identity:"))
    return int(value)


def file_change_requires_retry(
    before: tuple[int, int, int, int],
    after: tuple[int, int, int, int],
    parsed_size: int,
) -> bool:
    before_device, before_inode, before_mtime_ns, before_size = before
    after_device, after_inode, after_mtime_ns, after_size = after
    if before_device != after_device or before_inode != after_inode:
        return True
    if after_size < before_size or after_size < parsed_size:
        return True
    return after_size == before_size and after_mtime_ns != before_mtime_ns


def file_parse_markers(path: Path, size: int) -> tuple[bool, str, str]:
    try:
        with path.open("rb") as handle:
            prefix = handle.read(min(PARSE_CACHE_SAMPLE_BYTES, size))
            if size:
                handle.seek(size - 1)
                append_safe = handle.read(1) == b"\n"
            else:
                append_safe = True
            tail_start = max(0, size - PARSE_CACHE_SAMPLE_BYTES)
            handle.seek(tail_start)
            tail = handle.read(size - tail_start)
    except OSError:
        return False, "", ""
    return (
        append_safe,
        hashlib.sha256(prefix).hexdigest(),
        hashlib.sha256(tail).hexdigest(),
    )


def file_matches_cached_prefix(
    path: Path,
    entry: FileParseCacheEntry,
    stat: os.stat_result,
) -> bool:
    if (
        not entry.append_safe
        or stat.st_size <= entry.size
        or int(stat.st_dev) != entry.device
        or int(stat.st_ino) != entry.inode
    ):
        return False
    try:
        with path.open("rb") as handle:
            prefix_length = min(PARSE_CACHE_SAMPLE_BYTES, entry.size)
            prefix = handle.read(prefix_length)
            tail_start = max(0, entry.size - PARSE_CACHE_SAMPLE_BYTES)
            handle.seek(tail_start)
            tail = handle.read(entry.size - tail_start)
    except OSError:
        return False
    return (
        hashlib.sha256(prefix).hexdigest() == entry.prefix_digest
        and hashlib.sha256(tail).hexdigest() == entry.tail_digest
    )


class RemoteSnapshotStore:
    def __init__(self, current_device_code: str | None = None, root: Path | None = None):
        self.current_device_code = safe_device_code(current_device_code or current_device_short_code())
        self.root = root or remote_snapshots_dir()

    def snapshot_path(self, device_code: str) -> Path:
        code = safe_device_code(device_code)
        if not code:
            raise ValueError("missing device short code")
        return self.root / f"{code}.json"

    def validate_snapshot(self, payload: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("snapshot must be a JSON object")
        if payload.get("schema") != SNAPSHOT_SCHEMA:
            raise ValueError("unsupported snapshot schema")
        try:
            version = int(payload.get("version") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("snapshot version is invalid") from exc
        if version > SNAPSHOT_VERSION:
            raise ValueError("snapshot version is newer than this dashboard")
        device = payload.get("device")
        snapshot = payload.get("snapshot")
        if not isinstance(device, dict) or not isinstance(snapshot, dict):
            raise ValueError("snapshot is missing device or data")
        code = safe_device_code(device.get("short_code"))
        if not code:
            raise ValueError("snapshot is missing device short code")
        sessions = snapshot.get("sessions")
        details = snapshot.get("details_by_uid")
        if not isinstance(sessions, list) or not isinstance(details, dict):
            raise ValueError("snapshot is missing session data")
        return code, device, snapshot

    def read_remote(self, device_code: str) -> dict[str, Any] | None:
        return read_json_file(self.snapshot_path(device_code))

    def read_all(self) -> list[dict[str, Any]]:
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError:
            return []
        payloads: list[dict[str, Any]] = []
        for path in paths:
            payload = read_json_file(path)
            if not payload:
                continue
            try:
                code, _device, _snapshot = self.validate_snapshot(payload)
            except ValueError:
                continue
            payloads.append(payload)
        return payloads

    def state_signature(self) -> tuple[tuple[str, int | None, int | None], ...]:
        try:
            paths = sorted(self.root.glob("*.json"))
        except OSError:
            return ()
        return tuple(path_state_signature(path) for path in paths)

    def list_remotes(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for payload in self.read_all():
            try:
                code, device, snapshot = self.validate_snapshot(payload)
            except ValueError:
                continue
            sessions = snapshot.get("sessions") if isinstance(snapshot.get("sessions"), list) else []
            usage = normalize_usage((snapshot.get("summary") or {}).get("usage") if isinstance(snapshot.get("summary"), dict) else None)
            rows.append(
                {
                    "device_short_code": code,
                    "label": str(device.get("label") or code),
                    "platform": str(device.get("platform") or ""),
                    "hostname": str(device.get("hostname") or ""),
                    "session_count": len(sessions),
                    "usage": usage,
                    "imported_at": payload.get("imported_at") or "",
                    "exported_at": payload.get("exported_at") or "",
                    "generated_at": snapshot.get("generated_at") or "",
                }
            )
        return sorted(rows, key=lambda row: str(row.get("label") or row.get("device_short_code")))

    def import_snapshot(
        self,
        incoming: dict[str, Any],
        label: str | None = None,
        allow_current_device: bool = False,
    ) -> dict[str, Any]:
        code, incoming_device, incoming_snapshot = self.validate_snapshot(incoming)
        if code == self.current_device_code and not allow_current_device:
            return {
                "ok": False,
                "needs_confirmation": True,
                "reason": "current_device",
                "device_short_code": code,
                "suggested_label": str(incoming_device.get("label") or code),
            }

        existing = self.read_remote(code)
        existing_device: dict[str, Any] = {}
        existing_snapshot: dict[str, Any] = {}
        if existing:
            try:
                _existing_code, existing_device, existing_snapshot = self.validate_snapshot(existing)
            except ValueError:
                existing_device = {}
                existing_snapshot = {}

        new_label = clean_text(label or str(existing_device.get("label") or incoming_device.get("label") or code), 120)
        if not existing and not label:
            return {
                "ok": False,
                "needs_label": True,
                "device_short_code": code,
                "suggested_label": new_label,
                "platform": incoming_device.get("platform") or "",
                "hostname": incoming_device.get("hostname") or "",
            }

        merged_snapshot = self.merge_snapshots(existing_snapshot, incoming_snapshot)
        now = utc_iso(dt.datetime.now(dt.UTC))
        stored = {
            "schema": SNAPSHOT_SCHEMA,
            "version": SNAPSHOT_VERSION,
            "device": {
                **{key: value for key, value in incoming_device.items() if isinstance(key, str)},
                "short_code": code,
                "label": new_label,
            },
            "exported_at": incoming.get("exported_at") or incoming_snapshot.get("generated_at") or now,
            "imported_at": now,
            "snapshot": merged_snapshot,
        }
        safe_json_dump(self.snapshot_path(code), stored)
        return {"ok": True, "remote": self.remote_metadata(stored), "created": not bool(existing)}

    def merge_snapshots(self, existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        existing_sessions = existing.get("sessions") if isinstance(existing.get("sessions"), list) else []
        incoming_sessions = incoming.get("sessions") if isinstance(incoming.get("sessions"), list) else []
        existing_details = existing.get("details_by_uid") if isinstance(existing.get("details_by_uid"), dict) else {}
        incoming_details = incoming.get("details_by_uid") if isinstance(incoming.get("details_by_uid"), dict) else {}

        by_key: dict[str, dict[str, Any]] = {}
        detail_by_uid: dict[str, dict[str, Any]] = {}
        for session in existing_sessions:
            if isinstance(session, dict):
                cloned = clone_json(session)
                by_key[snapshot_session_key(cloned)] = cloned
                uid = cloned.get("uid")
                if isinstance(uid, str) and isinstance(existing_details.get(uid), dict):
                    detail_by_uid[uid] = clone_json(existing_details[uid])

        for session in incoming_sessions:
            if not isinstance(session, dict):
                continue
            cloned = clone_json(session)
            key = snapshot_session_key(cloned)
            old = by_key.get(key)
            old_uid = old.get("uid") if isinstance(old, dict) else None
            if isinstance(old_uid, str):
                detail_by_uid.pop(old_uid, None)
            by_key[key] = cloned
            uid = cloned.get("uid")
            if isinstance(uid, str) and isinstance(incoming_details.get(uid), dict):
                detail_by_uid[uid] = clone_json(incoming_details[uid])

        sessions = list(by_key.values())
        sessions.sort(key=lambda row: str(row.get("end_at") or row.get("updated_at") or row.get("start_at") or ""), reverse=True)
        generated_at = incoming.get("generated_at") or utc_iso(dt.datetime.now(dt.UTC))
        return {
            "generated_at": generated_at,
            "codex_home": incoming.get("codex_home") or existing.get("codex_home") or "",
            "codex_sources": incoming.get("codex_sources") if isinstance(incoming.get("codex_sources"), list) else [],
            "sessions": sessions,
            "details_by_uid": detail_by_uid,
            "summary": CodexUsageAnalyzer.build_summary_static(sessions),
            "daily_usage": CodexUsageAnalyzer.build_daily_usage_static(detail_by_uid.values()),
        }

    def remote_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        code, device, snapshot = self.validate_snapshot(payload)
        sessions = snapshot.get("sessions") if isinstance(snapshot.get("sessions"), list) else []
        summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
        return {
            "device_short_code": code,
            "label": str(device.get("label") or code),
            "platform": str(device.get("platform") or ""),
            "hostname": str(device.get("hostname") or ""),
            "session_count": len(sessions),
            "usage": normalize_usage(summary.get("usage")),
            "imported_at": payload.get("imported_at") or "",
            "exported_at": payload.get("exported_at") or "",
            "generated_at": snapshot.get("generated_at") or "",
        }

    def rename_remote(self, device_code: str, label: str) -> dict[str, Any]:
        code = safe_device_code(device_code)
        payload = self.read_remote(code)
        if not payload:
            raise FileNotFoundError(code)
        validated_code, device, _snapshot = self.validate_snapshot(payload)
        device["label"] = clean_text(label, 120) or validated_code
        payload["device"] = device
        safe_json_dump(self.snapshot_path(validated_code), payload)
        return self.remote_metadata(payload)

    def delete_remote(self, device_code: str) -> None:
        path = self.snapshot_path(device_code)
        if not path.exists():
            raise FileNotFoundError(device_code)
        path.unlink()

    def transformed_sessions(self) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[dict[str, str]]]:
        sessions: list[dict[str, Any]] = []
        details: dict[str, dict[str, Any]] = {}
        sources: list[dict[str, str]] = []
        for payload in self.read_all():
            try:
                code, device, snapshot = self.validate_snapshot(payload)
            except ValueError:
                continue
            label = str(device.get("label") or code)
            source_id = f"remote-{code}"
            sources.append({"id": source_id, "label": label, "codex_home": f"remote:{code}", "is_remote": True})
            raw_details = snapshot.get("details_by_uid") if isinstance(snapshot.get("details_by_uid"), dict) else {}
            for session in snapshot.get("sessions", []):
                if not isinstance(session, dict):
                    continue
                transformed = self.transform_row(session, code, label, source_id, payload)
                raw_uid = session.get("uid")
                raw_detail = raw_details.get(raw_uid) if isinstance(raw_uid, str) else None
                if isinstance(raw_detail, dict):
                    transformed_detail = self.transform_row(
                        raw_detail,
                        code,
                        label,
                        source_id,
                        payload,
                        transformed["uid"],
                    )
                    remote_timeline = transformed_detail.get("timeline")
                    timeline_rows: list[dict[str, Any]] = []
                    if isinstance(remote_timeline, list):
                        timeline_rows = [
                            row
                            for row in remote_timeline
                            if isinstance(row, dict)
                            and usage_has_tokens(normalize_usage(row.get("total_token_usage")))
                        ]
                    can_reprice = bool(timeline_rows) and all(
                        isinstance(row.get("model"), str) and bool(row.get("model"))
                        for row in timeline_rows
                    )
                    if can_reprice:
                        pricing = pricing_for_timeline(
                            remote_timeline,
                            str(transformed_detail.get("model") or transformed.get("model") or ""),
                            normalize_usage(
                                transformed_detail.get("total_token_usage")
                                or transformed.get("total_token_usage")
                            ),
                            transformed_detail.get("end_at") or transformed.get("end_at"),
                        )
                        transformed_detail.update(pricing)
                        for key in (
                            "estimated_cost_usd",
                            "estimated_cost_breakdown_usd",
                            "price_model_known",
                        ):
                            transformed[key] = pricing[key]
                    else:
                        for key in (
                            "estimated_cost_usd",
                            "estimated_cost_breakdown_usd",
                            "price_model_known",
                        ):
                            transformed_detail[key] = transformed.get(key)
                        transformed_detail.setdefault("applied_price_segments", [])
                    details[transformed["uid"]] = transformed_detail
                sessions.append({key: transformed.get(key) for key in SUMMARY_KEYS})
        return sessions, details, sources

    def transform_row(
        self,
        row: dict[str, Any],
        code: str,
        label: str,
        source_id: str,
        payload: dict[str, Any],
        forced_uid: str | None = None,
    ) -> dict[str, Any]:
        raw_uid = str(row.get("uid") or row.get("session_id") or row.get("path") or "")
        uid = forced_uid or hashlib.sha1(f"{code}:{raw_uid}".encode("utf-8", errors="replace")).hexdigest()[:16]
        transformed = clone_json(row)
        normalize_usage_fields(transformed)
        transformed["uid"] = uid
        transformed["environment"] = label
        transformed["environment_id"] = source_id
        transformed["is_remote"] = True
        transformed["remote_device_short_code"] = code
        transformed["remote_imported_at"] = payload.get("imported_at") or ""
        transformed["remote_exported_at"] = payload.get("exported_at") or ""
        transformed["codex_home"] = f"remote:{code}"
        return transformed


class FileParseCacheEntry(NamedTuple):
    mtime_ns: int
    size: int
    device: int
    inode: int
    summary: dict[str, Any]
    detail: dict[str, Any]
    append_safe: bool
    prefix_digest: str
    tail_digest: str


class PersistentParseCache:
    def __init__(self, path: Path | None = None):
        self.path = path or parse_cache_path()
        self._lock = threading.RLock()
        self._connection: sqlite3.Connection | None = None
        self._disabled = os.environ.get("COUSASH_DISABLE_PARSE_CACHE") == "1"

    @staticmethod
    def encode_payload(value: dict[str, Any]) -> bytes:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return zlib.compress(raw, level=1)

    @staticmethod
    def decode_payload(value: bytes) -> dict[str, Any]:
        decoded = json.loads(zlib.decompress(value).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("cached payload is not an object")
        return decoded

    def connection(self) -> sqlite3.Connection | None:
        if self._disabled:
            return None
        with self._lock:
            if self._connection is not None:
                return self._connection
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if os.name != "nt":
                    os.chmod(self.path.parent, 0o700)
                connection = sqlite3.connect(self.path, timeout=10.0, check_same_thread=False)
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA synchronous=NORMAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS parsed_files (
                        cache_key TEXT PRIMARY KEY,
                        parser_version INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        size INTEGER NOT NULL,
                        device INTEGER NOT NULL,
                        inode INTEGER NOT NULL,
                        append_safe INTEGER NOT NULL,
                        prefix_digest TEXT NOT NULL,
                        tail_digest TEXT NOT NULL,
                        summary_blob BLOB NOT NULL,
                        detail_blob BLOB NOT NULL,
                        updated_at_ns INTEGER NOT NULL
                    )
                    """
                )
                connection.execute(
                    "DELETE FROM parsed_files WHERE parser_version != ?",
                    (PARSE_CACHE_VERSION,),
                )
                connection.commit()
                if os.name != "nt":
                    os.chmod(self.path, 0o600)
            except (OSError, sqlite3.Error):
                self._disabled = True
                try:
                    connection.close()
                except (NameError, sqlite3.Error):
                    pass
                return None
            self._connection = connection
            return connection

    def get(self, cache_key: str) -> FileParseCacheEntry | None:
        connection = self.connection()
        if connection is None:
            return None
        with self._lock:
            try:
                row = connection.execute(
                    """
                    SELECT mtime_ns, size, device, inode, append_safe, prefix_digest, tail_digest,
                           summary_blob, detail_blob
                    FROM parsed_files
                    WHERE cache_key = ? AND parser_version = ?
                    """,
                    (cache_key, PARSE_CACHE_VERSION),
                ).fetchone()
                if row is None:
                    return None
                return FileParseCacheEntry(
                    int(row[0]),
                    int(row[1]),
                    file_identity_from_sqlite(row[2]),
                    file_identity_from_sqlite(row[3]),
                    self.decode_payload(row[7]),
                    self.decode_payload(row[8]),
                    bool(row[4]),
                    str(row[5]),
                    str(row[6]),
                )
            except (sqlite3.Error, UnicodeDecodeError, ValueError, zlib.error, json.JSONDecodeError):
                try:
                    connection.execute("DELETE FROM parsed_files WHERE cache_key = ?", (cache_key,))
                    connection.commit()
                except sqlite3.Error:
                    pass
                return None

    def is_empty(self) -> bool:
        connection = self.connection()
        if connection is None:
            return True
        with self._lock:
            try:
                return connection.execute(
                    "SELECT 1 FROM parsed_files WHERE parser_version = ? LIMIT 1",
                    (PARSE_CACHE_VERSION,),
                ).fetchone() is None
            except sqlite3.Error:
                return True

    def put(self, cache_key: str, entry: FileParseCacheEntry) -> None:
        self.put_many([(cache_key, entry)])

    def put_many(self, entries: list[tuple[str, FileParseCacheEntry]]) -> None:
        if not entries:
            return
        connection = self.connection()
        if connection is None:
            return
        updated_at_ns = time.time_ns()
        try:
            rows = [
                (
                    cache_key,
                    PARSE_CACHE_VERSION,
                    entry.mtime_ns,
                    entry.size,
                    sqlite_file_identity(entry.device),
                    sqlite_file_identity(entry.inode),
                    int(entry.append_safe),
                    entry.prefix_digest,
                    entry.tail_digest,
                    self.encode_payload(entry.summary),
                    self.encode_payload(entry.detail),
                    updated_at_ns,
                )
                for cache_key, entry in entries
            ]
        except (OSError, TypeError, ValueError):
            return
        with self._lock:
            try:
                connection.executemany(
                    """
                    INSERT INTO parsed_files (
                        cache_key, parser_version, mtime_ns, size, device, inode, append_safe,
                        prefix_digest, tail_digest, summary_blob, detail_blob, updated_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        parser_version = excluded.parser_version,
                        mtime_ns = excluded.mtime_ns,
                        size = excluded.size,
                        device = excluded.device,
                        inode = excluded.inode,
                        append_safe = excluded.append_safe,
                        prefix_digest = excluded.prefix_digest,
                        tail_digest = excluded.tail_digest,
                        summary_blob = excluded.summary_blob,
                        detail_blob = excluded.detail_blob,
                        updated_at_ns = excluded.updated_at_ns
                    """,
                    rows,
                )
                connection.commit()
            except (OSError, sqlite3.Error, TypeError, ValueError):
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass
                return

    def prune(self, valid_keys: set[str], owned_roots: set[str]) -> None:
        connection = self.connection()
        if connection is None:
            return
        normalized_roots = {
            os.path.normcase(os.path.abspath(root))
            for root in owned_roots
        }

        def belongs_to_owned_root(cache_key: str) -> bool:
            parts = cache_key.split(":", 2)
            if len(parts) != 3:
                return False
            path = os.path.normcase(os.path.abspath(parts[2]))
            for root in normalized_roots:
                try:
                    if os.path.commonpath((path, root)) == root:
                        return True
                except ValueError:
                    continue
            return False

        with self._lock:
            try:
                cached_keys = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT cache_key FROM parsed_files WHERE parser_version = ?",
                        (PARSE_CACHE_VERSION,),
                    )
                }
                stale_keys = {
                    cache_key
                    for cache_key in cached_keys - valid_keys
                    if belongs_to_owned_root(cache_key)
                }
                if not stale_keys:
                    return
                connection.executemany(
                    "DELETE FROM parsed_files WHERE cache_key = ?",
                    [(cache_key,) for cache_key in stale_keys],
                )
                connection.commit()
            except sqlite3.Error:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
            self._connection = None


class SnapshotStaleError(LookupError):
    pass


_PARSE_WORKER_ANALYZERS: dict[tuple[str, str, str], "CodexUsageAnalyzer"] = {}


def initialize_parse_worker() -> None:
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (AttributeError, OSError, ValueError):
        pass


def parse_rollout_worker(
    job: dict[str, Any],
) -> dict[str, Any]:
    index = int(job["index"])
    source_id = str(job["source_id"])
    source_label = str(job["source_label"])
    codex_home = str(job["codex_home"])
    path_text = str(job["path"])
    source = str(job["source"])
    worker_key = (source_id, source_label, codex_home)
    analyzer = _PARSE_WORKER_ANALYZERS.get(worker_key)
    log_source = CodexLogSource(source_id, source_label, Path(codex_home))
    if analyzer is None:
        analyzer = CodexUsageAnalyzer(
            [log_source],
            resolve_project_info=False,
            parallel_workers=0,
        )
        _PARSE_WORKER_ANALYZERS[worker_key] = analyzer
    path = Path(path_text)
    try:
        before = path.stat()
        summary, detail = analyzer.parse_file(
            path,
            source,
            log_source,
            end_offset=before.st_size,
        )
        after = path.stat()
    except OSError:
        return {"index": index, "error": "file_unavailable"}
    return {
        "index": index,
        "summary": summary,
        "detail": detail,
        "before_state": file_stat_tuple(before),
        "after_state": file_stat_tuple(after),
    }


class CodexUsageAnalyzer:
    def __init__(
        self,
        codex_home: Path | list[Path] | list[CodexLogSource],
        remote_store: RemoteSnapshotStore | None = None,
        persistent_cache: PersistentParseCache | None = None,
        resolve_project_info: bool = True,
        parallel_workers: int = 0,
    ):
        if isinstance(codex_home, list):
            if codex_home and isinstance(codex_home[0], CodexLogSource):
                sources = dedupe_codex_sources(codex_home)
            else:
                sources = codex_sources_from_homes([Path(item) for item in codex_home])
        else:
            sources = codex_sources_from_homes([codex_home])
        if not sources:
            sources = codex_sources_from_homes([Path.home() / ".codex"])
        self.codex_sources = sources
        self.codex_home = sources[0].codex_home
        self.codex_home_display = codex_home_display(sources)
        self.remote_store = remote_store
        self.persistent_cache = persistent_cache
        self.resolve_project_info = resolve_project_info
        self.parallel_workers = max(0, min(int(parallel_workers), 4))
        self._process_pool: concurrent.futures.ProcessPoolExecutor | None = None
        self._parallel_disabled = False
        self._cache: dict[str, FileParseCacheEntry] = {}
        self.cache_metrics = {
            "memory_hits": 0,
            "persistent_hits": 0,
            "full_parses": 0,
            "incremental_parses": 0,
            "incremental_bytes": 0,
            "parallel_files": 0,
        }
        self._pending_persistent_entries: dict[str, FileParseCacheEntry] = {}
        self._snapshot_cache_signature: tuple[Any, ...] | None = None
        self._snapshot_cache: dict[str, Any] | None = None
        self._period_cache: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
        self._bounded_snapshot_cache: dict[
            tuple[str, str | None, str | None, bool],
            tuple[tuple[Any, ...], dict[str, Any]],
        ] = {}
        self._project_info_cache: dict[str, ProjectInfo] = {}
        self._session_meta_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}
        self._last_pruned_cache_keys: frozenset[str] | None = None
        self._scan_lock = threading.RLock()
        self._published_lock = threading.Lock()
        self._published_snapshots: dict[str, dict[str, Any]] = {}
        self._session_payload_cache: dict[str, bytes] = {}

    def publish_snapshot(
        self,
        snapshot: dict[str, Any],
        replaced: list[dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        published = {**snapshot, "snapshot_token": secrets.token_urlsafe(16)}
        with self._published_lock:
            for old_snapshot in replaced or []:
                if old_snapshot is None:
                    continue
                old_token = old_snapshot.get("snapshot_token")
                if isinstance(old_token, str):
                    self._published_snapshots.pop(old_token, None)
                    self._session_payload_cache.pop(old_token, None)
            self._published_snapshots[published["snapshot_token"]] = published
        return published

    def unpublish_snapshot(self, snapshot: dict[str, Any] | None) -> None:
        if snapshot is None:
            return
        token = snapshot.get("snapshot_token")
        if not isinstance(token, str):
            return
        with self._published_lock:
            self._published_snapshots.pop(token, None)
            self._session_payload_cache.pop(token, None)

    def session_payload_bytes(
        self,
        snapshot: dict[str, Any],
        payload: dict[str, Any],
    ) -> bytes:
        token = str(snapshot.get("snapshot_token") or "")
        if token:
            with self._published_lock:
                cached = (
                    self._session_payload_cache.get(token)
                    if self._published_snapshots.get(token) is snapshot
                    else None
                )
            if cached is not None:
                return cached
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if not token:
            return body
        with self._published_lock:
            if self._published_snapshots.get(token) is not snapshot:
                return body
            return self._session_payload_cache.setdefault(token, body)

    def load_session_titles(self, codex_home: Path | None = None) -> dict[str, str]:
        titles: dict[str, str] = {}
        index_path = (codex_home or self.codex_home) / "session_index.jsonl"
        if not index_path.exists():
            return titles

        try:
            for item in read_jsonl(index_path):
                session_id = item.get("id")
                title = item.get("thread_name")
                if isinstance(session_id, str) and isinstance(title, str) and title.strip():
                    titles[session_id] = clean_text(title, 180)
        except OSError:
            return titles
        return titles

    def resolved_path_key(self, path: Path) -> str:
        return str(path)

    def file_cache_key(self, log_source: CodexLogSource, path: Path, source: str) -> str:
        return f"{log_source.id}:{source}:{self.resolved_path_key(path)}"

    def prune_parse_cache(
        self,
        files: list[tuple[CodexLogSource, Path, str]],
    ) -> None:
        valid_keys = frozenset(
            self.file_cache_key(log_source, path, source)
            for log_source, path, source in files
        )
        if valid_keys == self._last_pruned_cache_keys:
            return
        self._last_pruned_cache_keys = valid_keys
        for cache_key in tuple(self._cache):
            if cache_key not in valid_keys:
                self._cache.pop(cache_key, None)
        if self.persistent_cache is not None:
            owned_roots = {
                str(log_source.codex_home / directory)
                for log_source in self.codex_sources
                for directory in ("sessions", "archived_sessions")
            }
            self.persistent_cache.prune(set(valid_keys), owned_roots)

    def cached_session_meta(self, path: Path) -> dict[str, Any]:
        path_key = self.resolved_path_key(path)
        try:
            stat = path.stat()
        except OSError:
            return {}
        cached = self._session_meta_cache.get(path_key)
        if cached is not None and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            return cached[2]
        payload = first_session_meta_payload(path)
        self._session_meta_cache[path_key] = (stat.st_mtime_ns, stat.st_size, payload)
        return payload

    def iter_session_files(self) -> list[tuple[CodexLogSource, Path, str]]:
        files: list[tuple[CodexLogSource, Path, str]] = []
        for log_source in self.codex_sources:
            sessions_dir = log_source.codex_home / "sessions"
            archived_dir = log_source.codex_home / "archived_sessions"

            if sessions_dir.exists():
                for path in sessions_dir.rglob("*.jsonl"):
                    files.append((log_source, path, "active"))
            if archived_dir.exists():
                for path in archived_dir.glob("*.jsonl"):
                    files.append((log_source, path, "archived"))

        files.sort(key=lambda item: item[1].stat().st_mtime if item[1].exists() else 0, reverse=True)
        return files

    def scan_signature(self, files: list[tuple[CodexLogSource, Path, str]], include_remotes: bool) -> tuple[Any, ...]:
        file_signature = tuple(
            (log_source.id, source, *path_state_signature(path))
            for log_source, path, source in files
        )
        title_signature = tuple(
            (log_source.id, *path_state_signature(log_source.codex_home / "session_index.jsonl"))
            for log_source in self.codex_sources
        )
        remote_signature = self.remote_store.state_signature() if include_remotes and self.remote_store is not None else ()
        return (file_signature, title_signature, remote_signature)

    def scan(
        self,
        period: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_remotes: bool = True,
    ) -> dict[str, Any]:
        with self._scan_lock:
            return self._scan_locked(period, start_date, end_date, include_remotes)

    def _scan_locked(
        self,
        period: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_remotes: bool = True,
    ) -> dict[str, Any]:
        all_files = self.iter_session_files()
        self.prune_parse_cache(all_files)
        files = all_files
        if period:
            key, start_at, _end_at, start_key, end_key = local_period_bounds(period, start_date, end_date)
            if start_at is not None:
                files = self.files_modified_since(files, start_at)
                files = self.files_with_fork_dependencies(files, all_files)
                signature = self.scan_signature(files, include_remotes)
                cache_key = (key, start_key, end_key, include_remotes)
                cached = self._bounded_snapshot_cache.get(cache_key)
                if cached is not None and cached[0] == signature:
                    return cached[1]

                snapshot = self.build_snapshot(files, include_remotes, include_daily_usage=False)
                snapshot = self.filter_snapshot_by_period(snapshot, key, start_key, end_key)
                snapshot = self.publish_snapshot(snapshot, [cached[1] if cached is not None else None])
                self._bounded_snapshot_cache[cache_key] = (signature, snapshot)
                if len(self._bounded_snapshot_cache) > 16:
                    evicted = self._bounded_snapshot_cache.pop(next(iter(self._bounded_snapshot_cache)))
                    self.unpublish_snapshot(evicted[1])
                return snapshot

        signature = self.scan_signature(files, include_remotes)
        if self._snapshot_cache_signature != signature or self._snapshot_cache is None:
            old_snapshots = [self._snapshot_cache, *self._period_cache.values()]
            self._snapshot_cache = self.publish_snapshot(
                self.build_snapshot(files, include_remotes),
                old_snapshots,
            )
            self._snapshot_cache_signature = signature
            self._period_cache = {}

        snapshot = self._snapshot_cache
        if period:
            key, _start_at, _end_at, _start_key, _end_key = local_period_bounds(
                period,
                start_date,
                end_date,
            )
            if key == "all":
                return snapshot
            cache_key = (period, start_date, end_date)
            cached = self._period_cache.get(cache_key)
            if cached is None:
                cached = self.publish_snapshot(
                    self.filter_snapshot_by_period(snapshot, period, start_date, end_date)
                )
                self._period_cache[cache_key] = cached
            return cached
        return snapshot

    @staticmethod
    def files_modified_since(
        files: list[tuple[CodexLogSource, Path, str]],
        start_at: dt.datetime,
    ) -> list[tuple[CodexLogSource, Path, str]]:
        cutoff_ns = int(start_at.timestamp() * 1_000_000_000)
        candidates: list[tuple[CodexLogSource, Path, str]] = []
        for item in files:
            try:
                if item[1].stat().st_mtime_ns >= cutoff_ns:
                    candidates.append(item)
            except OSError:
                continue
        return candidates

    def files_with_fork_dependencies(
        self,
        candidates: list[tuple[CodexLogSource, Path, str]],
        all_files: list[tuple[CodexLogSource, Path, str]],
    ) -> list[tuple[CodexLogSource, Path, str]]:
        metadata_by_path: dict[str, dict[str, Any]] = {}
        files_by_thread: dict[tuple[str, str], tuple[CodexLogSource, Path, str]] = {}
        for item in all_files:
            log_source, path, _source = item
            path_key = self.resolved_path_key(path)
            payload = self.cached_session_meta(path)
            metadata_by_path[path_key] = payload
            session_id = payload.get("id") or payload.get("session_id")
            if isinstance(session_id, str) and session_id:
                files_by_thread.setdefault((log_source.id, session_id), item)

        selected = {self.resolved_path_key(item[1]): item for item in candidates}
        queue = list(candidates)
        while queue:
            log_source, path, _source = queue.pop()
            payload = metadata_by_path.get(self.resolved_path_key(path), {})
            forked_from_id = payload.get("forked_from_id")
            if not isinstance(forked_from_id, str) or not forked_from_id:
                continue
            dependency = files_by_thread.get((log_source.id, forked_from_id))
            if dependency is None:
                continue
            dependency_key = self.resolved_path_key(dependency[1])
            if dependency_key in selected:
                continue
            selected[dependency_key] = dependency
            queue.append(dependency)

        return [item for item in all_files if self.resolved_path_key(item[1]) in selected]

    @staticmethod
    def normalize_subagent_usage(
        local_rows: list[tuple[dict[str, Any], dict[str, Any]]],
    ) -> None:
        details_by_thread: dict[tuple[str, str], dict[str, Any]] = {}
        raw_timelines: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for _summary, detail in local_rows:
            environment_id = str(detail.get("environment_id") or "")
            session_id = str(detail.get("session_id") or "")
            if not session_id:
                continue
            key = (environment_id, session_id)
            details_by_thread.setdefault(key, detail)
            timeline = detail.get("timeline")
            if key not in raw_timelines and isinstance(timeline, list):
                raw_timelines[key] = timeline

        for summary, detail in local_rows:
            if not (detail.get("is_subagent") or detail.get("forked_from_id")):
                continue

            environment_id = str(detail.get("environment_id") or "")
            match_source_id = str(
                detail.get("forked_from_id") or detail.get("parent_thread_id") or ""
            )
            child_timeline = detail.get("timeline")
            if not isinstance(child_timeline, list):
                continue

            parent_key = (environment_id, match_source_id)
            parent_detail = details_by_thread.get(parent_key)
            parent_timeline = raw_timelines.get(parent_key)
            fork_at = parse_timestamp(detail.get("created_at"))
            parent_timeline_at_fork = parent_timeline
            if fork_at is not None and isinstance(parent_timeline, list):
                parent_timeline_at_fork = [
                    row
                    for row in parent_timeline
                    if (
                        (parent_timestamp := parse_timestamp(row.get("timestamp"))) is not None
                        and parent_timestamp <= fork_at
                    )
                ]
            inherited_event_count = inherited_timeline_prefix_length(
                child_timeline,
                parent_timeline_at_fork,
            )

            usage_before_fork = zero_usage()
            if isinstance(parent_timeline_at_fork, list):
                for parent_row in parent_timeline_at_fork:
                    usage_before_fork = normalize_usage(parent_row.get("total_token_usage"))

            inherited_override: dict[str, int] | None = None
            resolved = False
            if inherited_event_count:
                resolved = True
            elif not detail.get("forked_from_id"):
                inherited_override = zero_usage()
                resolved = True
            elif parent_detail is not None:
                if not child_timeline or not usage_has_tokens(usage_before_fork):
                    inherited_override = zero_usage()
                    resolved = True
                else:
                    first_total = normalize_usage(child_timeline[0].get("total_token_usage"))
                    first_last = normalize_usage(child_timeline[0].get("last_token_usage"))
                    if first_total == first_last:
                        inherited_override = zero_usage()
                        resolved = True
                    elif timeline_usage_delta(first_total, usage_before_fork) == first_last:
                        inherited_override = usage_before_fork
                        resolved = True
            elif not child_timeline:
                inherited_override = zero_usage()
                resolved = True

            detail["fork_usage_resolved"] = resolved
            if not resolved:
                detail["timeline"] = []
                detail["total_token_usage"] = zero_usage()
                detail["last_token_usage"] = zero_usage()
                detail["estimated_cost_usd"] = None
                detail["estimated_cost_breakdown_usd"] = None
                detail["price_model_known"] = False
                detail["applied_price_segments"] = []
                detail["cached_input_percent"] = None
                detail["token_event_count"] = 0
                summary.update({key: detail.get(key) for key in SUMMARY_KEYS})
                continue

            rebased, total_usage, last_usage, inherited_usage = rebase_timeline_after_prefix(
                child_timeline,
                inherited_event_count,
                inherited_override,
            )
            detail["timeline"] = rebased
            detail["total_token_usage"] = total_usage
            detail["last_token_usage"] = last_usage
            detail["inherited_token_usage"] = inherited_usage
            detail["inherited_token_event_count"] = inherited_event_count

            inherited_cutoff = None
            if inherited_event_count:
                inherited_cutoff = parse_timestamp(
                    child_timeline[inherited_event_count - 1].get("timestamp")
                )
            if inherited_cutoff is not None:
                detail["tasks"] = [
                    task
                    for task in detail.get("tasks", [])
                    if (
                        (task_timestamp := parse_timestamp(task.get("timestamp"))) is not None
                        and task_timestamp > inherited_cutoff
                    )
                ]

            tasks = detail.get("tasks", [])
            durations_ms = [
                int(task["duration_ms"])
                for task in tasks
                if isinstance(task.get("duration_ms"), (int, float))
            ]
            ttf_ms = [
                int(task["time_to_first_token_ms"])
                for task in tasks
                if isinstance(task.get("time_to_first_token_ms"), (int, float))
            ]
            input_tokens = total_usage.get("input_tokens", 0)
            detail["cached_input_percent"] = (
                round(total_usage.get("cached_input_tokens", 0) / input_tokens * 100, 1)
                if input_tokens
                else None
            )
            detail["token_event_count"] = len(rebased)
            detail["turn_count"] = len(tasks) or len(rebased)
            detail["completed_turn_count"] = len(tasks)
            detail["duration_ms_total"] = sum(durations_ms)
            detail["duration_ms_avg"] = (
                int(sum(durations_ms) / len(durations_ms)) if durations_ms else None
            )
            detail["time_to_first_token_ms_avg"] = (
                int(sum(ttf_ms) / len(ttf_ms)) if ttf_ms else None
            )
            period_models = unique_models(rebased, detail.get("model") if not rebased else None)
            if rebased:
                detail["model"] = str(rebased[-1].get("model") or detail.get("model") or "")
                detail["models"] = period_models or unique_models(detail["model"])
            else:
                detail["models"] = period_models or unique_models(detail.get("models"), detail.get("model"))
            detail.update(
                pricing_for_timeline(
                    rebased,
                    str(detail.get("model") or ""),
                    total_usage,
                    rebased[-1].get("timestamp") if rebased else detail.get("end_at"),
                )
            )
            if rebased:
                detail["start_at"] = str(rebased[0].get("timestamp") or detail.get("created_at") or "")
                detail["end_at"] = str(rebased[-1].get("timestamp") or detail.get("end_at") or "")
                detail["model_context_window"] = rebased[-1].get("model_context_window")
                detail["latest_rate_limits"] = rebased[-1].get("rate_limits")
            summary.update({key: detail.get(key) for key in SUMMARY_KEYS})

    def should_parallel_parse(
        self,
        indexed_files: list[tuple[int, tuple[CodexLogSource, Path, str]]],
    ) -> bool:
        if self.parallel_workers < 2 or self._parallel_disabled:
            return False
        min_files = max(0, environment_int("COUSASH_PARSE_MIN_FILES", DEFAULT_PARSE_MIN_FILES))
        if len(indexed_files) < min_files:
            return False
        main_module = sys.modules.get("__main__")
        main_path = Path(str(getattr(main_module, "__file__", "")))
        if not main_path.is_file():
            return False
        total_bytes = 0
        try:
            for _index, (_log_source, path, _source) in indexed_files:
                total_bytes += path.stat().st_size
        except OSError:
            return False
        min_bytes = max(0, environment_int("COUSASH_PARSE_MIN_BYTES", DEFAULT_PARSE_MIN_BYTES))
        return total_bytes >= min_bytes

    def process_pool(self) -> concurrent.futures.ProcessPoolExecutor:
        if self._process_pool is None:
            self._process_pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=self.parallel_workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=initialize_parse_worker,
            )
        return self._process_pool

    def parse_files_in_parallel(
        self,
        indexed_files: list[tuple[int, tuple[CodexLogSource, Path, str]]],
    ) -> dict[int, tuple[dict[str, Any], dict[str, Any]]] | None:
        jobs = [
            {
                "index": index,
                "source_id": log_source.id,
                "source_label": log_source.label,
                "codex_home": str(log_source.codex_home),
                "path": str(path),
                "source": source,
            }
            for index, (log_source, path, source) in indexed_files
        ]
        try:
            results = list(self.process_pool().map(parse_rollout_worker, jobs, chunksize=1))
        except Exception:
            self._parallel_disabled = True
            if self._process_pool is not None:
                try:
                    self._process_pool.shutdown(wait=True, cancel_futures=True)
                except Exception:
                    pass
                self._process_pool = None
            return None

        parsed_by_index: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
        pending_entries: list[tuple[str, FileParseCacheEntry]] = []
        files_by_index = dict(indexed_files)
        for result in results:
            if result.get("error"):
                continue
            index = int(result["index"])
            summary = result.get("summary")
            detail = result.get("detail")
            before_state = result.get("before_state")
            after_state = result.get("after_state")
            if (
                not isinstance(summary, dict)
                or not isinstance(detail, dict)
                or not isinstance(before_state, tuple)
                or not isinstance(after_state, tuple)
            ):
                continue
            log_source, path, source = files_by_index[index]
            try:
                current_stat = path.stat()
            except OSError:
                continue
            current_state = file_stat_tuple(current_stat)
            parsed_size = int(detail.get("_parsed_end_offset") or 0)
            if (
                parsed_size > before_state[3]
                or file_change_requires_retry(before_state, after_state, parsed_size)
                or file_change_requires_retry(after_state, current_state, parsed_size)
            ):
                continue
            append_safe, prefix_digest, tail_digest = file_parse_markers(path, parsed_size)
            entry = FileParseCacheEntry(
                current_stat.st_mtime_ns,
                parsed_size,
                int(current_stat.st_dev),
                int(current_stat.st_ino),
                summary,
                detail,
                append_safe,
                prefix_digest,
                tail_digest,
            )
            cache_key = self.file_cache_key(log_source, path, source)
            parsed_by_index[index] = (summary, detail)
            pending_entries.append((cache_key, entry))

        for cache_key, entry in pending_entries:
            self._cache[cache_key] = entry
            if self.persistent_cache is not None:
                self._pending_persistent_entries[cache_key] = entry
        self.cache_metrics["full_parses"] += len(parsed_by_index)
        self.cache_metrics["parallel_files"] += len(parsed_by_index)
        return parsed_by_index

    def close(self) -> None:
        if self._process_pool is not None:
            try:
                self._process_pool.shutdown(wait=True, cancel_futures=True)
            except Exception:
                pass
            self._process_pool = None
        if self.persistent_cache is not None:
            self.persistent_cache.close()

    def build_snapshot(
        self,
        files: list[tuple[CodexLogSource, Path, str]],
        include_remotes: bool,
        include_daily_usage: bool = True,
    ) -> dict[str, Any]:
        titles_by_source = {
            log_source.id: self.load_session_titles(log_source.codex_home)
            for log_source in self.codex_sources
        }
        sessions: list[dict[str, Any]] = []
        details_by_uid: dict[str, dict[str, Any]] = {}
        local_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []

        parsed_by_index: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
        full_misses: list[tuple[int, tuple[CodexLogSource, Path, str]]] = []
        for index, (log_source, path, source) in enumerate(files):
            try:
                cached = self.parse_file_cached(
                    path,
                    source,
                    log_source,
                    allow_full=False,
                )
            except OSError:
                continue
            if cached is None:
                full_misses.append((index, (log_source, path, source)))
            else:
                parsed_by_index[index] = cached

        if self.should_parallel_parse(full_misses):
            parallel = self.parse_files_in_parallel(full_misses)
            if parallel is not None:
                parsed_by_index.update(parallel)

        for index, (log_source, path, source) in full_misses:
            if index in parsed_by_index:
                continue
            try:
                parsed = self.parse_file_cached(path, source, log_source)
            except OSError:
                continue
            if parsed is not None:
                parsed_by_index[index] = parsed

        for index, (log_source, _path, source) in enumerate(files):
            parsed = parsed_by_index.get(index)
            if parsed is None:
                # Retain known identity/relationships even if the usage source is unreadable.
                payload = self.cached_session_meta(_path)
                sid = str(payload.get("id") or payload.get("session_id") or _path.stem)
                raw_source = payload.get("source")
                nested = raw_source.get("subagent", {}) if isinstance(raw_source, dict) else {}
                nested = nested.get("thread_spawn", nested) if isinstance(nested, dict) else {}
                parent = str(payload.get("parent_thread_id") or nested.get("parent_thread_id") or "")
                detail = {"uid": self.analysis_id(log_source.id, sid), "session_id": sid,
                          "root_session_id": str(payload.get("root_session_id") or sid),
                          "parent_thread_id": parent,
                          "forked_from_id": str(payload.get("forked_from_id") or nested.get("forked_from_id") or ""),
                          "agent_role": str(payload.get("agent_role") or nested.get("agent_role") or ""),
                          "is_subagent": bool(parent or nested),
                          "title": "Unavailable session source", "environment_id": log_source.id,
                          "codex_home": str(log_source.codex_home), "path": str(_path),
                          "timeline": [], "total_token_usage": zero_usage(), "source": source,
                          "source_unreadable": True,
                          "accounting_warnings": [{"code": "source_unavailable", "message": "A discovered session log could not be read."}]}
                details_by_uid[detail["uid"]] = detail
                continue
            cached_summary, cached_detail = parsed
            summary = dict(cached_summary)
            detail = dict(cached_detail)
            for key in tuple(detail):
                if key.startswith("_"):
                    detail.pop(key, None)
            project_info = self.project_info_for_cwd(str(detail.get("cwd") or ""))
            detail.update(
                {
                    "source": source,
                    "environment": log_source.label,
                    "environment_id": log_source.id,
                    "codex_home": str(log_source.codex_home),
                    "project": project_info.project,
                    "project_root": project_info.project_root,
                    "workspace_root": project_info.workspace_root,
                    "project_branch": project_info.project_branch,
                    "is_git_worktree": project_info.is_git_worktree,
                }
            )
            timeline = detail.get("timeline")
            detail.update(
                pricing_for_timeline(
                    timeline if isinstance(timeline, list) else [],
                    str(detail.get("model") or ""),
                    normalize_usage(detail.get("total_token_usage")),
                    detail.get("end_at"),
                )
            )
            summary.update({key: detail.get(key) for key in SUMMARY_KEYS})
            local_rows.append((summary, detail))

        if self.persistent_cache is not None and self._pending_persistent_entries:
            pending = list(self._pending_persistent_entries.items())
            self._pending_persistent_entries.clear()
            self.persistent_cache.put_many(pending)

        self.normalize_subagent_usage(local_rows)

        for summary, detail in local_rows:
            session_id = summary.get("session_id")
            titles = titles_by_source.get(str(summary.get("environment_id") or ""), {})
            if isinstance(session_id, str) and session_id in titles:
                summary["title"] = titles[session_id]
                detail["title"] = titles[session_id]

            sessions.append(summary)
            details_by_uid[summary["uid"]] = detail

        codex_sources: list[dict[str, Any]] = codex_source_payloads(self.codex_sources)
        if include_remotes and self.remote_store is not None:
            remote_sessions, remote_details, remote_sources = self.remote_store.transformed_sessions()
            sessions.extend(remote_sessions)
            details_by_uid.update(remote_details)
            codex_sources.extend(remote_sources)

        sessions.sort(key=lambda row: row["total_token_usage"].get("total_tokens", 0), reverse=True)
        generated_at = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
        snapshot = {
            "generated_at": generated_at,
            "codex_home": self.codex_home_display,
            "codex_sources": codex_sources,
            "sessions": sessions,
            "details_by_uid": details_by_uid,
            "summary": self.build_summary(sessions),
            "daily_usage": self.build_daily_usage(details_by_uid.values()) if include_daily_usage else [],
            "daily_usage_complete": include_daily_usage,
            "period": {"key": "all", "start_at": None, "end_at": generated_at},
        }
        snapshot["analysis"] = self.build_analysis(snapshot)
        return snapshot

    @staticmethod
    def analysis_id(environment_id: str, session_id: str) -> str:
        return hashlib.sha256((environment_id + "\0" + session_id).encode("utf-8")).hexdigest()[:24]

    def build_analysis(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        keys = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
        def counters(value: Any) -> dict[str, int]:
            normalized = normalize_usage(value)
            return {k: normalized[k] for k in keys}
        def combine(values: Any) -> dict[str, int]:
            result = zero_usage()
            for value in values:
                result = add_usage(result, value)
            return counters(result)
        def warn(warnings: list, code: str, message: str, agent_id: str = "") -> None:
            value = {"code": code, "message": message}
            if agent_id:
                value["agent_id"] = agent_id
            if value not in warnings:
                warnings.append(value)

        # One instance per recorded thread; resumed/duplicate files do not create agents.
        instances: dict[tuple[str, str], list[dict[str, Any]]] = {}
        analysis_details = {str(row.get("uid") or ""): dict(row) for row in snapshot["sessions"]}
        for uid, detail in snapshot["details_by_uid"].items():
            analysis_details[uid] = {**analysis_details.get(uid, {}), **detail}
        for detail in analysis_details.values():
            env = str(detail.get("environment_id") or "")
            sid = str(detail.get("session_id") or detail.get("uid") or "")
            instances.setdefault((env, sid), []).append(detail)
        groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
        root_problems: dict[tuple[str, str], str] = {}
        for key, details in instances.items():
            current = key
            visited = set()
            while current in instances:
                if current in visited:
                    root_problems[key] = "Recorded parent links form a cycle."
                    current = min(visited)
                    break
                visited.add(current)
                d = instances[current][0]
                sid = current[1]
                recorded_root = str(d.get("root_session_id") or "")
                parent = str(d.get("parent_thread_id") or d.get("forked_from_id") or "")
                explicit_root = recorded_root if recorded_root and recorded_root != sid else ""
                target = parent if parent and (current[0], parent) in instances else explicit_root or parent
                if not target:
                    break
                current = (current[0], target)
            groups.setdefault(current, []).append(key)

        roots = []
        usages = {}
        sources = {}
        role_names = {"main": "Main", "explorer": "Explorer", "designer": "Designer", "worker": "Worker",
                      "worker-sol": "Worker Sol", "worker_sol": "Worker Sol", "worker sol": "Worker Sol",
                      "validator": "Validator", "reviewer": "Reviewer", "debugger": "Debugger"}
        for root_key, member_keys in groups.items():
            root_id = self.analysis_id(*root_key)
            warnings: list[dict[str, Any]] = []
            root_details = instances.get(root_key)
            representative = (root_details or instances[member_keys[0]])[0]
            if root_details is None:
                warn(warnings, "missing_root", "The recorded parent/root session log is unavailable on this device.")
            agents = []
            thread_sources = []
            for key in sorted(member_keys, key=lambda k: (k != root_key, k[1])):
                details = instances[key]
                d = details[0]
                agent_id = self.analysis_id(*key)
                is_main = key == root_key and not d.get("is_subagent")
                recorded_role = str(d.get("agent_role") or "").strip()
                role = "Main" if is_main else role_names.get(recorded_role.lower(), recorded_role or "Unknown")
                if role == "Unknown":
                    warn(warnings, "unknown_role", "An agent has no recorded role; its known usage is included under Unknown.", agent_id)
                for detail in details:
                    recorded_parent = str(detail.get("parent_thread_id") or "")
                    if recorded_parent and (key[0], recorded_parent) not in instances:
                        warn(warnings, "missing_parent", "A recorded parent agent has no available session log on this device.", agent_id)
                    for warning in detail.get("accounting_warnings", []):
                        warn(warnings, warning["code"], warning["message"], agent_id)
                    if detail.get("parse_errors"):
                        warn(warnings, "unreadable_records", "Some source records could not be parsed.", agent_id)
                    if detail.get("fork_usage_resolved") is False and (detail.get("is_subagent") or detail.get("forked_from_id")):
                        warn(warnings, "inherited_usage_unresolved", "Inherited usage could not be separated from this agent's counters.", agent_id)
                    if key in root_problems:
                        warn(warnings, "relationship_cycle", root_problems[key], agent_id)
                # Union cumulative rows rather than adding resumed copies of the same thread.
                rows = []
                seen = set()
                for detail in details:
                    for row in detail.get("timeline", []):
                        fingerprint = tuple(normalize_usage(row.get("total_token_usage")).values())
                        if fingerprint not in seen:
                            seen.add(fingerprint)
                            rows.append(row)
                if len(details) > 1:
                    rows.sort(key=lambda row: str(row.get("timestamp") or ""))
                    merged = []
                    boundary = 0
                    for row in rows:
                        total = normalize_usage(row.get("total_token_usage"))["total_tokens"]
                        if total < boundary:
                            continue
                        merged.append(row)
                        boundary = total
                    rows = merged
                by_model: dict[str, dict[str, int]] = {}
                for row, _at, _total, delta in timeline_rows_with_deltas(rows):
                    model = str(row.get("model") or "Unknown")
                    by_model[model] = add_usage(by_model.get(model, zero_usage()), delta)
                if rows and any(parse_timestamp(row.get("timestamp")) is None for row in rows):
                    attributed = combine(by_model.values())
                    known = max(details, key=lambda item: normalize_usage(item.get("total_token_usage"))["total_tokens"])
                    remainder = subtract_usage(normalize_usage(known.get("total_token_usage")), attributed)
                    if usage_has_tokens(remainder):
                        by_model["Unknown"] = add_usage(by_model.get("Unknown", zero_usage()), remainder)
                    warn(warnings, "undated_usage", "Some usage has no usable timestamp; its known remainder is included under Unknown.", agent_id)
                if len(details) > 1:
                    warn(warnings, "duplicate_sources", "Multiple source files record this thread; overlapping histories are merged and require verification.", agent_id)
                for detail in details:
                    for child_id in detail.get("referenced_child_ids", []):
                        if (key[0], child_id) not in instances:
                            warn(warnings, "missing_child", "A recorded spawned agent has no available session log on this device.", agent_id)
                if not rows:
                    # Imported summaries may contain usage without full event histories.
                    known = max(details, key=lambda item: normalize_usage(item.get("total_token_usage"))["total_tokens"])
                    if usage_has_tokens(normalize_usage(known.get("total_token_usage"))):
                        by_model["Unknown"] = normalize_usage(known.get("total_token_usage"))
                        warn(warnings, "model_attribution_unavailable", "Usage is recorded without an attributable event timeline.", agent_id)
                if "Unknown" in by_model and usage_has_tokens(by_model["Unknown"]):
                    warn(warnings, "unknown_model", "Some known usage has no recorded effective model.", agent_id)
                usage = combine(by_model.values())
                parent = str(d.get("parent_thread_id") or d.get("forked_from_id") or "")
                agent = {"id": agent_id, "session_id": key[1],
                         "parent_id": self.analysis_id(key[0], parent) if parent else None,
                         "role": role, "label": str(d.get("agent_nickname") or role),
                         "models": [{"model": model, "usage": counters(value)} for model, value in sorted(by_model.items())],
                         "usage": usage}
                agents.append(agent)
                if d.get("is_remote"):
                    warn(warnings, "remote_history_unavailable", "Full session history not available on this device.", agent_id)
                for detail in details:
                    if detail.get("is_remote") or detail.get("source_unreadable"):
                        continue
                    path = Path(str(detail.get("path") or ""))
                    source_root = Path(str(detail.get("codex_home") or self.codex_home)).resolve()
                    try:
                        path = path.resolve(strict=True)
                        path.relative_to(source_root)
                        if not path.is_file():
                            raise OSError("missing source")
                    except (OSError, ValueError):
                        warn(warnings, "source_unavailable", "A recorded session source is unavailable.", agent_id)
                        continue
                    thread_sources.append({"agent_id": agent_id, "session_id": key[1], "role": role,
                                           "label": agent["label"], "path": path, "source_root": source_root,
                                           "size": detail.get("source_file_size", detail.get("file_size", 0)),
                                           "mtime_ns": detail.get("source_mtime_ns", path.stat().st_mtime_ns),
                                           **({"device": detail["source_device"]} if detail.get("source_device") is not None else {}),
                                           **({"inode": detail["source_inode"]} if detail.get("source_inode") is not None else {})})
            roles = []
            for role in dict.fromkeys(a["role"] for a in agents):
                members = [a for a in agents if a["role"] == role]
                if len(members) > 1:
                    for index, member in enumerate(members, 1):
                        member["label"] = f"{member['label']} #{index}"
                        for source in thread_sources:
                            if source["agent_id"] == member["id"]:
                                source["label"] = member["label"]
                roles.append({"role": role, "usage": combine(a["usage"] for a in members), "agents": members})
            models = {}
            for agent in agents:
                for model in agent["models"]:
                    models.setdefault(model["model"], []).append(model["usage"])
            overall = combine(a["usage"] for a in agents)
            if overall["total_tokens"] != overall["input_tokens"] + overall["output_tokens"]:
                warn(warnings, "inconsistent_counters", "Attributed token counters do not reconcile to input plus output; the recorded known counters are shown.")
            if overall["cached_input_tokens"] > overall["input_tokens"] or overall["reasoning_output_tokens"] > overall["output_tokens"]:
                warn(warnings, "inconsistent_subsets", "Attributed cached input or reasoning output exceeds its containing counter.")
            incomplete = any(w["code"] not in {"unknown_role", "unknown_model"} for w in warnings)
            root = {"id": root_id, "title": representative.get("title") or "Untitled conversation",
                    "project": representative.get("project") or "", "date": representative.get("created_at") or representative.get("start_at") or "",
                    "agent_count": len(agents), "usage": overall,
                    "completeness": "incomplete" if incomplete else "complete", "warnings": warnings,
                    "inspect_available": bool(thread_sources)}
            roots.append(root)
            usages[root_id] = {"root": root, "overall": overall, "by_role": roles, "by_agent": agents,
                               "by_model": [{"model": model, "usage": combine(values)} for model, values in sorted(models.items())],
                               "warnings": warnings}
            sources[root_id] = thread_sources
        roots.sort(key=lambda root: root["date"], reverse=True)
        return {"roots": roots, "usages": usages, "sources": sources}

    def analysis_snapshot(self, snapshot_token: str | None = None) -> dict[str, Any]:
        if snapshot_token:
            with self._published_lock:
                snapshot = self._published_snapshots.get(snapshot_token)
            if snapshot is None:
                raise SnapshotStaleError(snapshot_token)
            return snapshot
        return self.scan("all")

    def filter_snapshot_by_period(
        self,
        snapshot: dict[str, Any],
        period: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        key, start_at, end_at, start_key, end_key = local_period_bounds(period, start_date, end_date)
        if key == "all" or start_at is None:
            return {
                **snapshot,
                "period": {"key": "all", "start_at": None, "end_at": utc_iso(end_at), "start_date": None, "end_date": None},
            }

        sessions: list[dict[str, Any]] = []
        details_by_uid: dict[str, dict[str, Any]] = {}

        for session in snapshot["sessions"]:
            detail = snapshot["details_by_uid"].get(session["uid"])
            if not detail:
                continue
            ranged_detail = self.detail_for_period(detail, start_at, end_at)
            usage = normalize_usage(ranged_detail.get("total_token_usage"))
            if ranged_detail.get("token_event_count", 0) <= 0 and usage["total_tokens"] <= 0:
                continue
            sessions.append({field: ranged_detail.get(field) for field in SUMMARY_KEYS})
            details_by_uid[ranged_detail["uid"]] = ranged_detail

        sessions.sort(key=lambda row: row["total_token_usage"].get("total_tokens", 0), reverse=True)
        return {
            **snapshot,
            "sessions": sessions,
            "details_by_uid": details_by_uid,
            "summary": self.build_summary(sessions),
            "daily_usage": self.build_daily_usage(details_by_uid.values()),
            "daily_usage_complete": False,
            "period": {
                "key": key,
                "start_at": utc_iso(start_at),
                "end_at": utc_iso(end_at),
                "start_date": start_key,
                "end_date": end_key,
            },
        }

    def build_daily_usage(self, details: Any) -> list[dict[str, Any]]:
        return self.build_daily_usage_static(details)

    @staticmethod
    def build_daily_usage_static(details: Any) -> list[dict[str, Any]]:
        tzinfo = dt.datetime.now().astimezone().tzinfo
        by_day: dict[str, dict[str, Any]] = {}

        for detail in details:
            for _row, timestamp, _cumulative_usage, delta_usage in timeline_rows_with_deltas(
                detail.get("timeline", [])
            ):
                if delta_usage["total_tokens"] <= 0:
                    continue
                day = timestamp.astimezone(tzinfo).date().isoformat()
                by_day.setdefault(day, {"date": day, "usage": zero_usage()})
                by_day[day]["usage"] = add_usage(by_day[day]["usage"], delta_usage)

        return sorted(by_day.values(), key=lambda row: row["date"])

    def detail_for_period(self, detail: dict[str, Any], start_at: dt.datetime, end_at: dt.datetime) -> dict[str, Any]:
        timeline: list[dict[str, Any]] = []
        total_usage = zero_usage()
        last_usage = zero_usage()
        for row, timestamp, _cumulative_usage, delta_usage in timeline_rows_with_deltas(
            detail.get("timeline", [])
        ):
            if timestamp < start_at:
                continue
            if timestamp > end_at:
                break

            total_usage = add_usage(total_usage, delta_usage)
            last_usage = delta_usage
            relative_row = dict(row)
            relative_row["total_token_usage"] = dict(total_usage)
            relative_row["last_token_usage"] = dict(delta_usage)
            timeline.append(relative_row)
        cached_percent = None
        input_tokens = total_usage.get("input_tokens", 0)
        if input_tokens:
            cached_percent = round(total_usage.get("cached_input_tokens", 0) / input_tokens * 100, 1)

        tasks = [
            row
            for row in detail.get("tasks", [])
            if timestamp_in_range(row.get("timestamp"), start_at, end_at)
        ]
        durations_ms = [
            int(row["duration_ms"])
            for row in tasks
            if isinstance(row.get("duration_ms"), (int, float))
        ]
        ttf_ms = [
            int(row["time_to_first_token_ms"])
            for row in tasks
            if isinstance(row.get("time_to_first_token_ms"), (int, float))
        ]

        ranged = dict(detail)
        ranged["period_start_at"] = utc_iso(start_at)
        ranged["period_end_at"] = utc_iso(end_at)
        ranged["timeline"] = timeline
        ranged["tasks"] = tasks
        ranged["total_token_usage"] = total_usage
        ranged["last_token_usage"] = last_usage
        period_models = unique_models(timeline, detail.get("model") if not timeline else None)
        if timeline:
            ranged["model"] = str(timeline[-1].get("model") or detail.get("model") or "")
            ranged["models"] = period_models or unique_models(ranged["model"])
        else:
            ranged["models"] = period_models or unique_models(detail.get("models"), detail.get("model"))
        ranged.update(
            pricing_for_timeline(
                timeline,
                str(ranged.get("model") or detail.get("model") or ""),
                total_usage,
                timeline[-1].get("timestamp") if timeline else end_at,
            )
        )
        ranged["cached_input_percent"] = cached_percent
        ranged["token_event_count"] = len(timeline)
        ranged["turn_count"] = len(tasks) or len(timeline)
        ranged["completed_turn_count"] = len(tasks)
        ranged["duration_ms_total"] = sum(durations_ms)
        ranged["duration_ms_avg"] = int(sum(durations_ms) / len(durations_ms)) if durations_ms else None
        ranged["time_to_first_token_ms_avg"] = int(sum(ttf_ms) / len(ttf_ms)) if ttf_ms else None
        if timeline:
            ranged["start_at"] = str(timeline[0].get("timestamp") or detail.get("start_at") or "")
            ranged["end_at"] = str(timeline[-1].get("timestamp") or detail.get("end_at") or "")
            ranged["model_context_window"] = timeline[-1].get("model_context_window")
            ranged["latest_rate_limits"] = timeline[-1].get("rate_limits")
        return ranged

    def parse_file_cached(
        self,
        path: Path,
        source: str,
        log_source: CodexLogSource | None = None,
        allow_full: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        log_source = log_source or self.codex_sources[0]
        stat = path.stat()
        cache_key = self.file_cache_key(log_source, path, source)
        cached = self._cache.get(cache_key)
        if (
            cached is not None
            and cached.mtime_ns == stat.st_mtime_ns
            and cached.size == stat.st_size
            and cached.device == int(stat.st_dev)
            and cached.inode == int(stat.st_ino)
        ):
            self.cache_metrics["memory_hits"] += 1
            return cached.summary, cached.detail

        if cached is None and self.persistent_cache is not None:
            cached = self.persistent_cache.get(cache_key)
            if cached is not None:
                self._cache[cache_key] = cached
                if (
                    cached.mtime_ns == stat.st_mtime_ns
                    and cached.size == stat.st_size
                    and cached.device == int(stat.st_dev)
                    and cached.inode == int(stat.st_ino)
                ):
                    self.cache_metrics["persistent_hits"] += 1
                    return cached.summary, cached.detail

        used_incremental = cached is not None and file_matches_cached_prefix(path, cached, stat)
        if used_incremental:
            summary, detail = self.parse_file(
                path,
                source,
                log_source,
                base_detail=cached.detail,
                start_offset=cached.size,
                end_offset=stat.st_size,
            )
        elif not allow_full:
            return None
        else:
            summary, detail = self.parse_file(
                path,
                source,
                log_source,
                end_offset=stat.st_size,
            )

        final_stat = path.stat()
        parsed_size = int(detail.get("_parsed_end_offset") or 0)
        if file_change_requires_retry(
            file_stat_tuple(stat),
            file_stat_tuple(final_stat),
            parsed_size,
        ):
            stat = path.stat()
            summary, detail = self.parse_file(
                path,
                source,
                log_source,
                end_offset=stat.st_size,
            )
            final_stat = path.stat()
            parsed_size = int(detail.get("_parsed_end_offset") or 0)
            used_incremental = False

        if used_incremental and cached is not None:
            self.cache_metrics["incremental_parses"] += 1
            self.cache_metrics["incremental_bytes"] += max(0, parsed_size - cached.size)
        else:
            self.cache_metrics["full_parses"] += 1

        if file_change_requires_retry(
            file_stat_tuple(stat),
            file_stat_tuple(final_stat),
            parsed_size,
        ):
            return summary, detail

        append_safe, prefix_digest, tail_digest = file_parse_markers(path, parsed_size)
        entry = FileParseCacheEntry(
            final_stat.st_mtime_ns,
            parsed_size,
            int(final_stat.st_dev),
            int(final_stat.st_ino),
            summary,
            detail,
            append_safe,
            prefix_digest,
            tail_digest,
        )
        self._cache[cache_key] = entry
        if self.persistent_cache is not None:
            self._pending_persistent_entries[cache_key] = entry
        return summary, detail

    def project_info_for_cwd(self, cwd: str) -> ProjectInfo:
        key = str(cwd or "")
        if not self.resolve_project_info:
            project = folder_name_from_path(key) or "unknown"
            return ProjectInfo(project, key, key, "", False)
        cached = self._project_info_cache.get(key)
        if cached is None:
            cached = git_project_info(key)
            self._project_info_cache[key] = cached
        return cached

    def parse_file(
        self,
        path: Path,
        source: str,
        log_source: CodexLogSource | None = None,
        base_detail: dict[str, Any] | None = None,
        start_offset: int = 0,
        end_offset: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        log_source = log_source or self.codex_sources[0]
        source_stat = path.stat()
        resolved_path = self.resolved_path_key(path)
        uid = hashlib.sha1(f"{log_source.id}:{resolved_path}".encode("utf-8", errors="replace")).hexdigest()[:16]
        base = base_detail or {}
        session_id = str(base.get("session_id") or "")
        root_session_id = str(base.get("root_session_id") or "")
        parent_thread_id = str(base.get("parent_thread_id") or "")
        forked_from_id = str(base.get("forked_from_id") or "")
        thread_source = str(base.get("thread_source") or "")
        is_subagent = bool(base.get("is_subagent"))
        agent_path = str(base.get("agent_path") or "")
        agent_nickname = str(base.get("agent_nickname") or "")
        agent_role = str(base.get("agent_role") or "")
        session_meta_seen = bool(base.get("_session_meta_seen"))
        title = ""
        cwd = str(base.get("cwd") or "")
        model = str(base.get("model") or "")
        models = unique_models(base.get("models"), model)
        effort = str(base.get("effort") or "")
        originator = str(base.get("originator") or "")
        cli_version = str(base.get("cli_version") or "")
        created_at = str(base.get("_raw_created_at") or "")
        start_at = str(base.get("_raw_start_at") or "")
        end_at = str(base.get("_raw_end_at") or "")
        raw_context_window = base.get("model_context_window")
        model_context_window = int(raw_context_window) if isinstance(raw_context_window, (int, float)) else None
        raw_rate_limits = base.get("latest_rate_limits")
        latest_rate_limits = raw_rate_limits if isinstance(raw_rate_limits, dict) else None
        raw_reached_type = base.get("latest_rate_limit_reached_type")
        latest_rate_limit_reached_type = raw_reached_type if isinstance(raw_reached_type, str) else None
        raw_plan_type = base.get("latest_plan_type")
        latest_plan_type = raw_plan_type if isinstance(raw_plan_type, str) else None

        total_usage = normalize_usage(base.get("total_token_usage"))
        last_usage = normalize_usage(base.get("last_token_usage"))
        timeline = list(base.get("_token_count_timeline", base.get("timeline", [])))
        modern_usage_rows = list(base.get("_modern_usage_rows", []))
        tasks = list(base.get("tasks", [])) if isinstance(base.get("tasks"), list) else []
        accounting_warnings = list(base.get("accounting_warnings", []))
        response_usage_seen = dict(base.get("_response_usage_seen", {}))
        spawn_call_ids = set(base.get("_spawn_call_ids", []))
        referenced_child_ids = set(base.get("referenced_child_ids", []))

        def note_spawn_result(value: Any) -> None:
            if isinstance(value, str):
                try:
                    note_spawn_result(json.loads(value))
                except (ValueError, TypeError):
                    pass
            elif isinstance(value, dict):
                child_id = value.get("agent_id") or value.get("thread_id")
                if isinstance(child_id, str) and child_id:
                    referenced_child_ids.add(child_id)
                for name in ("content", "text", "result", "output"):
                    if name in value:
                        note_spawn_result(value[name])
            elif isinstance(value, list):
                for child in value:
                    note_spawn_result(child)
        usage_families = set(base.get("_usage_families", []))

        def accounting_warning(code: str, message: str) -> None:
            if not any(w.get("code") == code for w in accounting_warnings):
                accounting_warnings.append({"code": code, "message": message})

        def checked_usage(value: Any, required: bool = True) -> tuple[dict[str, int], bool]:
            normalized = normalize_usage(value)
            recognized = False
            malformed = False
            if isinstance(value, dict):
                for name in (*TOKEN_KEYS, "cache_write_input_tokens"):
                    if name not in value:
                        continue
                    raw = value[name]
                    valid = (isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0) or (
                        isinstance(raw, float) and math.isfinite(raw) and raw >= 0 and raw.is_integer())
                    recognized = recognized or valid
                    malformed = malformed or not valid
            if malformed or (required and not recognized):
                accounting_warning("invalid_usage", "Some recorded token counters have an unsupported or invalid shape; only valid nonnegative counters are included.")
            return normalized, recognized

        def record_usage(cumulative: Any, last: Any, timestamp: Any, family: str,
                         response_id: str = "", event_model: str | None = None) -> None:
            nonlocal total_usage, last_usage, token_event_count
            current, usable = checked_usage(cumulative)
            if not usable:
                accounting_warning("usage_unresolved", "A token record has no usable cumulative counters.")
                return
            previous = normalize_usage(timeline[-1].get("total_token_usage")) if timeline else zero_usage()
            usage_families.add(family)
            if current["total_tokens"] != current["input_tokens"] + current["output_tokens"]:
                accounting_warning("inconsistent_counters", "Recorded total tokens differ from input plus output.")
            if current["cached_input_tokens"] > current["input_tokens"] or current["reasoning_output_tokens"] > current["output_tokens"]:
                accounting_warning("inconsistent_subsets", "Recorded cached input or reasoning output exceeds its containing counter.")
            if timeline and current == previous:
                return
            if timeline and any(current[key] < previous[key] for key in TOKEN_KEYS):
                accounting_warning("counter_reset", "Recorded cumulative counter components decrease; the accounting boundary is uncertain.")
            total_usage = current
            last_usage, _last_usable = checked_usage(last, required=last is not None)
            token_event_count += 1
            timeline.append({"timestamp": timestamp, "model": event_model if event_model is not None else model,
                             "total_token_usage": current, "last_token_usage": last_usage,
                             "model_context_window": model_context_window, "rate_limits": latest_rate_limits,
                             "usage_family": family, "response_id": response_id})
        raw_tool_counts = base.get("tool_counts")
        tool_counts = {
            str(name): int(count)
            for name, count in raw_tool_counts.items()
            if isinstance(count, (int, float))
        } if isinstance(raw_tool_counts, dict) else {}
        turn_ids = {
            str(turn_id)
            for turn_id in base.get("_turn_ids", [])
            if isinstance(turn_id, str)
        }
        parse_errors = int(base.get("parse_errors") or 0)
        line_count = int(base.get("line_count") or 0)
        token_event_count = int(base.get("token_event_count") or 0)
        user_message_count = int(base.get("user_message_count") or 0)
        assistant_message_count = int(base.get("assistant_message_count") or 0)
        first_user_prompt = str(base.get("first_user_prompt") or "")
        last_agent_preview = str(base.get("last_agent_preview") or "")
        durations_ms = [
            int(task["duration_ms"])
            for task in tasks
            if isinstance(task, dict) and isinstance(task.get("duration_ms"), (int, float))
        ]
        ttf_ms = [
            int(task["time_to_first_token_ms"])
            for task in tasks
            if isinstance(task, dict) and isinstance(task.get("time_to_first_token_ms"), (int, float))
        ]
        fast_skipped_line_count = int(base.get("fast_skipped_line_count") or 0)
        fast_skipped_bytes = int(base.get("fast_skipped_bytes") or 0)

        def note_model(value: Any) -> None:
            nonlocal model
            if not isinstance(value, str):
                return
            cleaned = value.strip()
            if not cleaned:
                return
            model = cleaned
            if cleaned not in models:
                models.append(cleaned)

        rollout_stats = RolloutReadStats()
        for item in read_rollout_jsonl(
            path,
            start_offset,
            rollout_stats,
            end_offset=end_offset,
        ):
            line_count += 1
            if item.get("__parse_error__"):
                parse_errors += 1
                continue

            timestamp = item.get("timestamp")
            if isinstance(timestamp, str):
                if not start_at or timestamp < start_at:
                    start_at = timestamp
                if not end_at or timestamp > end_at:
                    end_at = timestamp

            item_type = item.get("type")
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}

            if item_type == "session_meta":
                if not session_meta_seen:
                    session_meta_seen = True
                    session_id = str(payload.get("id") or payload.get("session_id") or session_id)
                    root_session_id = str(payload.get("root_session_id") or payload.get("session_id") or session_id)
                    cwd = str(payload.get("cwd") or cwd)
                    created_at = str(payload.get("timestamp") or created_at)
                    originator = str(payload.get("originator") or originator)
                    cli_version = str(payload.get("cli_version") or cli_version)
                    note_model(model_from_payload(payload) or model)

                    raw_thread_source = payload.get("thread_source")
                    if isinstance(raw_thread_source, str):
                        thread_source = raw_thread_source

                    raw_source = payload.get("source")
                    subagent_meta: dict[str, Any] = {}
                    if isinstance(raw_source, dict) and isinstance(raw_source.get("subagent"), dict):
                        subagent_meta = raw_source["subagent"]
                    spawn_meta = (
                        subagent_meta.get("thread_spawn")
                        if isinstance(subagent_meta.get("thread_spawn"), dict)
                        else subagent_meta
                    )
                    parent_thread_id = str(
                        payload.get("parent_thread_id")
                        or spawn_meta.get("parent_thread_id")
                        or subagent_meta.get("parent_thread_id")
                        or ""
                    )
                    forked_from_id = str(
                        payload.get("forked_from_id")
                        or spawn_meta.get("forked_from_id")
                        or subagent_meta.get("forked_from_id")
                        or ""
                    )
                    agent_path = str(
                        payload.get("agent_path")
                        or spawn_meta.get("agent_path")
                        or subagent_meta.get("agent_path")
                        or ""
                    )
                    agent_nickname = str(
                        payload.get("agent_nickname")
                        or spawn_meta.get("agent_nickname")
                        or subagent_meta.get("agent_nickname")
                        or ""
                    )
                    agent_role = str(
                        payload.get("agent_role")
                        or spawn_meta.get("agent_role")
                        or subagent_meta.get("agent_role")
                        or ""
                    )
                    is_subagent = bool(
                        subagent_meta
                        or parent_thread_id
                        or thread_source.lower() == "subagent"
                    )
                    if is_subagent and not parent_thread_id:
                        parent_thread_id = forked_from_id or (
                            root_session_id if root_session_id != session_id else ""
                        )

            elif item_type == "turn_context":
                turn_id = payload.get("turn_id")
                if isinstance(turn_id, str):
                    turn_ids.add(turn_id)
                cwd = str(payload.get("cwd") or cwd)
                note_model(model_from_payload(payload) or model)
                effort = str(
                    payload.get("effort")
                    or payload.get("reasoning_effort")
                    or effort
                )

            elif item_type == "response_item":
                response_type = payload.get("type")
                if response_type == "message":
                    role = payload.get("role")
                    text = clean_text(text_from_content(payload.get("content")), 260)
                    if role == "user":
                        user_message_count += 1
                        if text and not first_user_prompt and not is_synthetic_user_context(text):
                            first_user_prompt = text
                    elif role == "assistant":
                        assistant_message_count += 1
                        if text:
                            last_agent_preview = text
                elif response_type == "function_call":
                    name = str(payload.get("name") or "function_call")
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                    if name.rsplit(".", 1)[-1] == "spawn_agent" and payload.get("call_id"):
                        spawn_call_ids.add(str(payload["call_id"]))
                elif response_type in {"function_call_output", "custom_tool_call_output"}:
                    if str(payload.get("call_id") or "") in spawn_call_ids:
                        note_spawn_result(payload.get("output"))

            elif item_type == "token_usage_record":
                response_id = str(payload.get("response_id") or "")
                cumulative, cumulative_usable = checked_usage(payload.get("thread_token_usage"), required="thread_token_usage" in payload)
                contribution, contribution_usable = checked_usage(payload.get("usage"))
                if response_id and response_id in response_usage_seen:
                    if response_usage_seen[response_id] != contribution:
                        accounting_warning("response_conflict", "A repeated response ID has conflicting token counters.")
                    continue
                if response_id:
                    response_usage_seen[response_id] = contribution
                event_model = model_from_payload(payload) or model
                if event_model and event_model not in models:
                    models.append(event_model)
                if not cumulative_usable and not (response_id and contribution_usable):
                    accounting_warning("usage_unresolved", "A token record has neither usable cumulative counters nor a unique response contribution.")
                else:
                    modern_usage_rows.append({"timestamp": timestamp, "model": event_model,
                        "total_token_usage": normalize_usage(cumulative), "last_token_usage": contribution,
                        "response_only": not cumulative_usable,
                        "usage_family": "token_usage_record", "response_id": response_id})

            elif item_type == "event_msg":
                event_type = payload.get("type")
                if event_type == "item_completed":
                    completed = payload.get("item")
                    if isinstance(completed, dict) and isinstance(completed.get("agent_thread_id"), str):
                        referenced_child_ids.add(completed["agent_thread_id"])
                elif event_type == "thread_settings_applied":
                    # Desktop/WSL model switches often arrive here before the next
                    # turn_context, so apply them immediately for timeline pricing.
                    note_model(model_from_payload(payload))
                    thread_settings = (
                        payload.get("thread_settings")
                        if isinstance(payload.get("thread_settings"), dict)
                        else {}
                    )
                    effort = str(
                        thread_settings.get("reasoning_effort")
                        or thread_settings.get("effort")
                        or payload.get("effort")
                        or effort
                    )
                    cwd = str(thread_settings.get("cwd") or payload.get("cwd") or cwd)

                elif event_type == "token_count":
                    latest_rate_limits = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else None
                    latest_plan_type = payload.get("plan_type") if isinstance(payload.get("plan_type"), str) else latest_plan_type
                    reached = payload.get("rate_limit_reached_type")
                    latest_rate_limit_reached_type = reached if isinstance(reached, str) else latest_rate_limit_reached_type

                    info = payload.get("info")
                    if not isinstance(info, dict):
                        accounting_warning("invalid_usage", "A token-count record has no usable usage object.")
                    if isinstance(info, dict):
                        # Prefer explicit model at the usage event, never the final session model.
                        event_model = model_from_payload(info) or model_from_payload(payload) or model
                        if event_model and event_model not in models:
                            models.append(event_model)
                        window = info.get("model_context_window")
                        if isinstance(window, (int, float)):
                            model_context_window = int(window)
                        record_usage(info.get("total_token_usage"), info.get("last_token_usage"), timestamp, "token_count", event_model=event_model)

                elif event_type == "task_complete":
                    duration = payload.get("duration_ms")
                    first_token = payload.get("time_to_first_token_ms")
                    turn_id = payload.get("turn_id")
                    if isinstance(turn_id, str):
                        turn_ids.add(turn_id)
                    if isinstance(duration, (int, float)):
                        durations_ms.append(int(duration))
                    if isinstance(first_token, (int, float)):
                        ttf_ms.append(int(first_token))
                    tasks.append(
                        {
                            "timestamp": timestamp,
                            "turn_id": turn_id,
                            "duration_ms": int(duration) if isinstance(duration, (int, float)) else None,
                            "time_to_first_token_ms": int(first_token) if isinstance(first_token, (int, float)) else None,
                        }
                    )
                    last_message = payload.get("last_agent_message")
                    if isinstance(last_message, str):
                        last_agent_preview = clean_text(last_message, 320)

                elif event_type in {"agent_message", "assistant_message"}:
                    assistant_message_count += 1
                    message = payload.get("message")
                    if isinstance(message, str):
                        last_agent_preview = clean_text(message, 320)

                elif event_type in {"user_message", "user_input", "human_message"}:
                    user_message_count += 1
                    message = payload.get("message") or payload.get("text") or payload.get("content")
                    if isinstance(message, str) and not first_user_prompt and not is_synthetic_user_context(message):
                        first_user_prompt = clean_text(message, 260)

        token_count_timeline = list(timeline)
        if modern_usage_rows:
            if not timeline:
                # Modern-only logs use their cumulative thread counters, never a sum of both representations.
                timeline = []
                for modern in modern_usage_rows:
                    if modern.get("response_only"):
                        previous = normalize_usage(timeline[-1]["total_token_usage"]) if timeline else zero_usage()
                        modern = {**modern, "total_token_usage": add_usage(previous, modern["last_token_usage"])}
                    current = normalize_usage(modern["total_token_usage"])
                    if timeline and current["total_tokens"] < normalize_usage(timeline[-1]["total_token_usage"])["total_tokens"]:
                        accounting_warning("counter_reset", "Recorded cumulative counters decrease; the accounting boundary is uncertain.")
                    if not timeline or current != normalize_usage(timeline[-1]["total_token_usage"]):
                        timeline.append(modern)
            else:
                # Older cumulative snapshots are authoritative wherever the two families overlap.
                # A trailing modern record is included only when its response contribution proves
                # that its cumulative counters start exactly at the current known boundary.
                authority = list(timeline)
                index = 0
                for modern in modern_usage_rows:
                    if modern.get("response_only"):
                        accounting_warning("usage_overlap", "Response-only usage overlaps cumulative coverage and cannot be independently added.")
                        continue
                    at = str(modern.get("timestamp") or "")
                    while index < len(authority) and str(authority[index].get("timestamp") or "") < at:
                        index += 1
                    current = normalize_usage(modern["total_token_usage"])
                    if index < len(authority):
                        if current != normalize_usage(authority[index]["total_token_usage"]):
                            accounting_warning("usage_overlap", "Token record families disagree over overlapping coverage; cumulative token-count usage is shown.")
                        continue
                    boundary = normalize_usage(timeline[-1]["total_token_usage"])
                    if current == boundary:
                        continue
                    contribution = normalize_usage(modern["last_token_usage"])
                    if add_usage(boundary, contribution) == current:
                        timeline.append(modern)
                    else:
                        accounting_warning("usage_overlap", "Trailing token records cannot be reconciled with the known cumulative boundary.")
            for row in timeline:
                value = normalize_usage(row.get("total_token_usage"))
                if value["total_tokens"] != value["input_tokens"] + value["output_tokens"]:
                    accounting_warning("inconsistent_counters", "Recorded total tokens differ from input plus output.")
            total_usage = normalize_usage(timeline[-1].get("total_token_usage")) if timeline else zero_usage()
            last_usage = normalize_usage(timeline[-1].get("last_token_usage")) if timeline else zero_usage()
            token_event_count = len(timeline)

        fast_skipped_line_count += rollout_stats.fast_skipped_line_count
        fast_skipped_bytes += rollout_stats.fast_skipped_bytes

        if not session_id:
            match = re.search(r"rollout-[^-]+-[^-]+-(.+?)\.jsonl$", path.name)
            session_id = match.group(1) if match else uid
        if not root_session_id:
            root_session_id = session_id

        raw_created_at = created_at
        raw_start_at = start_at
        raw_end_at = end_at

        if not title:
            agent_leaf = agent_path.rstrip("/").rsplit("/", 1)[-1] if agent_path else ""
            agent_labels = [agent_nickname] if agent_nickname else []
            if agent_leaf and all(agent_leaf.casefold() != label.casefold() for label in agent_labels):
                agent_labels.append(agent_leaf)
            title = (
                " · ".join(agent_labels)
                if is_subagent and agent_labels
                else first_user_prompt or folder_name_from_path(cwd) or path.stem
            )

        if not start_at:
            start_at = created_at or utc_from_mtime(path) or ""
        if not end_at:
            end_at = utc_from_mtime(path) or start_at

        # Rebuild from timeline so incremental cache bases without `models`
        # still surface every model that actually generated token events.
        models = unique_models(models, timeline, model)

        cached_percent = None
        input_tokens = total_usage.get("input_tokens", 0)
        if input_tokens:
            cached_percent = round(total_usage.get("cached_input_tokens", 0) / input_tokens * 100, 1)
        pricing = pricing_for_timeline(timeline, model, total_usage, end_at)
        project_info = self.project_info_for_cwd(cwd)

        detail: dict[str, Any] = {
            "uid": uid,
            "session_id": session_id,
            "root_session_id": root_session_id,
            "parent_thread_id": parent_thread_id,
            "forked_from_id": forked_from_id,
            "thread_source": thread_source,
            "is_subagent": is_subagent,
            "agent_path": agent_path,
            "agent_nickname": agent_nickname,
            "agent_role": agent_role,
            "title": title,
            "source": source,
            "environment": log_source.label,
            "environment_id": log_source.id,
            "is_remote": False,
            "remote_device_short_code": "",
            "remote_imported_at": "",
            "remote_exported_at": "",
            "codex_home": str(log_source.codex_home),
            "path": resolved_path,
            "file_size": start_offset + rollout_stats.bytes_read,
            "source_file_size": end_offset if end_offset is not None else source_stat.st_size,
            "source_mtime_ns": source_stat.st_mtime_ns,
            "source_device": int(source_stat.st_dev),
            "source_inode": int(source_stat.st_ino),
            "line_count": line_count,
            "parse_errors": parse_errors,
            "fast_skipped_line_count": fast_skipped_line_count,
            "fast_skipped_bytes": fast_skipped_bytes,
            "created_at": created_at or start_at,
            "start_at": start_at,
            "end_at": end_at,
            "updated_at": utc_from_mtime(path),
            "cwd": cwd,
            "project": project_info.project,
            "project_root": project_info.project_root,
            "workspace_root": project_info.workspace_root,
            "project_branch": project_info.project_branch,
            "is_git_worktree": project_info.is_git_worktree,
            "model": model,
            "models": models,
            "effort": effort,
            "originator": originator,
            "cli_version": cli_version,
            "total_token_usage": total_usage,
            "last_token_usage": last_usage,
            "branch_total_token_usage": total_usage,
            "inherited_token_usage": zero_usage(),
            "inherited_token_event_count": 0,
            "fork_usage_resolved": not is_subagent,
            "estimated_cost_usd": pricing["estimated_cost_usd"],
            "estimated_cost_breakdown_usd": pricing["estimated_cost_breakdown_usd"],
            "price_model_known": pricing["price_model_known"],
            "applied_price_segments": pricing["applied_price_segments"],
            "cached_input_percent": cached_percent,
            "model_context_window": model_context_window,
            "token_event_count": token_event_count,
            "turn_count": len(turn_ids) or len(tasks) or token_event_count,
            "completed_turn_count": len(tasks),
            "user_message_count": user_message_count,
            "assistant_message_count": assistant_message_count,
            "first_user_prompt": first_user_prompt,
            "last_agent_preview": last_agent_preview,
            "latest_rate_limits": latest_rate_limits,
            "latest_plan_type": latest_plan_type,
            "latest_rate_limit_reached_type": latest_rate_limit_reached_type,
            "tool_counts": dict(sorted(tool_counts.items(), key=lambda item: item[1], reverse=True)),
            "duration_ms_total": sum(durations_ms),
            "duration_ms_avg": int(sum(durations_ms) / len(durations_ms)) if durations_ms else None,
            "time_to_first_token_ms_avg": int(sum(ttf_ms) / len(ttf_ms)) if ttf_ms else None,
            "timeline": timeline,
            "tasks": tasks,
            "accounting_warnings": accounting_warnings,
            "referenced_child_ids": sorted(referenced_child_ids),
            "_spawn_call_ids": sorted(spawn_call_ids),
            "_token_count_timeline": token_count_timeline,
            "_modern_usage_rows": modern_usage_rows,
            "_response_usage_seen": response_usage_seen,
            "_usage_families": sorted(usage_families),
            "_turn_ids": sorted(turn_ids),
            "_session_meta_seen": session_meta_seen,
            "_raw_created_at": raw_created_at,
            "_raw_start_at": raw_start_at,
            "_raw_end_at": raw_end_at,
            "_parsed_end_offset": start_offset + rollout_stats.bytes_read,
        }

        summary = {key: detail[key] for key in SUMMARY_KEYS}
        return summary, detail

    def build_summary(self, sessions: list[dict[str, Any]]) -> dict[str, Any]:
        return self.build_summary_static(sessions)

    @staticmethod
    def build_summary_static(sessions: list[dict[str, Any]]) -> dict[str, Any]:
        totals = zero_usage()
        by_model: dict[str, dict[str, Any]] = {}
        by_project: dict[str, dict[str, Any]] = {}
        by_day: dict[str, dict[str, Any]] = {}
        by_environment: dict[str, dict[str, Any]] = {}
        active_count = 0
        archived_count = 0
        estimated_cost_total = 0.0
        estimated_cost_known_count = 0

        for session in sessions:
            usage = normalize_usage(session.get("total_token_usage"))
            totals = add_usage(totals, usage)
            if isinstance(session.get("estimated_cost_usd"), (int, float)):
                estimated_cost_total += float(session["estimated_cost_usd"])
                estimated_cost_known_count += 1

            if session.get("source") == "active":
                active_count += 1
            elif session.get("source") == "archived":
                archived_count += 1

            model = str(session.get("model") or "unknown")
            by_model.setdefault(model, {"model": model, "sessions": 0, "usage": zero_usage()})
            by_model[model]["sessions"] += 1
            by_model[model]["usage"] = add_usage(by_model[model]["usage"], usage)

            project_key = str(session.get("project_root") or session.get("project") or "unknown")
            project = str(session.get("project") or folder_name_from_path(project_key) or "unknown")
            by_project.setdefault(
                project_key,
                {"project": project, "project_root": project_key, "sessions": 0, "usage": zero_usage()},
            )
            by_project[project_key]["sessions"] += 1
            by_project[project_key]["usage"] = add_usage(by_project[project_key]["usage"], usage)

            environment_id = str(session.get("environment_id") or "local")
            environment = str(session.get("environment") or environment_id)
            by_environment.setdefault(
                environment_id,
                {"id": environment_id, "label": environment, "sessions": 0, "usage": zero_usage()},
            )
            by_environment[environment_id]["sessions"] += 1
            by_environment[environment_id]["usage"] = add_usage(by_environment[environment_id]["usage"], usage)

            stamp = str(session.get("end_at") or session.get("start_at") or "")[:10] or "unknown"
            by_day.setdefault(stamp, {"date": stamp, "sessions": 0, "usage": zero_usage()})
            by_day[stamp]["sessions"] += 1
            by_day[stamp]["usage"] = add_usage(by_day[stamp]["usage"], usage)

        return {
            "session_count": len(sessions),
            "active_count": active_count,
            "archived_count": archived_count,
            "usage": totals,
            "estimated_cost_usd": round(estimated_cost_total, 6),
            "estimated_cost_known_count": estimated_cost_known_count,
            "by_model": sorted(by_model.values(), key=lambda row: row["usage"]["total_tokens"], reverse=True),
            "by_project": sorted(by_project.values(), key=lambda row: row["usage"]["total_tokens"], reverse=True)[:20],
            "by_environment": sorted(by_environment.values(), key=lambda row: row["usage"]["total_tokens"], reverse=True),
            "by_day": sorted(by_day.values(), key=lambda row: row["date"]),
            "top_session_uid": sessions[0]["uid"] if sessions else None,
        }

    def get_detail(
        self,
        uid: str,
        period: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        snapshot_token: str | None = None,
    ) -> dict[str, Any] | None:
        if snapshot_token:
            with self._published_lock:
                snapshot = self._published_snapshots.get(snapshot_token)
            if snapshot is None:
                raise SnapshotStaleError(snapshot_token)
            return snapshot["details_by_uid"].get(uid)
        snapshot = self.scan(period, start_date, end_date)
        return snapshot["details_by_uid"].get(uid)

    def export_snapshot_payload(self) -> dict[str, Any]:
        snapshot = self.scan("all", include_remotes=False)
        device_code = self.remote_store.current_device_code if self.remote_store else current_device_short_code()
        now = utc_iso(dt.datetime.now(dt.UTC))
        return {
            "schema": SNAPSHOT_SCHEMA,
            "version": SNAPSHOT_VERSION,
            "exported_at": now,
            "device": {
                "short_code": device_code,
                "label": default_device_label(),
                "platform": platform.system() or "",
                "hostname": platform.node() or "",
            },
            "snapshot": {
                "generated_at": snapshot["generated_at"],
                "codex_home": snapshot["codex_home"],
                "codex_sources": snapshot.get("codex_sources", []),
                "summary": snapshot["summary"],
                "sessions": snapshot["sessions"],
                "details_by_uid": snapshot["details_by_uid"],
                "daily_usage": snapshot.get("daily_usage", []),
            },
        }

    def export_snapshot_json(self) -> str:
        return json.dumps(self.export_snapshot_payload(), ensure_ascii=False, indent=2)


def load_sibling_module(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    if spec is None or spec.loader is None:
        raise ImportError(name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HTML = load_sibling_module("session_analysis_ui").HTML
_inspect = load_sibling_module("session_inspect")


def make_handler(analyzer: CodexUsageAnalyzer) -> type[BaseHTTPRequestHandler]:
    inspector = _inspect.SessionInspector(read_rollout_jsonl)

    class Handler(BaseHTTPRequestHandler):
        server_version = "CodexUsageDashboard/1.0"

        def log_message(self, fmt: str, *args: Any) -> None:
            try:
                if sys.stderr is not None and not sys.stderr.closed:
                    sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
            except Exception:
                pass

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            if path == "/":
                self.send_bytes(HTML.encode("utf-8"), "text/html; charset=utf-8")
                return

            if path == "/api/health":
                self.send_json(
                    {
                        "ok": True,
                        "app": "codex-usage-dashboard",
                        "features": DASHBOARD_FEATURES,
                        "device_short_code": analyzer.remote_store.current_device_code if analyzer.remote_store else current_device_short_code(),
                    }
                )
                return

            if path.startswith("/api/analysis/"):
                try:
                    snapshot_token = query.get("snapshot_token", [""])[0] or None
                    if path != "/api/analysis/sessions" and not snapshot_token:
                        raise ValueError("snapshot_token is required; refresh the session list")
                    snapshot = analyzer.analysis_snapshot(snapshot_token if path != "/api/analysis/sessions" else None)
                    analysis = snapshot["analysis"]
                    if path == "/api/analysis/sessions":
                        self.send_json({"snapshot_token": snapshot["snapshot_token"], "generated_at": snapshot["generated_at"], "roots": analysis["roots"]})
                        return
                    root_id = query.get("id", [""])[0]
                    if root_id not in analysis["usages"]:
                        self.send_json({"error": "conversation not found"}, status=404)
                        return
                    if path == "/api/analysis/usage":
                        self.send_json(analysis["usages"][root_id])
                        return
                    threads = analysis["sources"][root_id]
                    if path == "/api/analysis/events":
                        result = inspector.events(root_id, snapshot["snapshot_token"], threads,
                            agent_id=query.get("agent_id", [""])[0], category=query.get("category", [""])[0],
                            offset=int(query.get("offset", ["0"])[0]), limit=int(query.get("limit", ["100"])[0]))
                        self.send_json(result)
                        return
                    if path == "/api/analysis/event":
                        result = inspector.event(root_id, snapshot["snapshot_token"], threads, query.get("event_id", [""])[0])
                        if result is None:
                            self.send_json({"error": "event not found"}, status=404)
                        else:
                            self.send_json(result)
                        return
                except (SnapshotStaleError, _inspect.InspectSourceChanged):
                    self.send_json({"error": "snapshot stale", "code": "snapshot_stale"}, status=409)
                    return
                except (ValueError, _inspect.InspectBadRequest) as exc:
                    self.send_json({"error": str(exc)}, status=400)
                    return
                except KeyError:
                    self.send_json({"error": "event not found"}, status=404)
                    return
                self.send_json({"error": "not found"}, status=404)
                return

            if path == "/api/sessions":
                period = query.get("period", ["today"])[0]
                start_date = query.get("start", [""])[0] or None
                end_date = query.get("end", [""])[0] or None
                snapshot = analyzer.scan(period, start_date, end_date)
                payload = {
                    "snapshot_token": snapshot["snapshot_token"],
                    "generated_at": snapshot["generated_at"],
                    "codex_home": snapshot["codex_home"],
                    "codex_sources": snapshot.get("codex_sources", []),
                    "period": snapshot["period"],
                    "summary": snapshot["summary"],
                    "sessions": snapshot["sessions"],
                    "daily_usage": snapshot.get("daily_usage", []),
                    "daily_usage_complete": snapshot.get("daily_usage_complete", False),
                    "current_device_short_code": analyzer.remote_store.current_device_code if analyzer.remote_store else current_device_short_code(),
                    "remotes": analyzer.remote_store.list_remotes() if analyzer.remote_store else [],
                }
                self.send_bytes(
                    analyzer.session_payload_bytes(snapshot, payload),
                    "application/json; charset=utf-8",
                )
                return

            if path == "/api/daily-usage":
                snapshot = analyzer.scan()
                self.send_json(
                    {
                        "generated_at": snapshot["generated_at"],
                        "daily_usage": snapshot.get("daily_usage", []),
                        "daily_usage_complete": snapshot.get("daily_usage_complete", True),
                    }
                )
                return

            if path == "/api/session":
                uid = query.get("id", [""])[0]
                period = query.get("period", ["today"])[0]
                start_date = query.get("start", [""])[0] or None
                end_date = query.get("end", [""])[0] or None
                snapshot_token = query.get("snapshot_token", [""])[0] or None
                try:
                    detail = analyzer.get_detail(
                        uid,
                        period,
                        start_date,
                        end_date,
                        snapshot_token=snapshot_token,
                    )
                except SnapshotStaleError:
                    self.send_json(
                        {"error": "snapshot stale", "code": "snapshot_stale"},
                        status=409,
                    )
                    return
                if detail is None:
                    self.send_json({"error": "session not found"}, status=404)
                    return
                self.send_json(detail)
                return

            if path == "/api/export.json":
                body = analyzer.export_snapshot_json().encode("utf-8")
                device_code = analyzer.remote_store.current_device_code if analyzer.remote_store else current_device_short_code()
                filename = f"cousash-{device_code}.json"
                self.send_bytes(
                    body,
                    "application/json; charset=utf-8",
                    extra_headers={"Content-Disposition": f'attachment; filename="{filename}"'},
                )
                return

            if path == "/api/remotes":
                store = analyzer.remote_store
                self.send_json(
                    {
                        "current_device_short_code": store.current_device_code if store else current_device_short_code(),
                        "remotes": store.list_remotes() if store else [],
                    }
                )
                return

            self.send_json({"error": "not found"}, status=404)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                payload = self.read_json_body()
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return

            store = analyzer.remote_store
            if store is None:
                self.send_json({"ok": False, "error": "remote snapshots are not enabled"}, status=400)
                return

            try:
                if path == "/api/remotes/import":
                    snapshot = payload.get("snapshot")
                    label = payload.get("label") if isinstance(payload.get("label"), str) else None
                    allow_current = bool(payload.get("allow_current_device"))
                    result = store.import_snapshot(snapshot, label=label, allow_current_device=allow_current)
                    self.send_json(result, status=200 if result.get("ok") else 409)
                    return

                if path == "/api/remotes/rename":
                    device_code = str(payload.get("device_short_code") or "")
                    label = str(payload.get("label") or "")
                    remote = store.rename_remote(device_code, label)
                    self.send_json({"ok": True, "remote": remote})
                    return

                if path == "/api/remotes/delete":
                    if payload.get("confirm") is not True:
                        self.send_json({"ok": False, "error": "delete requires confirmation"}, status=400)
                        return
                    store.delete_remote(str(payload.get("device_short_code") or ""))
                    self.send_json({"ok": True})
                    return
            except FileNotFoundError:
                self.send_json({"ok": False, "error": "remote data not found"}, status=404)
                return
            except ValueError as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=400)
                return

            self.send_json({"ok": False, "error": "not found"}, status=404)

        def read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            if length > 100 * 1024 * 1024:
                raise ValueError("request body is too large")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid JSON body") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def send_json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_bytes(body, "application/json; charset=utf-8", status=status)

        def send_bytes(
            self,
            body: bytes,
            content_type: str,
            status: int = 200,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if extra_headers:
                for key, value in extra_headers.items():
                    self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    return Handler


class FixedPortHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


DASHBOARD_PROCESS_MARKERS = ("codex_usage_dashboard.py", "codex-usage-dashboard")


def is_dashboard_command(command: str) -> bool:
    lowered = command.lower()
    return any(marker in lowered for marker in DASHBOARD_PROCESS_MARKERS)


def run_text(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def listening_pids_for_port(port: int) -> list[int]:
    if platform.system() == "Windows":
        output = run_text(["netstat", "-ano", "-p", "TCP"])
        pids: set[int] = set()
        suffix = f":{port}"
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0].upper() == "TCP" and parts[1].endswith(suffix) and parts[3].upper() == "LISTENING":
                try:
                    pids.add(int(parts[4]))
                except ValueError:
                    pass
        return sorted(pids)

    lsof = shutil.which("lsof")
    if not lsof:
        return []
    output = run_text([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"])
    pids: list[int] = []
    for line in output.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid not in pids:
            pids.append(pid)
    return pids


def command_for_pid(pid: int) -> str:
    if pid == os.getpid():
        return ""
    if platform.system() == "Windows":
        output = run_text(["wmic", "process", "where", f"processid={pid}", "get", "CommandLine", "/value"])
        for line in output.splitlines():
            if line.startswith("CommandLine="):
                return line.removeprefix("CommandLine=").strip()
        return ""
    return run_text(["ps", "-p", str(pid), "-o", "command="])


def terminate_process(pid: int) -> None:
    if pid == os.getpid():
        return
    try:
        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=3, check=False)
            return
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        return


def release_dashboard_port(port: int) -> None:
    pids = listening_pids_for_port(port)
    if not pids:
        return

    blockers: list[str] = []
    for pid in pids:
        command = command_for_pid(pid)
        if command and is_dashboard_command(command):
            safe_print(f"Stopping existing Codex Usage Dashboard on port {port} (pid {pid}).")
            terminate_process(pid)
        else:
            blockers.append(f"{pid}: {command or 'unknown process'}")

    if blockers:
        joined = "; ".join(blockers)
        raise RuntimeError(f"Port {port} is already in use by a non-dashboard process: {joined}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local read-only Codex usage dashboard.")
    parser.add_argument(
        "--codex-home",
        type=Path,
        action="append",
        default=None,
        help="Path to a Codex home directory. Can be provided multiple times.",
    )
    parser.add_argument(
        "--no-auto-windows",
        action="store_true",
        help="Do not auto-add the Windows ~/.codex directory when running under WSL.",
    )
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",), help="Local bind host (127.0.0.1).")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind. Defaults to the fixed dashboard port 8765.")
    parser.add_argument(
        "--parse-workers",
        type=int,
        default=environment_int("COUSASH_PARSE_WORKERS", DEFAULT_PARSE_WORKERS),
        help=f"Worker processes for large cold parses. Defaults to {DEFAULT_PARSE_WORKERS}; use 0 to disable.",
    )
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser.")
    parser.add_argument("--once", action="store_true", help="Scan once and print a short summary instead of serving the UI.")
    parser.add_argument("--json", action="store_true", help="With --once, print JSON.")
    parser.add_argument(
        "--export-snapshot",
        nargs="?",
        const="",
        default=None,
        help="Export this device's full Cousash JSON snapshot. Optionally pass an output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    sources = (
        codex_sources_from_homes(args.codex_home)
        if args.codex_home
        else default_codex_sources(include_windows=not args.no_auto_windows)
    )
    remote_store = RemoteSnapshotStore()
    persistent_cache = PersistentParseCache()
    analyzer = CodexUsageAnalyzer(
        sources,
        remote_store=remote_store,
        persistent_cache=persistent_cache,
        parallel_workers=args.parse_workers,
    )
    if args.export_snapshot is not None:
        body = analyzer.export_snapshot_json()
        output = Path(args.export_snapshot).expanduser() if args.export_snapshot else Path.cwd() / f"cousash-{remote_store.current_device_code}.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(body + "\n", encoding="utf-8")
        safe_print(str(output.resolve()))
        analyzer.close()
        return 0

    if args.once:
        snapshot = analyzer.scan()
        if args.json:
            payload = {
                "generated_at": snapshot["generated_at"],
                "codex_home": snapshot["codex_home"],
                "codex_sources": snapshot.get("codex_sources", []),
                "summary": snapshot["summary"],
                "sessions": snapshot["sessions"],
                "cache_metrics": analyzer.cache_metrics,
            }
            safe_print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            usage = snapshot["summary"]["usage"]
            safe_print(f"Codex homes: {snapshot['codex_home']}")
            safe_print(f"Sessions: {snapshot['summary']['session_count']}")
            safe_print(f"Total tokens: {usage['total_tokens']:,}")
            if snapshot["sessions"]:
                top = snapshot["sessions"][0]
                safe_print(f"Top session: {top.get('title', top.get('session_id'))} ({top['total_token_usage']['total_tokens']:,})")
        analyzer.close()
        return 0

    port = args.port
    release_dashboard_port(port)
    try:
        server = FixedPortHTTPServer((args.host, port), make_handler(analyzer))
    except OSError as exc:
        raise RuntimeError(f"Port {port} is already in use and could not be released.") from exc
    url = f"http://{args.host}:{port}/"
    safe_print(f"Codex Usage Dashboard: {url}")
    safe_print(f"Codex homes: {analyzer.codex_home_display}")
    safe_print("Press Ctrl+C to stop.")
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url, new=2)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        safe_print("\nStopping.")
    finally:
        server.server_close()
        analyzer.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
