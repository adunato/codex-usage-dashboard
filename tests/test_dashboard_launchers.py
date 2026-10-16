import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "codex-usage-dashboard"
    / "scripts"
    / "stop_dashboard.py"
)
SPEC = importlib.util.spec_from_file_location("stop_dashboard_tests", SCRIPT)
stopper = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stopper
SPEC.loader.exec_module(stopper)


class DashboardLauncherTests(unittest.TestCase):
    def process(self, pid=12, name="python.exe", command="python.exe \"C:\\Users\\A B\\codex_usage_dashboard.py\" --port 8765"):
        return stopper.Process(pid, name, command)

    def test_matches_quoted_script_path_under_spaces(self):
        self.assertTrue(stopper.is_dashboard_process(self.process()))
        self.assertTrue(stopper.is_dashboard_process(self.process(name="pythonw.exe")))
        self.assertTrue(stopper.is_dashboard_process(self.process(command='python.exe -u "C:\\Users\\A B\\codex_usage_dashboard.py" --port 8765')))
        self.assertTrue(stopper.is_dashboard_process(self.process(command='python.exe -- "C:\\Users\\A B\\codex_usage_dashboard.py"')))

    def test_rejects_incidental_text_and_python_c_commands(self):
        self.assertFalse(stopper.is_dashboard_process(self.process(command='python.exe -c "run codex_usage_dashboard.py"')))
        self.assertFalse(stopper.is_dashboard_process(self.process(command='python.exe other.py codex_usage_dashboard.py')))
        self.assertFalse(stopper.is_dashboard_process(self.process(command='python.exe -c "pass" codex_usage_dashboard.py')))
        self.assertFalse(stopper.is_dashboard_process(self.process(command='python.exe -m codex_usage_dashboard.py')))
        self.assertFalse(stopper.is_dashboard_process(self.process(command="python.exe other.py codex_usage_dashboard.py.log")))
        self.assertFalse(stopper.is_dashboard_process(self.process(name="my-python.exe")))

    def test_inventory_json_accepts_single_item_and_empty(self):
        self.assertEqual(stopper.parse_inventory(""), [])
        item = stopper.parse_inventory(json.dumps({"ProcessId": 12, "Name": "python.exe", "CommandLine": "python.exe x.py"}))
        self.assertEqual(item, [stopper.Process(12, "python.exe", "python.exe x.py")])

    @mock.patch.object(stopper, "os")
    @mock.patch.object(stopper, "inventory")
    @mock.patch.object(stopper, "stop_process")
    def test_stops_only_matches_and_verifies(self, kill, get_inventory, os_mock):
        os_mock.name = "nt"
        match = self.process()
        unrelated = self.process(13, command="python.exe unrelated.py")
        get_inventory.side_effect = [[match, unrelated], [match, unrelated], [unrelated]]
        with mock.patch.object(stopper.time, "sleep"):
            self.assertEqual(stopper.main(), 0)
        kill.assert_called_once_with(12)
        self.assertEqual(get_inventory.call_count, 3)

    @mock.patch.object(stopper, "os")
    @mock.patch.object(stopper, "inventory", return_value=[])
    def test_already_stopped_is_success(self, get_inventory, os_mock):
        os_mock.name = "nt"
        self.assertEqual(stopper.main(), 0)
        get_inventory.assert_called_once()

    @mock.patch.object(stopper, "os")
    @mock.patch.object(stopper, "inventory", side_effect=RuntimeError("inventory failed"))
    def test_inventory_failure_is_reported(self, get_inventory, os_mock):
        os_mock.name = "nt"
        self.assertEqual(stopper.main(), 1)


if __name__ == "__main__":
    unittest.main()
