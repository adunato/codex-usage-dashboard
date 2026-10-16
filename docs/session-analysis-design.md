# Codex Session Analysis — Design and Implementation Plan

**Status:** Proposed design for implementation  
**Repository:** `adunato/codex-usage-dashboard`  
**Reference agent configuration:** `adunato/codex-config`, branch `change/flat-agent-routing`  
**Purpose:** Replace and simplify the existing dashboard as needed; its current design is not a constraint.

## 1. Goal

Build a local application that answers two questions about a selected Codex session:

1. **Where did the tokens go?** Show the session total and break it down by agent role, individual agent, and model.
2. **What happened in the session?** Show the execution history that Codex actually recorded, so we can later decide what qualitative analysis is possible.

The first version must provide **both** capabilities in a working browser application. It is **not** an AI efficiency auditor. No recommendations about `AGENTS.md` or agent behaviour are generated yet.

## 2. User-facing application

Keep a simple, English-only local web application, opened using the existing Codex skill or launcher.

### A. Session selection

Display a searchable list of sessions with title, project, date, and token total. Include archived sessions. Selecting a **root session** includes Main and all its associated subagents. Show a warning when a parent or linked thread is missing.

The selected session stays selected when switching between **Usage** and **Inspect**.

### B. Usage

Show three summaries for the selected root session:

**Overall:** input tokens, cached input tokens, output tokens, and total tokens.

**By agent:** one row per *role* (Main, Explorer, Designer, Worker, Worker Sol, Reviewer, Debugger, Validator, or Unknown), summing all agent instances of that role. Expanding a row reveals each individual agent/thread, its model(s), and token counts.

**By model:** one row per actual model identifier, summing its usage across Main and all subagents. If one agent switched models, split its consumption across those models.

Use the same four numerical columns in both tables: **Input | Cached input | Output | Total**. Show a final total row.

**Important token definitions:** cached input is part of input, not an additional amount; reasoning-output tokens are part of output, not additional output. Therefore total is input + output. Reasoning-output tokens can appear in a detail view if recorded.

For fully attributable sessions, the agent rows and model rows must each sum to the session total. Put unidentified roles or models in an **Unknown** row. If some token usage cannot be reliably counted at all, show a *known subtotal* and a clear **Incomplete** warning; never silently label it a complete total.

Do not introduce cost estimates, scoring, charts, or extra metrics for this version. Existing dashboard features unrelated to these needs need not be retained.

### C. Inspect

Show two sections for the same selected session:

**Recorded data:** counts of the event categories found (messages, reasoning records, tool calls, tool results, model/context changes, lifecycle events, and unrecognised events). Explicitly show which kinds of content are available, missing, unreadable, or encrypted.

**Timeline:** recorded events from Main and subagents in timestamp order, with filters for agent and event category. Each row shows time, agent, event type, and a brief preview. Expanding it displays the available recorded content and source-file/record reference.

The inspector should expose, where present:
- User and assistant messages, without confusing injected context with user prompts.
- Readable reasoning summaries. Mark encrypted or missing reasoning as unavailable; never claim to recover hidden reasoning.
- Tool names, recorded arguments, outputs/errors, and call identifiers.
- Agent/thread identities, parent-child relationships, and recorded delegation activity.
- Recorded patch/edit commands and their results. These are evidence of actions, **not** proof of the final Git repository state.
- Other recorded events, including unknown event types, so their existence is visible.

Match a tool result to its invocation by recorded call ID when possible, not simply by neighbouring timestamps. Mark unmatched calls and outputs. For concurrent agents, chronological display does not imply causal order.

Large messages and tool outputs may be collapsed and loaded only when opened. Render all recorded text safely as text, not executable HTML.

## 3. Data handling and accounting

The source is the user's existing local Codex session history: `.codex/sessions`, `.codex/archived_sessions`, and relevant session index information. Use the dashboard's existing source discovery, including its Windows/WSL support.

**Use one shared JSONL reading mechanism.** Different parts of the application consume the fields they need. Session lists should not unnecessarily retain large tool outputs; opening a session or event makes its recorded content available. There is no requirement for two separate parsers or formal reading modes.

### Session identity

Use the recorded source, thread/session IDs and parent relationships to associate Main with its subagents. A thread is counted once within a selected root session. Historical role assignments come from the session records when available, **not** from assuming the current agent configuration was used historically.

### Token usage

Build on the existing and tested code for token normalisation, usage deltas, fork-aware inherited-history removal, model changes, and cached parsing. Relevant starting points in the current Python file are `CodexUsageAnalyzer.parse_file`, `normalize_subagent_usage`, `timeline_rows_with_deltas`, `build_snapshot`, and `get_detail`.

Rules:
1. Interpret cumulative token counters as differences between snapshots, not by summing snapshots.
2. Do not double-count a child's inherited parent token history, or repeated records from resumed/forked sessions.
3. Associate each contribution with the effective recorded model at that point, including mid-session model changes.
4. Codex log formats can evolve. Inspect the actual records encountered during implementation. If both per-response and cumulative usage records are present, reconcile overlapping usage rather than counting both. Do not assume unverified event fields exist.
5. Preserve uncertainty: unrecognised usage, missing parent baselines, missing model identity, and contradictory counters are reported rather than guessed.

Where a model is known but the agent role is not, its usage still contributes to the model table and the Unknown agent row. The inverse also applies.

### Recorded event inspection

The current usage parser intentionally skips some large reasoning and tool-output payloads for performance. Those events must be accessible in the inspector. Reuse the JSONL parsing foundation and read the original records as needed, instead of trying to reconstruct full content from the dashboard's short message previews.

An inspected event retains a stable reference to its source file and position, so the UI can open the corresponding original record. If the underlying file changes, invalidate that reference and refresh the session rather than returning a different event.

The inspector is descriptive: it must clearly distinguish *recorded facts* from unavailable information. No AI model is invoked by these features.

## 4. Implementation approach

Use the existing `adunato/codex-usage-dashboard` repository as the starting point. Reuse the parts that work, but simplify or replace the rest freely.

The existing application is mostly in `skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py`, with tests in `tests/test_codex_usage_dashboard.py`. Keep the Python local server and the existing skill-launch mechanism. A new frontend framework and a new repository are not necessary.

Keep the implementation straightforward:
- Reuse/refactor existing session discovery and token-accounting functions.
- Add grouping by role and by model, with explicit accounting warnings.
- Add event extraction and a timeline view that reads full original records when requested.
- Replace the present UI with a focused English-only **Sessions / Usage / Inspect** experience. Remove Chinese localisation and unwanted presentation complexity.
- Extract code from the monolithic script into small modules **only where that helps maintainability while implementing these features**; there is no mandated full rewrite or speculative architecture.

The browser interface and any command-line tests should use the same underlying calculations so totals cannot disagree.

Keep the service on `127.0.0.1` by default. The browser must select from discovered sessions/events; it must not be allowed to request arbitrary filesystem paths. Do not automatically upload session contents or publish private logs.

## 5. Implementation sequence

This is a delivery plan, **not** a separate research project.

### Milestone 1 — Working first version

Implement, in the existing project:
1. Session selection with Main and associated subagents.
2. Working session, role, individual-agent, and model token totals, using existing accounting logic.
3. A basic inspector that reads actual session records and displays an event inventory and chronological, expandable timeline.
4. A simplified English-only interface connecting those features.

**Deliverable:** A usable application that can select a real session, show both token breakdowns, and inspect its recorded events.

**During this implementation**, examine representative local JSONL records to identify supported fields and variations. This is part of making the first version work, **not** a preceding deliverable or a standalone format-discovery phase. Unknown formats must be marked unsupported until handled.

### Milestone 2 — Accuracy and completeness

Test against representative real sessions: an ordinary session, a multi-agent session, an archived/resumed session, and a model-switching session if available. Resolve accounting discrepancies and fill in observed event types.

Add or adapt automated tests for inherited token history, duplicate records, mixed usage formats, model switches, unavailable attribution, tool call/result matching, encrypted reasoning, unknown events, and malformed/large records.

**Deliverable:** Consistent totals for supported formats, with explicit warnings for remaining gaps; a useful event timeline for the inspected samples.

### Milestone 3 — Cleanup and release

Remove unnecessary UI/localisation code, tidy modules affected by the work, preserve the installer and launcher, update documentation, and run the full regression suite and Windows launch check.

**Deliverable:** A maintainable, English-only application with the agreed features, not a partially rewritten dashboard with parallel interfaces.

## 6. Acceptance criteria

The work is complete when all of the following hold:

1. A user can open the application and select a root session that includes its subagents.
2. The Usage view shows the overall total, totals **by agent role**, expandable **individual agents**, and totals **by model**.
3. The same underlying consumption is not counted twice, cached/reasoning tokens are treated as subsets, and totals reconcile when attribution is complete.
4. Missing or uncertain consumption/attribution is explicitly marked instead of hidden.
5. The Inspect view shows the observed event categories and an expandable chronology containing recorded messages, available reasoning summaries, tool activity, and other events.
6. The inspector does not invent hidden reasoning, unrecorded file changes, or missing agent actions.
7. The original Codex logs and configuration are not modified. Raw session contents stay local unless the user explicitly chooses to share them.
8. The application is straightforward, English-only, and starts using the existing skill-launch workflow.
9. Existing relevant tests remain passing, with new regression tests for the added functionality.

## 7. Subsequent decision (not part of this implementation)

Once the inspector works, examine a few representative session histories and discuss which parts of agent behaviour can be reliably evaluated. **Only then** design a qualitative efficiency-analysis agent. Do not predefine an auditor or quality scores in this project phase.
