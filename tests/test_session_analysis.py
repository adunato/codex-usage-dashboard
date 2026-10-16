import http.client
import importlib.util
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

MODULE_PATH = Path(__file__).resolve().parents[1] / "skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py"
spec = importlib.util.spec_from_file_location("analysis_dashboard", MODULE_PATH)
dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dashboard)


def usage(input_tokens, output_tokens=0, cached=0, reasoning=0):
    return dict(input_tokens=input_tokens, cached_input_tokens=cached, output_tokens=output_tokens,
                reasoning_output_tokens=reasoning, total_tokens=input_tokens + output_tokens)


def row(kind, payload, second=0):
    return {"timestamp": f"2026-10-16T10:00:{second:02d}Z", "type": kind, "payload": payload}


def token(value, second=1, model=None):
    info = {"total_token_usage": value, "last_token_usage": value}
    if model:
        info["model"] = model
    return row("event_msg", {"type": "token_count", "info": info}, second)


def modern(value, contribution, second=1, response="response-1"):
    return row("token_usage_record", {"thread_token_usage": value, "usage": contribution,
                                     "response_id": response}, second)


class SessionAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        self.analyzer = dashboard.CodexUsageAnalyzer(self.home, resolve_project_info=False)

    def tearDown(self):
        self.analyzer.close()
        self.temp.cleanup()

    def write(self, sid, events, parent=None, role=None, fork=None, archive=False):
        meta = {"id": sid}
        if parent:
            meta.update(parent_thread_id=parent, agent_role=role or "")
        if fork:
            meta["forked_from_id"] = fork
            meta["timestamp"] = "2026-10-16T10:00:02Z"
        directory = self.home / ("archived_sessions" if archive else "sessions")
        directory.mkdir(exist_ok=True)
        path = directory / f"rollout-2026-10-16T10-00-00-{sid}.jsonl"
        path.write_text("".join(json.dumps(value) + "\n" for value in [row("session_meta", meta), *events]), encoding="utf-8")
        return path

    def selected(self):
        snapshot = self.analyzer.scan("all")
        self.assertEqual(len(snapshot["analysis"]["roots"]), 1)
        root = snapshot["analysis"]["roots"][0]
        return snapshot["analysis"]["usages"][root["id"]]

    def test_example_reconciles_roles_instances_models_and_subsets(self):
        self.write("main", [token(usage(14000, 3000, 4000, 1000), model="gpt-6.1-sol")])
        self.write("explorer1", [token(usage(6000, 750, 500), model="gpt-6-luna")], "main", "explorer")
        self.write("explorer2", [token(usage(6000, 750, 500), model="gpt-6-luna")], "main", "explorer")
        self.write("worker", [token(usage(10000, 2500, 3000), model="gpt-6.1-sol")], "main", "worker-sol", archive=True)
        result = self.selected()
        self.assertEqual(result["overall"], usage(36000, 7000, 8000, 1000))
        self.assertEqual({r["role"]: r["usage"]["total_tokens"] for r in result["by_role"]},
                         {"Main": 17000, "Explorer": 13500, "Worker Sol": 12500})
        self.assertEqual(len(next(r for r in result["by_role"] if r["role"] == "Explorer")["agents"]), 2)
        self.assertEqual({r["model"]: r["usage"]["total_tokens"] for r in result["by_model"]},
                         {"gpt-6.1-sol": 29500, "gpt-6-luna": 13500})
        self.assertEqual(result["root"]["completeness"], "complete")
        explorers = next(r for r in result["by_role"] if r["role"] == "Explorer")["agents"]
        self.assertEqual({a["label"] for a in explorers}, {"Explorer #1", "Explorer #2"})

    def test_model_switch_uses_effective_delta(self):
        self.write("main", [row("turn_context", {"model": "first"}), token(usage(100, 20), 1),
                            row("turn_context", {"model": "second"}, 2), token(usage(300, 50), 3)])
        result = self.selected()
        self.assertEqual({m["model"]: m["usage"]["total_tokens"] for m in result["by_model"]}, {"first": 120, "second": 230})
        self.assertEqual(result["overall"]["total_tokens"], 350)

    def test_dual_family_and_repeated_response_do_not_double_count(self):
        value = usage(100, 20, 30, 5)
        self.write("main", [modern(value, value), modern(value, value), token(value, 2, "model"), token(value, 3, "model")])
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 120)
        self.assertEqual(result["root"]["completeness"], "complete")

    def test_mismatched_modern_counters_cannot_inflate_canonical_deltas(self):
        self.write("main", [modern(usage(1000), usage(100)), token(usage(100), 2, "first"),
                            modern(usage(1200), usage(200), 3, "response-2"), token(usage(300), 4, "second")])
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 300)
        self.assertEqual({m["model"]: m["usage"]["total_tokens"] for m in result["by_model"]}, {"first": 100, "second": 200})
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("usage_overlap", {w["code"] for w in result["warnings"]})

    def test_modern_only_and_verified_trailing_usage(self):
        value = usage(100, 20)
        self.write("main", [token(value, 1, "model"), modern(usage(150, 30), usage(50, 10), 2)])
        self.assertEqual(self.selected()["overall"]["total_tokens"], 180)
        self.analyzer.close()
        self.analyzer = dashboard.CodexUsageAnalyzer(self.home, resolve_project_info=False)
        self.write("main", [modern(value, value), modern(usage(150, 30), usage(50, 10), 2, "response-2")])
        self.assertEqual(self.selected()["overall"]["total_tokens"], 180)

    def test_inherited_prefix_is_excluded(self):
        inherited = token(usage(100), 1, "model")
        self.write("main", [inherited])
        self.write("child", [inherited, token(usage(140), 3, "model")], "main", "explorer", "main")
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 140)
        self.assertEqual(next(a for a in result["by_agent"] if a["role"] == "Explorer")["usage"]["total_tokens"], 40)

    def test_missing_parent_and_metadata_remain_visible(self):
        self.write("child", [token(usage(100))], "missing-parent")
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 100)
        self.assertEqual(result["by_agent"][0]["role"], "Unknown")
        self.assertEqual(result["by_model"][0]["model"], "Unknown")
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("missing_root", {w["code"] for w in result["warnings"]})

    def test_undated_usage_preserves_known_tokens_and_warns(self):
        event = token(usage(100), model="model")
        event.pop("timestamp")
        self.write("main", [event])
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 100)
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("undated_usage", {w["code"] for w in result["warnings"]})

    def test_counter_reset_is_visibly_incomplete(self):
        self.write("main", [token(usage(10), 1), token(usage(5), 2)])
        result = self.selected()
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("counter_reset", {w["code"] for w in result["warnings"]})

    def test_unique_response_without_cumulative_preserves_known_usage(self):
        event = modern(usage(0), usage(10))
        event["payload"].pop("thread_token_usage")
        self.write("main", [event, event])
        self.assertEqual(self.selected()["overall"]["total_tokens"], 10)

    def test_missing_recorded_child_is_incomplete(self):
        self.write("main", [token(usage(10)), row("event_msg", {
            "type": "item_completed", "item": {"agent_thread_id": "missing-child"}}, 2)])
        result = self.selected()
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("missing_child", {w["code"] for w in result["warnings"]})

    def test_resumed_duplicate_sources_are_not_added_twice(self):
        path = self.write("main", [token(usage(10), 1), token(usage(20), 2)])
        data = path.read_text(encoding="utf-8").replace("10:00:01Z", "10:00:03Z").replace("10:00:02Z", "10:00:04Z")
        path.with_name("duplicate.jsonl").write_text(data, encoding="utf-8")
        result = self.selected()
        self.assertEqual(len(result["by_agent"]), 1)
        self.assertEqual(result["overall"]["total_tokens"], 20)
        self.assertEqual(result["root"]["completeness"], "incomplete")

    def test_event_model_override_does_not_replace_turn_model(self):
        self.write("main", [row("turn_context", {"model": "context"}),
                            token(usage(10), 1, "override"), token(usage(20), 2)])
        result = self.selected()
        self.assertEqual({m["model"]: m["usage"]["total_tokens"] for m in result["by_model"]},
                         {"context": 10, "override": 10})

    def test_remote_summary_without_detail_remains_selectable(self):
        store = dashboard.RemoteSnapshotStore("local-device", self.home / "remotes")
        payload = {"schema": dashboard.SNAPSHOT_SCHEMA, "version": dashboard.SNAPSHOT_VERSION,
                   "device": {"short_code": "remote-device", "label": "Remote"},
                   "snapshot": {"sessions": [{"uid": "one", "session_id": "one", "total_token_usage": usage(10)}],
                                "details_by_uid": {}}}
        self.assertTrue(store.import_snapshot(payload, label="Remote")["ok"])
        self.analyzer.close()
        self.analyzer = dashboard.CodexUsageAnalyzer(self.home, remote_store=store, resolve_project_info=False)
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 10)
        self.assertFalse(result["root"]["inspect_available"])
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("remote_history_unavailable", {w["code"] for w in result["warnings"]})

    def test_explicit_root_does_not_hide_missing_intermediate_parent(self):
        self.write("main", [token(usage(10), model="model")])
        path = self.write("child", [token(usage(10), model="model")], "absent", "explorer")
        data = path.read_text(encoding="utf-8")
        data = data.replace('"id": "child"', '"id": "child", "root_session_id": "main"')
        path.write_text(data, encoding="utf-8")
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 20)
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("missing_parent", {w["code"] for w in result["warnings"]})

    def test_empty_modern_cumulative_uses_unique_response_and_warns(self):
        event = modern({}, usage(10))
        self.write("main", [event])
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 10)
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("invalid_usage", {w["code"] for w in result["warnings"]})

    def test_invalid_counters_preserve_valid_known_values_without_negatives(self):
        bad = {"input_tokens": 10, "cached_input_tokens": -5, "output_tokens": "bad",
               "reasoning_output_tokens": float("inf"), "total_tokens": 10}
        self.write("main", [token(bad, model="model")])
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 10)
        self.assertTrue(all(isinstance(v, int) and v >= 0 for v in result["overall"].values()))
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("invalid_usage", {w["code"] for w in result["warnings"]})

    def test_unsupported_usage_shapes_are_incomplete_without_scan_errors(self):
        self.write("main", [token({"input_tokens": [], "total_tokens": "10"}, model="model"),
                            modern({}, {"input_tokens": float("nan")}, 2)])
        result = self.selected()
        self.assertEqual(result["overall"]["total_tokens"], 0)
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("invalid_usage", {w["code"] for w in result["warnings"]})

    def test_component_decrease_is_incomplete_and_all_rollups_reconcile(self):
        self.write("main", [token(usage(100), 1, "first"), token(usage(50, 100), 2, "second")])
        result = self.selected()
        self.assertEqual(result["root"]["completeness"], "incomplete")
        self.assertIn("counter_reset", {w["code"] for w in result["warnings"]})
        self.assertIn("inconsistent_counters", {w["code"] for w in result["warnings"]})
        for key, total in result["overall"].items():
            for table in ("by_agent", "by_role", "by_model"):
                self.assertEqual(sum(item["usage"][key] for item in result[table]), total)

    def test_shared_reader_full_payload_and_source(self):
        payload = {"type": "reasoning", "summary": "x" * 5000}
        path = self.write("main", [row("response_item", payload)])
        projected = list(dashboard.read_rollout_jsonl(path))[-1]
        full = list(dashboard.read_rollout_jsonl(path, full_payload=True, with_source=True))[-1]
        self.assertEqual(full["payload"], payload)
        self.assertEqual(full["_source"]["line"], 2)
        exact = list(dashboard.read_rollout_jsonl(path, start_offset=full["_source"]["offset"],
                     end_offset=full["_source"]["offset"] + full["_source"]["length"], full_payload=True))
        self.assertEqual(exact[0]["payload"], payload)

    def test_api_snapshot_and_validation(self):
        path = self.write("main", [token(usage(100), model="model")])
        server = dashboard.FixedPortHTTPServer(("127.0.0.1", 0), dashboard.make_handler(self.analyzer))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def get(route, params=None):
            client = http.client.HTTPConnection("127.0.0.1", server.server_port)
            client.request("GET", route + ("?" + urlencode(params) if params else ""))
            response = client.getresponse()
            result = response.status, json.loads(response.read())
            client.close()
            return result
        try:
            status, sessions = get("/api/analysis/sessions")
            self.assertEqual(status, 200)
            params = dict(id=sessions["roots"][0]["id"], snapshot_token=sessions["snapshot_token"])
            self.assertEqual(get("/api/analysis/usage", params)[1]["overall"]["total_tokens"], 100)
            event_status, events = get("/api/analysis/events", params)
            self.assertEqual(event_status, 200)
            self.assertEqual(events["total"], 2)
            detail_status, detail = get("/api/analysis/event", dict(params, event_id=events["events"][0]["id"]))
            self.assertEqual(detail_status, 200)
            self.assertIsInstance(detail["record"], dict)
            self.assertEqual(detail["event"]["source"]["line"], 1)
            self.assertEqual(get("/api/analysis/usage", dict(params, id="unknown"))[0], 404)
            self.assertEqual(get("/api/analysis/events", dict(params, limit="nonsense"))[0], 400)
            self.assertEqual(get("/api/analysis/events", dict(params, category="invalid"))[0], 400)
            self.write("main", [token(usage(200), model="model")])
            get("/api/analysis/sessions")
            stale, error = get("/api/analysis/usage", params)
            self.assertEqual((stale, error["code"]), (409, "snapshot_stale"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
