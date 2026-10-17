# Low-Level Design: Session analysis

## 1. Change Overview

Extend the existing parser and published snapshots with canonical, root-level accounting. Add a callback-based Inspect module and a dependency-free browser HTML module; keep the existing server as the integration point. The approved functional requirements remain in [session-analysis-design.md](session-analysis-design.md); implementation sequencing is in [session-analysis-implementation-plan.md](session-analysis-implementation-plan.md).

Evidence is the reusable packet `session-analysis-2026-10-16-v1` at `C:/Users/danie/projects/session-analysis-evidence.md`, revision `41d86e7`, plus focused reads of its referenced reader/parser/snapshot/handler sections. Facts: existing fork/model/snapshot support is reusable; current fast projections lose Inspect payloads; modern logs contain overlapping usage families. Design decisions below resolve interfaces without a new framework or independent usage parser. Modern-family equality remains an evidence gap and must not be assumed.

## 2. File Changes

### `skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py`

**Action: Modify. Core worker owns this file.**

#### Shared reader and parser

Extend `read_rollout_jsonl(path,start_offset=0,stats=None,end_offset=None,*,full_payload=False,with_source=False)`. Defaults preserve existing projection and incremental cache behavior. Full mode bypasses `fast_ignored_rollout_projection()`. Source mode attaches reserved `_source={line,offset,length}` metadata to yielded records; line numbers are one-based physical JSONL lines including blank/malformed lines. Offsets/lengths are bytes. Inventory scans begin at zero; one-record expansion already knows its saved original line number.

Preserve BOM, UTF-8 replacement and incomplete trailing-record handling. Return a source-positioned parse-error marker for malformed complete records. Keep source metadata separate from an event's original JSON object when returning detail.

Extend `parse_file()` rather than adding a second usage parser:

- Retain provenance for canonical token observations, modern response IDs and accounting warnings in cache-compatible parser output.
- Normalize `event_msg/token_count.info.total_token_usage` and `token_usage_record.thread_token_usage` as overlapping cumulative observations. When token_count authority exists, retain it for covered segments and use modern observations as corroboration; use modern cumulative counters for modern-only coverage. Do not interleave conflicting cumulative observations and clamp negative deltas, which would double-count a later rise. Unproven overlap remains incomplete with the known canonical amount. Apply explicit token-event model first, then the effective model from prior metadata/context/settings. Never substitute the thread's final model for an earlier unknown model.
- Deduplicate repeated response IDs and equal cumulative observations. Never sum cumulative totals or independently add the two families. Per-response `usage` is corroborating evidence, and fallback only when cumulative authority is absent and unique response IDs give resolved coverage. `turn_token_usage` is cumulative within a turn and must never be summed as per-request usage.
- If cumulative shapes/coverage disagree, retain the known canonical amount and warn `usage_overlap_unresolved`; do not label it complete. Counter decreases, conflicting duplicate IDs, unsupported usage shapes and inconsistent total/input/output relationships also warn. Preserve actual known counters rather than fabricating a balanced total.
- Capture recorded spawned-child identifiers when recognized in lifecycle metadata. Only use a recognized schema; do not interpret free text as an authoritative child relationship.

Reuse `normalize_subagent_usage()` before root aggregates. Preserve its tested baseline subtraction and propagate unresolved/missing-parent flags as accounting warnings. Use `timeline_rows_with_deltas()` after normalization for per-effective-model allocation. If modern provenance must be rebased, rebase it alongside the same canonical timeline; never normalize a second independent total. Increment persistent parse-cache version if stored fields change.

#### Root identities and aggregation

Extend `build_snapshot()` with internal analysis root, agent and source indexes, using the exact published snapshot lifetime/token. Suggested helpers are `build_root_analysis(rows)`, `get_analysis_sessions()`, `get_analysis_usage(root_id,snapshot_token)`, and a private snapshot/root lookup shared by Inspect routes. Helper names may differ; exported HTTP and Inspect module contracts are fixed.

Resolve ancestry from recorded parent links in the same environment, falling back to explicit root identity when supplied. Group connected descendants transitively. A real root's display role is Main; a child role is recorded metadata or Unknown. An orphan child remains a child with recorded role/Unknown and a missing-ancestor warning. Do not turn an orphan into Main. Detect cycles and retain a deterministic incomplete orphan group rather than recurse indefinitely. Never infer historical role from current config.

Identities are stable SHA-256 prefixes (24 hex characters) of environment ID, a NUL separator byte, and resolved root session ID for roots; substitute session ID for agents. One recorded thread is one instance even across resumed files. Distinct thread IDs with the same role remain distinct. Duplicate files for one thread must not double usage; deduplicate canonical observations by their recorded IDs/cumulative provenance and flag unresolved overlap. Keep differing environments/devices isolated.

Build overall, by-role, by-agent and by-model sums from the same canonical agent/model deltas. Cached input is a subset of input; reasoning output a subset of output. Unknown model/role buckets retain known counters. A missing role/model alone does not lose tokens; an unresolved quantity or inconsistent arithmetic makes accounting incomplete. Complete means all usage found in inspected sources was counted and attributed to a known or explicit Unknown bucket, without claiming that Codex recorded every internal request.

Capture unreadable/disappeared discovered sources before the existing silent parse-skip points. Propagate warnings into any identifiable root; where no root can be identified, expose a list-level warning. Compare known recorded child references with available local/remote thread identities. Missing known children, unresolved inheritance/dedup, malformed usage and inconsistent totals produce Incomplete with the known amount. Remote summaries without historical model splits retain Unknown model and clear coverage warnings; they must not claim full local history.

Private local thread descriptors passed to Inspect are:
```text
{agent_id,session_id,role,label,path:Path,source_root:Path,size:int,mtime_ns:int}
```
Derive them from discovered local source files and pin them to the published snapshot. A source outside its resolved configured source root is unavailable. Public responses contain only source filename/line, never an API-controlled filesystem path. If inode/device data is available, retain it privately to strengthen replacement detection.

#### HTTP and module integration

Load sibling modules in both direct execution and `importlib.util.spec_from_file_location()` tests. Use an explicit sibling loader or narrowly add the scripts directory to module search; do not depend on the caller's current working directory. Instantiate `SessionInspector(read_rollout_jsonl)` once per analyzer and limit cached inventories to retained published snapshots.

Serve `session_analysis_ui.HTML` at `/`. Existing health, launcher and legacy JSON endpoints keep their behavior. The old embedded UI may remain temporarily for legacy source assertions, but only one HTML implementation is served and no unrelated backend refactor is required.

New GET routes:
| Route | Parameters | Result |
| --- | --- | --- |
| `/api/analysis/sessions` | none; always all-history scan | `{snapshot_token,generated_at,roots:[RootSummary],warnings?:[Warning]}` |
| `/api/analysis/usage` | `id,snapshot_token` | `Usage` |
| `/api/analysis/events` | `id,snapshot_token,agent_id?,category?,offset=0,limit=100` | `EventPage` |
| `/api/analysis/event` | `id,snapshot_token,event_id` | `EventDetail` |

Use exact snapshot lookup; a detail request must never silently switch to a newer scan. Unknown root/event returns 404, stale snapshot or changed source 409 with `{code:"snapshot_stale",error:...}`, malformed IDs/filter/page 400. Page offset is nonnegative, limit 1–500. IDs only resolve in the supplied root/snapshot. API accepts no filename, path, source root, byte range or arbitrary URL.

The new analysis/detail routes are local reads only. Enforce loopback binding for serving source-backed analysis; reject nonloopback host configuration with an actionable message rather than exposing transcript APIs. Preserve no-store/nosniff headers. No background remote transmission or model calls.

#### Public accounting JSON

```text
UsageCounters = {input_tokens,cached_input_tokens,output_tokens,
                 reasoning_output_tokens,total_tokens} // nonnegative integers
Warning = {code:string,message:string,agent_id?:string}
RootSummary = {id,title,project,date,agent_count,usage:UsageCounters,
               completeness:"complete"|"incomplete",warnings:[Warning],
               inspect_available:boolean}
AgentUsage = {id,session_id,parent_id:string|null,role,label,
              models:[{model,usage:UsageCounters}],usage:UsageCounters}
Usage = {root:RootSummary,overall:UsageCounters,
         by_role:[{role,usage:UsageCounters,agents:[AgentUsage]}],
         by_agent:[AgentUsage],by_model:[{model,usage:UsageCounters}],
         warnings:[Warning]}
```

`date` is an ISO timestamp suitable for sorting/display; missing values use the empty string. `parent_id` is an opaque agent ID. All sums reconcile across each of the five counter fields, even when completeness is incomplete. UI does not recalculate accounting.

### `skills/codex-usage-dashboard/scripts/session_inspect.py`

**Action: Create. Inspect worker owns this file.**

Exports:
```text
class InspectSourceChanged(Exception)
class InspectBadRequest(ValueError)
class SessionInspector:
    __init__(reader)
    events(root_id,snapshot_token,threads,*,agent_id="",category="",
           offset=0,limit=100) -> EventPage
    event(root_id,snapshot_token,threads,event_id) -> EventDetail
```

Consume the shared reader callback; do not import the monolith or duplicate its usage logic. Scan only selected-root files with `full_payload=True,with_source=True,end_offset=descriptor.size`. Retain compact metadata, record locations and pairing indexes; discard full payloads after inventory construction. Cache by root/snapshot and bound/evict cache entries.

Check resolved source containment and snapshot signature before inventory/detail; changed size/mtime or replaced/deleted file raises `InspectSourceChanged`. A growing live file also requires refreshed selection rather than mixing snapshots. Read original bytes again on detail via the same reader and stored offset/end offset. Do not trust file contents to specify another source path.

Categories are exactly `message,reasoning,tool_call,tool_result,context,lifecycle,other`. Raw type is `outer_type/inner_type` where an inner discriminator exists. Inventory counts actual records, including duplicate display representations if the log contains both; do not infer that two similar messages are one event. Unknown raw types remain visible under Other with raw names and counts. Recognize function/custom calls and outputs, message variants, reasoning, context/settings/compaction and known lifecycle records. Parse errors are explicit unavailable/unknown records with source positions.

Classify reasoning readability from actual readable summary/text fields. Encrypted-only content is encrypted/unavailable; never expose `encrypted_content` in DTOs or expansion JSON. Where readable summary coexists with encryption, show that summary and explicit encryption status. Do not invent absent thinking.

Pair only recorded call IDs, scoped by agent/thread and call family where necessary. Interleaving is supported. A repeated ambiguous ID must not silently bind the wrong pair; flag unmatched/ambiguous. Preserve related event IDs for navigation and show actual recorded arguments/results/errors. Missing calls/results remain visible and counted.

Sort by parsed timestamp in UTC; deterministic source rank and physical line break ties while preserving each file's order. Undated/invalid timestamps have explicit status and a deterministic fallback position; do not invent timestamps or causality.

```text
Event = {id,timestamp:string|null,session_id,agent_id,category,raw_type,preview,
         source:{filename,line},statuses:[string],call_id?:string,
         related_event_ids:[string]}
EventPage = {events:[Event],total,offset,limit,inventory,warnings:[Warning]}
inventory = {by_category:{category:count},by_raw_type:{raw_type:count},threads,
             count_readable_reasoning,count_encrypted_reasoning,
             count_unavailable_reasoning,unmatched_calls,unmatched_results}
EventDetail = {event:Event,record:object|null,text:string,
               truncated:boolean,statuses:[string]}
```

Event IDs are opaque and deterministic within a root/snapshot/source position. Status examples: readable, encrypted, unavailable, unmatched, ambiguous, unknown, invalid_timestamp. `threads` in inventory is a count. Inventory is for the whole root; `total` reflects the selected filters before pagination. Unknown filter values raise `InspectBadRequest`. An empty local source list returns empty events/inventory and a clear `history_unavailable` warning.

Bound previews (approximately 240 characters) and expansion text (200,000 characters). Bound serialized record content as well: for oversized records return `record:null` plus the bounded original-record representation in `text`, with `truncated:true`. Never return a full oversized raw record alongside truncated text. Truncation is explicit and output is escaped in the UI. Expanded ordinary records retain all original nonencrypted fields. Lazy expansion must fetch the original payload, not the projected list record.

### `skills/codex-usage-dashboard/scripts/session_analysis_ui.py`

**Action: Create. UI worker owns this file.**

Export a standalone English `HTML` string with inline CSS/JS, no dependencies. Keep the three screens in one document and one selected-root/snapshot state. Sessions loads the new all-history root list; search title/project, default newest-first and allow total-token sorting. Each root row is selectable regardless of archived status. Root warnings are visible.

Selecting a root loads Usage with the list snapshot token. Render header, completeness and reasons, five overall counters, expandable role rows containing distinct agents and their model usage, and a model table. Only roles present appear. Show Unknown literally. Explain the input/output subsets once. Do not add pricing, charts or scoring.

Inspect loads inventory and first event page lazily on navigation. Provide agent/category filters and paging. Show raw types, source filename/line, timestamp/session, statuses, unknown counts, reasoning availability and unmatched counts. Expand/collapse a record with an event-detail fetch only on first expansion; show truncated status. Pair navigation fetches related events by opaque IDs. Remote-only roots and empty/unavailable histories explain why original records cannot be displayed.

Use `textContent`/DOM nodes for log-controlled values, including errors and JSON. Never inject unescaped previews, content, filenames, roles or tool output into HTML. Use request-generation guards so slow root/filter/detail responses cannot replace current selection. A 409 clears stale selected-root data and offers refresh; never silently mix snapshots. Include loading/error/empty states and keyboard-accessible buttons/forms. Preserve selected root on Usage/Inspect/back navigation.

### `tests/test_session_analysis.py`

**Action: Create. Core worker owns this file.**

Use synthetic JSONL fixtures and standard unittest. Cover counter reconciliation, model switching, overlapping usage families/duplicate IDs, inherited baselines, same-role distinct agents, unknown attribution, ancestry/cycles/orphans/missing children, archived/resumed grouping and source-pinned HTTP contracts. Test shared reader modes/physical positions, default fast projection and malformed/trailing line behavior. Include disallowed host/path/id and stale-source handling where integration owns the behavior.

### `tests/test_session_inspect.py`

**Action: Create. Inspect worker owns this file.**

Use temporary synthetic logs plus the shared reader imported through the same script-loading pattern. Cover category/raw inventories, Unicode/BOM/physical lines, chronological stable ties, out-of-order call/result interleaving, unknown records, ambiguity/missing pairs, encrypted versus readable reasoning, exact lazy record retrieval, bounded content, unavailable remote histories, traversal/source containment and source mutation. Assert malicious log text remains data; UI smoke validates rendering.

### `README.md`

**Action: Modify. Main owns this file.**

Describe the three-screen workflow, root grouping, role/agent/model accounting, subsets, incomplete warnings, lazy local originals, remote limitations, encrypted reasoning, source mutation refresh and supported modern token format. Keep existing install/launch instructions accurate. No private transcript excerpts or identifiers.

### Delivery docs

**Action: Create. Designer owns** `docs/session-analysis-implementation-plan.md` **and** `docs/session-analysis-lld.md`. Main owns the downloaded approved `docs/session-analysis-design.md`. The recursive installer already includes sibling Python modules; launcher/installer source changes are not planned unless validation finds a concrete compatibility defect.

## 3. Cross-File Dependencies

1. Core establishes the opt-in source reader, canonical accounting, root IDs, exact snapshot descriptors and routes.
2. Inspect consumes the reader callback and descriptors; it owns event interpretation only, never accounting.
3. UI consumes public JSON only; it never derives filesystem paths or accounting totals.
4. Core imports the two sibling modules and maps their exceptions to HTTP responses. Main integrates documentation and resolves contract conflicts.
5. Focused tests run before full regressions, then real local source validation and browser flow verification. No worker edits another worker's files.

## 4. File Change Summary

| File | Action | Purpose |
| --- | --- | --- |
| `skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py` | Modify | Reader, canonical usage, root snapshots, API integration |
| `skills/codex-usage-dashboard/scripts/session_inspect.py` | Create | Lazy source-backed event inventory and expansion |
| `skills/codex-usage-dashboard/scripts/session_analysis_ui.py` | Create | English Sessions, Usage and Inspect UI |
| `tests/test_session_analysis.py` | Create | Canonical accounting, identity, reader and API checks |
| `tests/test_session_inspect.py` | Create | Inventory, source and detail checks |
| `README.md` | Modify | Actual workflow and format limitations |
| `docs/session-analysis-design.md` | Create | Exact approved functional specification |
| `docs/session-analysis-implementation-plan.md` | Create | Delivery sequence and acceptance |
| `docs/session-analysis-lld.md` | Create | File-level contracts and invariants |

## 5. Risks and Acceptance

The main risks are unresolved modern usage overlap, historical fork baselines, duplicate resumed sources, live-file mutation and oversized payloads. These are handled with canonical observations, retained known amounts, explicit incompleteness, pinned source checks and bounded expansions. No outstanding user decision is required. A substantive contradiction with focused new evidence returns to Main; workers must not silently redefine totals or JSON contracts.

Acceptance requires the implementation-plan checks, reconciliation and source/security tests above, all existing regressions, direct/installed launcher compatibility, and a working multi-agent Usage → Inspect browser demonstration on actual local logs. Design work performed only reads/templates and writes these two design documents; it does not claim implementation tests have run.
