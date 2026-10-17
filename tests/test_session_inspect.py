import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "codex-usage-dashboard" / "scripts"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inspect = load_module("session_inspect_tests", SCRIPTS / "session_inspect.py")
dashboard = load_module("dashboard_inspect_tests", SCRIPTS / "codex_usage_dashboard.py")


def row(kind, payload=None, timestamp="2026-10-16T09:00:00Z"):
    value = {"type": kind}
    if timestamp is not None:
        value["timestamp"] = timestamp
    if payload is not None:
        value["payload"] = payload
    return value


class SessionInspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.calls = []

        def reader(path, **kwargs):
            self.calls.append((path, kwargs))
            return dashboard.read_rollout_jsonl(path, **kwargs)

        self.inspector = inspect.SessionInspector(reader)

    def tearDown(self):
        self.temp.cleanup()

    def source(self, agent, rows, prefix=""):
        path = self.root / (agent + ".jsonl")
        path.write_text(prefix + "\n".join(json.dumps(item) for item in rows) + "\n", encoding="utf-8")
        stat = path.stat()
        return {"agent_id": agent, "session_id": "session-" + agent, "role": "Main" if agent == "main" else "Explorer",
                "label": agent, "path": path, "source_root": self.root, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}

    def page(self, sources, **kwargs):
        return self.inspector.events("root", "snapshot", sources, **kwargs)

    def detail(self, sources, event):
        return self.inspector.event("root", "snapshot", sources, event["id"])

    def test_utc_order_physical_lines_and_filter_pagination(self):
        main = self.source("main", [
            row("response_item", {"type": "message", "content": [{"text": "first"}]}, "2026-10-16T10:00:00+01:00"),
            row("response_item", {"type": "message", "content": [{"text": "second"}]}),
            row("session_meta", {"id": "main"}, None),
        ], prefix="\nnot JSON\n")
        child = self.source("child", [row("response_item", {"type": "message", "content": [{"text": "child"}]})])
        page = self.page([main, child])
        messages = [item for item in page["events"] if item["category"] == "message"]
        self.assertEqual([item["preview"] for item in messages], ["first", "second", "child"])
        self.assertEqual(messages[0]["source"], {"filename": "main.jsonl", "line": 3})
        self.assertIn("undated", page["events"][-1]["statuses"])
        self.assertEqual(page["inventory"]["threads"], 2)
        self.assertTrue(page["warnings"])
        filtered = self.page([main, child], agent_id="main", category="message", offset=1, limit=1)
        self.assertEqual(filtered["total"], 2)
        self.assertEqual(filtered["events"][0]["preview"], "second")
        self.assertEqual(filtered["inventory"], page["inventory"])
        self.assertEqual(len(self.calls), 2, "cached pages must not rescan payloads")

    def test_interleaved_tool_pairs_stay_within_thread_and_collisions_visible(self):
        main = self.source("main", [
            row("response_item", {"type": "function_call", "name": "read", "call_id": "a", "arguments": "a"}),
            row("response_item", {"type": "custom_tool_call", "name": "write", "call_id": "b", "input": "b"}),
            row("response_item", {"type": "custom_tool_call_output", "call_id": "b", "output": "B"}),
            row("response_item", {"type": "function_call_output", "call_id": "a", "output": "A"}),
            row("response_item", {"type": "function_call", "call_id": "missing", "name": "lost"}),
            row("response_item", {"type": "function_call_output", "call_id": "orphan", "output": "orphan"}),
            row("response_item", {"type": "function_call", "call_id": "collision", "name": "one"}),
            row("response_item", {"type": "function_call", "call_id": "collision", "name": "two"}),
            row("response_item", {"type": "function_call_output", "call_id": "collision", "output": "ambiguous"}),
        ])
        child = self.source("child", [row("response_item", {"type": "function_call_output", "call_id": "missing", "output": "different thread"})])
        page = self.page([main, child], category="tools")
        self.assertEqual(page["total"], 10)
        events = page["events"]
        self.assertEqual(events[0]["related_event_ids"], [events[3]["id"]])
        self.assertEqual(events[1]["related_event_ids"], [events[2]["id"]])
        self.assertIn("unmatched_call", events[4]["statuses"])
        self.assertIn("unmatched_result", events[-1]["statuses"])
        self.assertEqual(page["inventory"]["unmatched_calls"], 1)
        self.assertEqual(page["inventory"]["unmatched_results"], 2)
        self.assertTrue(all("ambiguous_call_id" in item["statuses"] for item in events[6:9]))

    def test_unknown_and_reasoning_availability_encryption_never_exposed(self):
        source = self.source("main", [
            row("response_item", {"type": "reasoning", "summary": [{"type": "summary_text", "text": "Readable summary"}], "encrypted_content": "SECRET"}),
            row("response_item", {"type": "reasoning", "encrypted_content": "SECRET"}),
            row("response_item", {"type": "reasoning"}),
            row("response_item", {"type": "future_tool", "nested": {"encrypted_content": "SECRET"}, "content": "<script>raw</script>"}),
            row("response_item", {"type": "function_call_output", "call_id": "x"}),
            row("turn_context", {"model": "test"}),
            row("session_meta", {"id": "main"}),
        ])
        page = self.page([source])
        inventory = page["inventory"]
        self.assertEqual(inventory["count_readable_reasoning"], 1)
        self.assertEqual(inventory["count_encrypted_reasoning"], 2)
        self.assertEqual(inventory["count_unavailable_reasoning"], 1)
        self.assertEqual(inventory["by_raw_type"]["response_item/future_tool"], 1)
        self.assertIn("unknown_event_type", page["events"][3]["statuses"])
        self.assertIn("content_unavailable", page["events"][4]["statuses"])
        self.assertEqual(self.page([source], category="other")["total"], 3)
        self.assertNotIn("SECRET", json.dumps(page))
        for event in page["events"]:
            detail = self.detail([source], event)
            self.assertNotIn("encrypted_content", json.dumps(detail))
            self.assertNotIn("SECRET", json.dumps(detail))
            self.assertEqual(detail["event"]["source"], event["source"])
        detail = self.detail([source], page["events"][3])
        self.assertIn("<script>raw</script>", detail["text"], "server delivers plain data; UI must escape")

    def test_large_output_is_not_retained_and_detail_is_lazy_bounded(self):
        output = "LARGE-MARKER-" + "x" * 800_000
        source = self.source("main", [row("response_item", {"type": "function_call_output", "call_id": "a", "output": output})])
        page = self.page([source])
        self.assertLess(len(json.dumps(page)), 2000)
        cached = next(iter(self.inspector._cache.values()))
        self.assertLess(len(repr(cached)), 5000)
        self.assertEqual(len(self.calls), 1)
        detail = self.detail([source], page["events"][0])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[-1][1]["end_offset"], source["size"])
        self.assertTrue(self.calls[-1][1]["full_payload"])
        self.assertTrue(detail["truncated"])
        self.assertIn("truncated", detail["statuses"])
        self.assertEqual(len(detail["text"]), inspect.DETAIL_TEXT_LIMIT)
        self.assertIsNone(detail["record"])
        self.assertIn("LARGE-MARKER-", detail["text"])

    def test_mutated_snapshot_rejected_for_cached_page_and_detail(self):
        source = self.source("main", [row("session_meta", {"id": "main"})])
        event = self.page([source])["events"][0]
        with source["path"].open("a", encoding="utf-8") as handle:
            handle.write("{}\n")
        with self.assertRaises(inspect.InspectSourceChanged):
            self.page([source])
        with self.assertRaises(inspect.InspectSourceChanged):
            self.detail([source], event)

    def test_mutation_during_scan_and_detail_rejected(self):
        source = self.source("main", [row("response_item", {"type": "message", "content": "test"})])
        def append_reader(path, **kwargs):
            yield from dashboard.read_rollout_jsonl(path, **kwargs)
            with path.open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
        inspector = inspect.SessionInspector(append_reader)
        with self.assertRaises(inspect.InspectSourceChanged):
            inspector.events("root", "snapshot", [source])
        source = self.source("main", [row("response_item", {"type": "message", "content": "test"})])
        event = self.page([source])["events"][0]
        def mutate_detail_reader(path, **kwargs):
            records = list(dashboard.read_rollout_jsonl(path, **kwargs))
            with path.open("a", encoding="utf-8") as handle:
                handle.write("{}\n")
            return iter(records)
        self.inspector.reader = mutate_detail_reader
        with self.assertRaises(inspect.InspectSourceChanged):
            self.detail([source], event)

    def test_identifiers_filters_pagination_and_paths_cannot_select_sources(self):
        source = self.source("main", [row("session_meta", {"id": "main"})])
        event = self.page([source])["events"][0]
        for kwargs in ({"offset": -1}, {"offset": True}, {"limit": 1001}, {"limit": 0}, {"category": "../../secret"}, {"agent_id": "../../secret"}):
            with self.assertRaises(inspect.InspectBadRequest):
                self.page([source], **kwargs)
        with self.assertRaises(inspect.InspectBadRequest):
            self.inspector.event("root", "snapshot", [source], str(source["path"]))
        with self.assertRaises(inspect.InspectBadRequest):
            self.inspector.event("other-root", "snapshot", [source], event["id"])
        with self.assertRaises(inspect.InspectBadRequest):
            self.inspector.event("root", "other-snapshot", [source], event["id"])
        outside = dict(source, source_root=self.root / "nested")
        outside["source_root"].mkdir()
        with self.assertRaises(inspect.InspectBadRequest):
            self.page([outside])
        result = self.page([source])
        result["events"][0]["statuses"].append("injected")
        self.assertNotIn("injected", self.page([source])["events"][0]["statuses"])

    def test_symlink_escape_is_rejected_when_symlinks_available(self):
        source = self.source("main", [row("session_meta", {"id": "main"})])
        nested = self.root / "nested"
        nested.mkdir()
        link = nested / "link.jsonl"
        try:
            link.symlink_to(source["path"])
        except OSError as exc:
            self.skipTest(f"Symlinks unavailable: {exc}")
        with self.assertRaises(inspect.InspectBadRequest):
            self.page([dict(source, path=link, source_root=nested)])

    def test_empty_remote_history_is_explicitly_unavailable(self):
        page = self.page([])
        self.assertEqual(page["events"], [])
        self.assertEqual(page["inventory"]["threads"], 0)
        self.assertEqual(page["warnings"][0]["code"], "history_unavailable")

    def test_resumed_sources_pair_within_same_instance_and_count_once(self):
        first = self.source("main", [row("response_item", {"type": "function_call", "call_id": "resumed", "name": "read"})])
        second = self.source("resumed", [row("response_item", {"type": "function_call_output", "call_id": "resumed", "output": "result"})])
        second.update(agent_id=first["agent_id"], session_id=first["session_id"])
        page = self.page([first, second])
        self.assertEqual(page["inventory"]["threads"], 1)
        self.assertEqual(page["inventory"]["unmatched_calls"], 0)
        self.assertEqual(page["inventory"]["unmatched_results"], 0)
        self.assertEqual(page["events"][0]["related_event_ids"], [page["events"][1]["id"]])

    def test_call_families_do_not_pair_by_reused_id(self):
        source = self.source("main", [
            row("response_item", {"type": "function_call", "call_id": "same", "name": "function"}),
            row("response_item", {"type": "custom_tool_call_output", "call_id": "same", "output": "custom"}),
        ])
        page = self.page([source])
        self.assertEqual(page["inventory"]["unmatched_calls"], 1)
        self.assertEqual(page["inventory"]["unmatched_results"], 1)

    def test_bom_unicode_lazy_offset_and_structured_tool_output(self):
        source = self.source("main", [
            row("response_item", {"type": "message", "content": [{"text": "Snowman ☃"}]}),
            row("response_item", {"type": "function_call_output", "call_id": "structured", "output": {"count": 3}}),
        ], prefix="\ufeff")
        page = self.page([source])
        self.assertEqual(page["events"][0]["preview"], "Snowman ☃")
        detail = self.detail([source], page["events"][1])
        self.assertEqual(detail["record"]["payload"]["output"], {"count": 3})
        self.assertEqual(detail["event"]["source"]["line"], 2)
        self.assertIn("readable", detail["statuses"])
        self.assertNotIn("_source", detail["record"])
        self.assertGreater(self.calls[-1][1]["start_offset"], 0)

    def test_replacement_with_identical_size_and_mtime_is_rejected_after_inventory(self):
        source = self.source("main", [row("session_meta", {"id": "main"})])
        self.page([source])
        replacement = self.root / "replacement.jsonl"
        replacement.write_bytes(source["path"].read_bytes())
        os.utime(replacement, ns=(source["mtime_ns"], source["mtime_ns"]))
        replacement.replace(source["path"])
        with self.assertRaises(inspect.InspectSourceChanged):
            self.page([source])

    def test_snapshot_inode_rejects_replacement_before_first_inventory(self):
        source = self.source("main", [row("session_meta", {"id": "main"})])
        stat = source["path"].stat()
        source.update(device=stat.st_dev, inode=stat.st_ino)
        replacement = self.root / "replacement.jsonl"
        replacement.write_bytes(source["path"].read_bytes())
        os.utime(replacement, ns=(source["mtime_ns"], source["mtime_ns"]))
        replacement.replace(source["path"])
        with self.assertRaises(inspect.InspectSourceChanged):
            self.page([source])


if __name__ == "__main__":
    unittest.main()
