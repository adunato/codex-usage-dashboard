"""Source-backed, lazy event inspection for trusted local rollout descriptors.

Only bounded event metadata is cached. Full records are reread through the same
JSONL reader used by the dashboard when the user expands an event.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import threading
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Callable


class InspectSourceChanged(Exception):
    """The source no longer matches the published dashboard snapshot."""


class InspectBadRequest(ValueError):
    """An event identifier, filter, or pagination value is invalid."""


EventPage = dict[str, Any]
EventDetail = dict[str, Any]
DETAIL_TEXT_LIMIT = 200_000
PREVIEW_LIMIT = 180
CATEGORIES = ("message", "reasoning", "tool_call", "tool_result", "context", "lifecycle", "other")
CALL_TYPES = {"function_call", "custom_tool_call", "tool_call", "web_search_call", "local_shell_call", "image_generation_call"}
RESULT_TYPES = {"function_call_output", "custom_tool_call_output", "tool_result", "tool_search_output"}
MESSAGE_TYPES = {"message", "user_message", "agent_message", "assistant_message"}
REASONING_TYPES = {"reasoning", "agent_reasoning", "reasoning_summary", "agent_reasoning_raw_content"}
CONTEXT_TYPES = {"turn_context", "compacted", "token_usage_record", "token_count", "thread_settings_applied", "context_compacted", "world_state"}
LIFECYCLE_TYPES = {"session_meta", "task_started", "task_complete", "turn_started", "turn_complete", "turn_aborted", "session_created", "shutdown_complete", "inter_agent_communication_metadata"}


def _category(outer: str, inner: str) -> str:
    kind = inner or outer
    if kind in MESSAGE_TYPES:
        return "message"
    if kind in REASONING_TYPES:
        return "reasoning"
    if kind in CALL_TYPES:
        return "tool_call"
    if kind in RESULT_TYPES:
        return "tool_result"
    if kind in CONTEXT_TYPES or outer in CONTEXT_TYPES:
        return "context"
    if kind in LIFECYCLE_TYPES or outer in LIFECYCLE_TYPES:
        return "lifecycle"
    return "other"


def _text(value: Any, limit: int = PREVIEW_LIMIT) -> str:
    """Extract a bounded readable prefix without serializing large payloads."""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        parts: list[str] = []
        remaining = limit
        for item in value:
            part = _text(item, remaining)
            if part:
                parts.append(part)
                remaining -= len(part) + 1
            if remaining <= 0:
                break
        return " ".join(parts)[:limit]
    if isinstance(value, dict):
        for key in ("text", "message", "summary", "content", "output", "error", "arguments", "input"):
            if key in value:
                result = _text(value[key], limit)
                if result:
                    return result
    return ""


def _encrypted(value: Any) -> bool:
    if isinstance(value, dict):
        return any((key == "encrypted_content" and bool(item)) or _encrypted(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_encrypted(item) for item in value)
    return False


def _sanitized(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitized(item) for key, item in value.items() if key != "encrypted_content"}
    if isinstance(value, list):
        return [_sanitized(item) for item in value]
    return value


def _timestamp(value: Any) -> tuple[str | None, dt.datetime]:
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return value, parsed.astimezone(dt.timezone.utc)
        except (ValueError, OverflowError):
            pass
    return None, dt.datetime.max.replace(tzinfo=dt.timezone.utc)


class SessionInspector:
    def __init__(self, reader: Callable[..., Any]) -> None:
        self.reader = reader
        self._cache: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
        self._lock = threading.RLock()

    @staticmethod
    def _sources(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sources = []
        for thread in threads:
            source = dict(thread)
            try:
                path = Path(source["path"])
                root = Path(source["source_root"]).resolve(strict=True)
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root) or not resolved.is_file():
                    raise InspectBadRequest("Inspect source must be a local rollout inside its source root")
                source["original_path"] = path.absolute()
                source["path"] = resolved
                source["source_root"] = root
                source["size"] = int(source["size"])
                source["mtime_ns"] = int(source["mtime_ns"])
                stat = resolved.stat()
                source["identity"] = (int(source.get("device", stat.st_dev)), int(source.get("inode", stat.st_ino)))
            except InspectBadRequest:
                raise
            except (KeyError, TypeError, ValueError) as exc:
                raise InspectBadRequest("Invalid Inspect source descriptor") from exc
            except OSError as exc:
                raise InspectSourceChanged("Session source is no longer available; refresh the session list") from exc
            sources.append(source)
        return sources

    @staticmethod
    def _verify(sources: list[dict[str, Any]]) -> None:
        for source in sources:
            try:
                # Resolve again: a symlink may have changed since the scan began.
                path = source["path"]
                resolved = source["original_path"].resolve(strict=True)
                stat = path.stat()
                if (not resolved.is_relative_to(source["source_root"])
                        or resolved != path or not path.is_file()
                        or stat.st_size != source["size"]
                        or stat.st_mtime_ns != source["mtime_ns"]
                        or (stat.st_dev, stat.st_ino) != source["identity"]):
                    raise InspectSourceChanged("Session source changed; refresh the session list")
            except OSError as exc:
                raise InspectSourceChanged("Session source is no longer available; refresh the session list") from exc

    @staticmethod
    def _key(root_id: str, snapshot_token: str, sources: list[dict[str, Any]]) -> tuple[Any, ...]:
        return (root_id, snapshot_token, tuple((str(s["path"]), str(s["source_root"]), s["size"], s["mtime_ns"],
                    str(s.get("agent_id", "")), str(s.get("session_id", "")), str(s.get("role", "")), str(s.get("label", ""))) for s in sources))

    def _inventory(self, root_id: str, snapshot_token: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
        self._verify(sources)
        key = self._key(root_id, snapshot_token, sources)
        if key in self._cache:
            self._cache.move_to_end(key)
            self._verify(self._cache[key]["sources"])
            return self._cache[key]
        entries = []
        warnings = [] if sources else [{"code": "history_unavailable", "message": "Full session history not available on this device"}]
        pairs: dict[tuple[str, str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"tool_call": [], "tool_result": []})
        readable_reasoning = encrypted_reasoning = unavailable_reasoning = 0
        for rank, source in enumerate(sources):
            try:
                for record in self.reader(source["path"], end_offset=source["size"], full_payload=True, with_source=True):
                    location = record.get("_source", {})
                    if not all(isinstance(location.get(key), int) for key in ("line", "offset", "length")):
                        raise InspectBadRequest("JSONL reader did not provide a source reference")
                    outer = str(record.get("type") or "unknown")
                    payload = record.get("payload")
                    payload = payload if isinstance(payload, dict) else {}
                    inner = str(payload.get("type") or "")
                    raw_type = outer + ("/" + inner if inner else "")
                    category = _category(outer, inner)
                    timestamp, order_time = _timestamp(record.get("timestamp"))
                    statuses = [] if timestamp is not None else ["undated"]
                    if record.get("__parse_error__"):
                        statuses.extend(["content_unavailable", "invalid_json"])
                        warnings.append({"code": "invalid_json", "message": f"Unreadable JSON record in {source['path'].name}, line {location['line']}", "agent_id": source["agent_id"]})
                    readable = _text(payload)
                    if not readable and category == "tool_result" and any(
                            field in payload and payload[field] is not None for field in ("output", "error", "content")):
                        readable = "Recorded tool result (expand to view)"
                    encrypted = category == "reasoning" and _encrypted(record)
                    if category == "reasoning":
                        readable_reasoning += bool(readable)
                        encrypted_reasoning += bool(encrypted)
                        unavailable_reasoning += not readable and not encrypted
                        if encrypted:
                            statuses.append("encrypted_reasoning")
                    if category == "other":
                        statuses.append("unknown_event_type")
                    if readable:
                        statuses.append("readable")
                    elif category in {"message", "reasoning", "tool_result"}:
                        statuses.append("content_unavailable")
                    preview = readable or ("Encrypted reasoning" if encrypted else "Content unavailable" if "content_unavailable" in statuses else raw_type)
                    if category == "tool_call" and payload.get("name"):
                        preview = str(payload["name"])[:PREVIEW_LIMIT] + (": " + readable if readable else "")
                    identity = f"{root_id}\0{snapshot_token}\0{rank}\0{source['session_id']}\0{location['offset']}\0{location['line']}"
                    event = {
                        "id": hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32],
                        "timestamp": timestamp, "session_id": source["session_id"], "agent_id": source["agent_id"],
                        "category": category, "raw_type": raw_type, "preview": preview[:PREVIEW_LIMIT],
                        "source": {"filename": source["path"].name, "line": location["line"]},
                        "statuses": list(dict.fromkeys(statuses)), "related_event_ids": [],
                    }
                    call_id = payload.get("call_id")
                    if not call_id and category == "tool_call":
                        call_id = payload.get("id")
                    if isinstance(call_id, (str, int)) and str(call_id):
                        event["call_id"] = str(call_id)
                    entry = {"event": event, "source": source, "offset": location["offset"], "length": location["length"], "order": (order_time, rank, location["line"])}
                    entries.append(entry)
                    if category in {"tool_call", "tool_result"}:
                        if "call_id" in event:
                            family = "function" if inner.startswith("function_call") else "custom" if inner.startswith("custom_tool_call") else "tool"
                            pairs[(source["agent_id"], source["session_id"], family, event["call_id"])][category].append(event)
                        else:
                            event["statuses"].append("unmatched_call" if category == "tool_call" else "unmatched_result")
            except OSError:
                warnings.append({"code": "source_unreadable", "message": f"Session source unreadable: {source['path'].name}", "agent_id": source["agent_id"]})
            finally:
                self._verify(sources)
        for pair in pairs.values():
            calls, results = pair["tool_call"], pair["tool_result"]
            for events, opposite, status in ((calls, results, "unmatched_call"), (results, calls, "unmatched_result")):
                for event in events:
                    event["related_event_ids"] = [other["id"] for other in opposite]
                    if not opposite:
                        event["statuses"].append(status)
                    if len(calls) > 1 or len(results) > 1:
                        event["statuses"].append("ambiguous_call_id")
        entries.sort(key=lambda entry: entry["order"])
        events = [entry["event"] for entry in entries]
        result = {
            "entries": {entry["event"]["id"]: entry for entry in entries}, "events": events,
            "inventory": {
                "by_category": {category: sum(event["category"] == category for event in events) for category in CATEGORIES},
                "by_raw_type": dict(sorted(Counter(event["raw_type"] for event in events).items())),
                "threads": len({(source["agent_id"], source["session_id"]) for source in sources}), "count_readable_reasoning": readable_reasoning,
                "count_encrypted_reasoning": encrypted_reasoning, "count_unavailable_reasoning": unavailable_reasoning,
                "unmatched_calls": sum("unmatched_call" in event["statuses"] for event in events),
                "unmatched_results": sum("unmatched_result" in event["statuses"] for event in events),
            }, "warnings": warnings, "sources": sources,
        }
        self._verify(sources)
        self._cache[key] = result
        while len(self._cache) > 4:
            self._cache.popitem(last=False)
        return result

    def events(self, root_id: str, snapshot_token: str, threads: list[dict[str, Any]], *,
               agent_id: str = "", category: str = "", offset: int = 0, limit: int = 100) -> EventPage:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise InspectBadRequest("Offset must be nonnegative and limit must be between 1 and 500")
        if category not in ("", "tools", *CATEGORIES):
            raise InspectBadRequest("Unknown event category")
        with self._lock:
            sources = self._sources(threads)
            if agent_id and agent_id not in {source.get("agent_id") for source in sources}:
                raise InspectBadRequest("Unknown agent instance")
            inventory = self._inventory(root_id, snapshot_token, sources)
            categories = {"tool_call", "tool_result"} if category == "tools" else {"context", "lifecycle", "other"} if category == "other" else {category}
            filtered = [event for event in inventory["events"] if (not agent_id or event["agent_id"] == agent_id) and (not category or event["category"] in categories)]
            self._verify(sources)
            return copy.deepcopy({"events": filtered[offset:offset + limit], "total": len(filtered), "offset": offset,
                                  "limit": limit, "inventory": inventory["inventory"], "warnings": inventory["warnings"]})

    def event(self, root_id: str, snapshot_token: str, threads: list[dict[str, Any]], event_id: str) -> EventDetail:
        with self._lock:
            sources = self._sources(threads)
            inventory = self._inventory(root_id, snapshot_token, sources)
            entry = inventory["entries"].get(event_id)
            if entry is None:
                raise InspectBadRequest("Unknown event identifier for this session snapshot")
            event = copy.deepcopy(entry["event"])
            record = None
            statuses = list(event["statuses"])
            try:
                self._verify(sources)
                record = next(iter(self.reader(entry["source"]["path"], start_offset=entry["offset"],
                    end_offset=entry["offset"] + entry["length"], full_payload=True, with_source=True)), None)
            except OSError:
                statuses.append("content_unavailable")
            finally:
                self._verify(sources)
            if record is None or record.get("__parse_error__"):
                return {"event": event, "record": None, "text": "Content unavailable", "truncated": False,
                        "statuses": list(dict.fromkeys([*statuses, "content_unavailable"]))}
            record = _sanitized({key: value for key, value in record.items() if key != "_source"})
            text = json.dumps(record, ensure_ascii=False, indent=2)
            truncated = len(text) > DETAIL_TEXT_LIMIT
            if truncated:
                statuses.append("truncated")
                text = text[:DETAIL_TEXT_LIMIT]
                record = None
            return {"event": event, "record": record, "text": text, "truncated": truncated,
                    "statuses": list(dict.fromkeys(statuses))}
