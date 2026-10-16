"""Stop only Windows Python processes running the bundled dashboard script."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass


INVENTORY_SCRIPT = (
    "Get-CimInstance Win32_Process | "
    "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
)
SCRIPT_NAME = "codex_usage_dashboard.py"


@dataclass(frozen=True)
class Process:
    pid: int
    name: str
    command_line: str


def parse_inventory(payload: str) -> list[Process]:
    if not payload.strip():
        return []
    rows = json.loads(payload)
    if isinstance(rows, dict):
        rows = [rows]
    return [
        Process(int(row["ProcessId"]), str(row.get("Name") or ""), str(row.get("CommandLine") or ""))
        for row in rows
        if row.get("ProcessId") is not None
    ]


def is_dashboard_process(process: Process) -> bool:
    if process.name.casefold() not in {"python.exe", "pythonw.exe"}:
        return False
    tokens = re.findall(r'"([^\"]*)"|(?=\S)([^\s]+)', process.command_line)
    args = [quoted or bare for quoted, bare in tokens]
    if len(args) < 2:
        return False
    index = 1
    no_argument_flags = {"-b", "-e", "-i", "-o", "-oo", "-q", "-s", "-u", "-v", "-x"}
    argument_flags = {"-w", "-x", "--check-hash-based-pycs"}
    while index < len(args):
        arg = args[index]
        flag = arg.casefold()
        if flag == "--":
            index += 1
            break
        if flag in {"-c", "-m"} or flag.startswith(("-c", "-m")):
            return False
        if flag in no_argument_flags or flag.startswith(("-w", "-x")) and flag != "-x":
            index += 1
            continue
        if flag in argument_flags:
            index += 2
            continue
        if arg.startswith("-"):
            return False
        break
    if index >= len(args):
        return False
    script = args[index].replace("/", "\\").rsplit("\\", 1)[-1]
    return script.casefold() == SCRIPT_NAME


def inventory() -> list[Process]:
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", INVENTORY_SCRIPT],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Windows could not list running programs.")
    return parse_inventory(result.stdout)


def stop_process(pid: int) -> None:
    result = subprocess.run(
        ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f"Windows could not stop process {pid}.")


def main() -> int:
    if os.name != "nt":
        print("This stop button works on Windows.", file=sys.stderr)
        return 1
    try:
        targets = [process for process in inventory() if is_dashboard_process(process)]
        if not targets:
            print("The dashboard is already stopped.")
            return 0
        for process in targets:
            current = next((p for p in inventory() if p.pid == process.pid), None)
            if current is None:
                continue
            if current.name.casefold() != process.name.casefold() or current.command_line != process.command_line:
                continue
            try:
                stop_process(process.pid)
            except RuntimeError:
                # A process that exited between inventory and taskkill is already stopped.
                current = next((p for p in inventory() if p.pid == process.pid), None)
                if current is not None and current.name.casefold() == process.name.casefold() and current.command_line == process.command_line:
                    raise
        time.sleep(0.25)
        remaining = [p for p in inventory() if is_dashboard_process(p)]
        if remaining:
            raise RuntimeError("Windows still reports a dashboard process running.")
        print("The dashboard has been stopped.")
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"Could not stop the dashboard: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
