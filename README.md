# Codex Usage Dashboard

Codex-only skill for a local OpenAI Codex usage dashboard.

A local browser for Codex conversations: find a root conversation, see where its recorded tokens were spent, and inspect the original events from Main and its agent threads. Runs with Python 3 and no API key.

> Currently only supports OpenAI Codex. It is not a Claude Code, Cursor, Continue, or generic OpenAI API dashboard.

## Three screens

- **Sessions** lists one row per root conversation, including archived conversations and associated agents. Search by title or project; sort by newest or total tokens.
- **Usage** shows overall Input, Cached input, Output and Total, expandable totals by recorded agent role, individual threads, and totals by the model used for each token contribution. Cached input is already included in input; reasoning output is already included in output.
- **Inspect** inventories the records actually present and displays a chronological timeline. Filter by agent or event category, then expand messages, tool arguments/results, or readable reasoning summaries. Expanded events show their original filename, thread ID and line number. Large content loads on expansion and is explicitly marked if truncated.

**Complete** means all usage available in the inspected logs was counted and attributed. It does not guarantee that Codex recorded every internal request. **Incomplete** shows known totals with explanations for missing logs, unresolved inherited counters or inconsistent accounting. Unidentified historical roles and models appear as **Unknown**.

## Install With The Skills CLI

Recommended global Codex install:

```bash
npx skills add luyh7/codex-usage-dashboard -g -a codex -y
```

Then restart Codex or open a new Codex conversation. Type `/usage`, then select the **Codex Usage Dashboard** skill.

The skill opens the local dashboard in your browser.

## Install With npx

GitHub installer:

```bash
npx github:luyh7/codex-usage-dashboard
```

Install and create a desktop shortcut:

```bash
npx github:luyh7/codex-usage-dashboard -- --shortcut
```

Install and open immediately:

```bash
npx github:luyh7/codex-usage-dashboard -- --open
```

## What Gets Installed

The standard skills CLI installs:

```text
~/.codex/skills/codex-usage-dashboard
```

The bundled npm installer copies the same skill to that location.

Repository layout:

```text
skills/
  codex-usage-dashboard/
    SKILL.md
    agents/openai.yaml
    scripts/open_dashboard.py
    scripts/export_snapshot.py
    scripts/codex_usage_dashboard.py
    scripts/session_analysis_ui.py
    scripts/session_inspect.py
    scripts/install_desktop_shortcut.py
    assets/codex_usage_dashboard.ico
```

## Manual Launch

After installation:

```bash
python ~/.codex/skills/codex-usage-dashboard/scripts/open_dashboard.py
```

On macOS you may need:

```bash
python3 ~/.codex/skills/codex-usage-dashboard/scripts/open_dashboard.py
```

The dashboard opens at:

```text
http://127.0.0.1:8765/
```

## Manual Multi-Device Usage

Open the dashboard on the receiving device:

```bash
python ~/.codex/skills/codex-usage-dashboard/scripts/open_dashboard.py
```

Export a snapshot on another device with:

```bash
python ~/.codex/skills/codex-usage-dashboard/scripts/export_snapshot.py
```

The existing snapshot export/import APIs remain available for manual usage summaries. Imported summaries can contribute token data, but they do not contain original transcripts. Inspect says **Full session history not available on this device** when the original local logs are absent. The session browser does not automatically synchronize devices.

To force specific log roots, pass `--codex-home` one or more times:

```bash
python ~/.codex/skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py \
  --codex-home ~/.codex \
  --codex-home /mnt/c/Users/<you>/.codex
```

## Data Source

The dashboard reads local Codex logs from each configured Codex home:

```text
~/.codex/sessions
~/.codex/archived_sessions
```

Under WSL, the default scan also includes:

```text
/mnt/c/Users/<you>/.codex/sessions
/mnt/c/Users/<you>/.codex/archived_sessions
```

It parses cumulative Codex `token_count` events and newer `token_usage_record` records through the same accounting pipeline. Overlapping counters are deduplicated, inherited parent usage is removed where the logs permit it, and model changes are attributed at the time of consumption. Inspect uses the shared JSONL reader and retrieves original records on demand.

## Privacy

This is a local dashboard. It does not upload your Codex logs. It starts a local server bound to `127.0.0.1`.

## Limitations

- Codex Desktop/CLI JSONL formats vary. Unsupported records remain visible by raw type; missing or inconsistent accounting is flagged.
- Encrypted reasoning remains unavailable. Readable summaries are shown only when recorded; this app does not recover hidden thinking or infer unrecorded actions.
- Tool calls/results pair using recorded call IDs within each thread. Missing or ambiguous matches are shown explicitly.
- Timestamp ordering across threads is chronological, without a claim of causality. Equal timestamps retain file order.
- Source logs can change while a conversation is active. Refresh the session list if an old snapshot becomes unavailable.
- Large expanded content is bounded and visibly marked when truncated. Original session files remain unchanged.
- No AI scoring, efficiency recommendations, new pricing system, or automatic remote uploads are included.

## Development checks

```bash
python -m unittest discover -s tests
python -m compileall -q scripts tests skills
npm run validate
```
