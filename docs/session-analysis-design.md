# Codex Session Analysis — Functional Specification and Build Plan

**Repository:** `adunato/codex-usage-dashboard`
**Target:** Replace/simplify the existing dashboard where useful; do not preserve unwanted UI or design decisions.
**Reference configuration:** `adunato/codex-config`, branch `change/flat-agent-routing` (for role names only).
**Status:** Design, not implemented.

## 1. What we are building

A local web application for investigating an existing Codex conversation. The user selects a conversation and sees **(1) where its tokens were spent** and **(2) the actual events recorded while it ran**.

The first working version must do both. It does **not** judge whether agents worked efficiently: we will decide how to do that only after seeing real session histories.

### Typical use

1. Start the application using the existing `codex-usage-dashboard` skill/launcher.
2. Find a conversation in the session list, e.g. “Fix authentication timeout”.
3. Click it. The **Usage** tab shows total tokens, totals for Main/Explorer/Worker/etc., and totals for Luna/Sol/any other recorded model.
4. Click **Inspect**. The page shows how many messages, tool calls, tool results, reasoning summaries, etc. were recorded, followed by a chronological list of those events.
5. Select “Explorer” to see what the explorer did; expand a tool call to see its arguments and returned output. If the log contains no readable thinking, the screen says so rather than implying it is available.

## 2. Exact screens and behaviours

### Screen A — Sessions

A searchable list/table with **Title | Project | Date | Total tokens**. Display one selectable entry per *root conversation*, rather than forcing the user to select an individual agent thread.

- Sorting: newest first by default; click Total tokens to sort by consumption.
- Clicking a conversation opens Screen B. Its associated subagents are included automatically.
- Archived conversations are selectable.
- If the selected conversation has missing/unreadable child logs, show a visible warning. Do not silently treat missing usage as zero.
- An imported remote-device *summary* can show token data, but **Inspect** must say “Full session history not available on this device” unless its original logs exist locally.

**Current-code starting point:** `CodexUsageAnalyzer.iter_session_files()` finds local logs; `build_snapshot()` produces the session list; the existing browser functions `agentTaskKey()` / `taskGroupsForRows()` already group threads into tasks. Reuse or replace the presentation, not the relationship data.

### Screen B — Usage

Header: **conversation title**, date, project, number of identified agents, and a clear **Complete / Incomplete** accounting status.

Immediately below it show:
```text
Session usage
Total 43,000   Input 36,000   Cached input 8,000   Output 7,000
```
Cached input is part of input, not additional consumption. Reasoning-output tokens are part of output.

**Table 1 — By agent role**, expandable:
```text
Role             Agents   Input   Cached input   Output   Total
Main                  1   14,000         4,000    3,000  17,000
Explorer              2   12,000         1,000    1,500  13,500  ▸
Worker Sol            1   10,000         3,000    2,500  12,500
TOTAL                 4   36,000         8,000    7,000  43,000
```
Clicking the Explorer row opens two underlying explorer-thread rows, each with its recorded model and its own usage. List only roles actually used. The roles supported by the current config include Main, Explorer, Designer, Worker, Worker Sol, Validator, Reviewer and Debugger; show Unknown for an unidentifiable historical role.

**Table 2 — By model**:
```text
Model               Input   Cached input   Output   Total
gpt-6.1-sol        24,000         7,000    5,500  29,500
gpt-6-luna         12,000         1,000    1,500  13,500
TOTAL              36,000         8,000    7,000  43,000
```
These are **illustrative numbers only**, not measured sessions. Their purpose is to specify layout and reconciliation: both tables add up to the same 43,000 tokens. If an agent used two models, distribute its recorded consumption between the two model rows.

No new pricing/cost system, charts, efficiency score, or benchmarks are in scope.

**Accounting displayed to the user:**
- “Complete” means all usage present in the inspected logs was counted and attributed; it is *not* a guarantee that Codex logged every internal request.
- “Incomplete” means there is missing source data, unresolved duplicate/inherited usage, or an unresolvable accounting inconsistency. Show the known amount and an explanation; never label a partial amount as a verified full total.
- If tokens are known but a role or model cannot be identified, include those amounts under Unknown. Their presence alone must not discard known usage.

### Screen C — Inspect

This is an **event browser**, not an AI interpretation of what happened.

It shows two sections:

**1. “What the log contains”**

Example:
```text
Messages           18    Readable
Tool calls         26    Readable
Tool results       25    Readable (1 unmatched)
Reasoning records   9    4 readable summaries, 5 encrypted/unavailable
Agent threads       4    1 Main, 2 Explorer, 1 Worker Sol
Other events       37    View types
```
Counts come from actual records, not estimates. This example is illustrative. Unknown event types remain listed, with their raw type names and counts.

**2. “Session timeline”**

Example of what a user sees:
```text
09:10:03  Main         Message          “Investigate the timeout...”
09:10:07  Main         Tool call        spawn_agent → explorer
09:10:10  Explorer #1  Tool call        read repository file
09:10:11  Explorer #1  Tool result      42 lines returned       ▸
09:10:16  Explorer #1  Reasoning        Summary available       ▸
09:10:30  Explorer #1  Message          “The timeout occurs in...” ▸
09:10:34  Worker Sol   Tool call        apply patch            ▸
09:10:38  Worker Sol   Tool result      Patch applied          ▸
09:10:45  Main         Message          “Implemented and tested...”
```
These are **examples of display**, not claims that every Codex recording contains these exact actions or event names.

**User interactions:**
- Filter timeline to **All agents** or one specific agent instance; filter event category (Messages, Tools, Reasoning, Other).
- Click a row to expand the actual available content: full message text, tool name/arguments, tool output/error, or readable reasoning summary.
- Display source reference (thread/session ID, original JSONL filename, and line/record position) with expanded content.
- Clearly show **Content unavailable**, **Encrypted reasoning**, **Unmatched tool result**, or **Unknown event type** where applicable.
- Display events by timestamp across threads; preserve per-file order when timestamps match. Do not imply causal relationships merely from timestamp order.
- Very large outputs should be initially collapsed and loaded when the row is opened; no truncation without a visible indication.

**Not promised:** access to hidden model thinking, reconstruction of the final Git diff from logs alone, or inference of actions Codex did not record.

## 3. How the existing code will change

Most functionality exists in one approximately 7,260-line file:
`skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py`.

The table below identifies the specific existing code and the required modification.

| Existing code | What it currently does | Required change |
| --- | --- | --- |
| `iter_session_files()`, `load_session_titles()` | Locates rollout files and titles | Keep; expose a root-conversation list with local child threads |
| `parse_file()` | Extracts metadata, selected messages, token events, tool counts | Keep usage extraction; ensure role/model identity and usage records needed for analysis are retained |
| `normalize_subagent_usage()` | Removes inherited parent usage from child histories | Reuse and test; unresolved baselines become visible warnings |
| `timeline_rows_with_deltas()` | Derives consumption from cumulative token counters | Reuse for model-specific token attribution; don't count cumulative snapshots as independent usage |
| `build_snapshot()` | Assembles summaries and details | Add one root-session analysis result: overall, by role, by instance, by model, warnings |
| `build_summary_static()` | Groups all-session totals; currently assigns each session to its latest model | **Do not use its `by_model` result for this screen**; split individual token contributions by their effective model |
| `read_rollout_jsonl()` / `fast_ignored_rollout_projection()` | Skips large reasoning and tool-output payloads for fast reporting | Keep efficient parsing for lists, but make source records accessible for Inspect; do not rely on these projections for expanded content |
| `make_handler()` | Serves `/api/sessions`, `/api/session`, etc. | Add one endpoint for selected-root usage and one for event timeline/details |
| `HTML` and embedded JavaScript | Present multilingual/project-heavy existing UI | Replace with the three screens described above; English only |
| `open_dashboard.py`, `bin/install.js` | Launch/install the current application | Keep working with the redesigned UI |
| `tests/test_codex_usage_dashboard.py` | Contains tests for accounting, cache, model changes, fork handling | Retain relevant tests and extend them for new outputs |

**Design decision:** One shared JSONL file reader and one underlying usage calculation. The application parses only the fields it needs for the session list; when an event is expanded it retrieves the original record. No two-parser architecture, new backend framework, or mandated wholesale code rewrite.

The developer may move code into smaller modules as necessary, but should not do a broad refactor merely to fit a speculative architecture.

## 4. Exact data behaviour

### Root conversation and agents

Use the recorded IDs and parent links: `session_id`, `root_session_id`, `parent_thread_id`, `forked_from_id`, and `agent_role` where present. Main is the root thread. Each child instance is listed once.

Historical sessions may have different agent roles than the current configuration. Do not infer roles from today's TOML files. Unknown stays Unknown.

### Tokens

Use the recorded `input_tokens`, `cached_input_tokens`, `output_tokens`, `reasoning_output_tokens`, and `total_tokens` where present.

- Report **Input** as all input including its cached portion.
- Report **Output** as all output including reasoning.
- Report **Total** as Input + Output when the source counters support that identity; inconsistent counters trigger a warning.
- Do not add Cached input or Reasoning a second time.
- Attribute consumption to its **agent instance** and the **effective model at the time**.
- If a session changes models, use per-event model labels/context rather than the last model name.

The existing code recognises `event_msg` + `token_count` and model changes from `turn_context` / `thread_settings_applied`. During implementation, inspect the user's actual recent logs for any other token record format. If newer per-response records exist, add support and deduplicate against cumulative totals rather than summing both representations.

Where the same parent usage is carried into child histories, exclude the inherited portion, using the existing tested fork logic. If missing files make this impossible, surface that failure.

### Events

For each selected conversation, read the available records from its Main and child JSONL files. The event data needed by the UI is:

```json
{
  "event_id": "opaque identifier",
  "timestamp": "recorded ISO timestamp",
  "thread_id": "source thread ID",
  "agent": "Explorer #1",
  "category": "tool_call",
  "raw_type": "response_item/function_call",
  "preview": "read repository file",
  "source": {"file": "rollout-...jsonl", "line": 42},
  "content_status": "readable"
}
```

This is the app's **proposed output structure**, not a claim about Codex's native JSONL schema. Expanding `event_id` retrieves the recorded payload from the original file.

Recognise recorded message, reasoning, tool-call, tool-result, context and lifecycle types. List unknown variants under their raw type. Associate call/result pairs using recorded call IDs, never by adjacency alone. Report unmatched entries. Do not display encrypted reasoning as readable text.

**Security:** Read local session files only. Display user-supplied/log text as escaped plain text, not HTML. Never allow an API request to name an arbitrary filesystem path. Bind the local server to `127.0.0.1`. Do not send session data to an AI model or remote service automatically.

## 5. Build and verification — concrete deliverables

### Delivery 1: Working application (the first actual implementation)

Modify the existing app, not just a design or log inventory.

**Developer tasks:**
1. Use the current `build_snapshot()` / session grouping data to present one selectable row per root conversation.
2. Build a backend aggregation function returning overall, by-role, by-agent and by-model token totals for the selected root conversation.
3. Connect those totals to the Usage screen, including expansion of role rows.
4. Read original JSONL event records for that conversation and return an event inventory and a timestamp-ordered list with expandable details.
5. Connect those events to the Inspect screen.
6. Run the revised application against local session logs while developing it; use actual encountered records to implement and correct parsing.

**Demonstration required to accept Delivery 1:**
- Open the existing launcher and select one multi-agent conversation.
- Show numerical totals for Main and participating subagents, grouped by role.
- Show model totals for the same conversation.
- Click Inspect, filter to one agent, expand a message and an actual tool call/result, and show the original recorded content or an explicit unavailable status.
- Explain any fields that the selected logs do not actually contain.

This is a complete usable vertical slice. Unsupported log variants may still be clearly flagged for Delivery 2; the UI must not invent data for them.

### Delivery 2: Make it reliable across recorded sessions

Run the app against several representative sessions (single-agent, multi-agent, archived/resumed, model-switching if available). Extend the parser for variants actually encountered.

**Tests must verify:**
- For the numerical example in section 2, Main 17,000 + Explorer 13,500 + Worker Sol 12,500 = **43,000**; model rows 29,500 + 13,500 = **43,000**.
- If two Explorers share a role, their totals aggregate under Explorer but remain independently expandable.
- If one agent switches models, its tokens are split across model rows.
- Inherited fork counters, repeated records and cumulative snapshots are not double-counted.
- Cached input and reasoning output are not added twice.
- Missing metadata is visible as Unknown or Incomplete as appropriate.
- Timeline results preserve source references; recorded tool calls and results pair by ID, even when interleaved.
- Unknown records, encrypted reasoning and missing results are visible rather than fabricated.

Use synthetic or sanitised fixtures in Git, not real private transcripts.

### Delivery 3: Remove unnecessary complexity and finish

Remove Chinese-language UI and redundant interface code; complete only refactors needed by the changed features. Keep existing Python launcher and installer functioning on Windows, and run the current regression tests.

Confirm source session files were not modified. Update the README to explain the three screens and documented limitations.

**Final acceptance:** A local application where the user can select a conversation, understand exactly which agents and models spent its tokens, and browse the events Codex recorded. No AI scoring or behavioural recommendations yet.

## 6. After this version

Use the working Inspect screen to examine a few real sessions and agree what a separate qualitative evaluator could legitimately judge. That evaluator is **not** part of this design.
