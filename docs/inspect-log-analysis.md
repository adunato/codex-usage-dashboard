# Local Codex execution-log evidence

Analysed at **2026-10-18T10:58:04+00:00**, against repository revision `7983abd409bcef2eae76155bc95d5c9b9eea70c9`. This report covers actual local logs and existing parser behaviour. No application code was modified. It is evidence, not a design or implementation proposal.
Focused attribution, body-format, failure and adjacency checks continued through **2026-10-18T11:11:11+00:00** on the same selected files.

## 1. Scope, units and provenance

The sample comprises three distinct user-rooted sessions and their locally available descendant threads: **57 JSONL files, 43,499 outer records**. The selection was the three largest roots, by the root file’s outer-record count, with `session_meta.thread_source = "user"` and at least one available descendant. This deliberately samples substantial multi-agent work; it is not a random or representative sample of all Codex use. Parent traversal found no overlapping selected trees.

| Session tree | Root records | Direct children | All threads/files | All outer records | Root log timestamp span (UTC) |
|---|---|---|---|---|---|
| R0 | 4,261 | 20 | 34 | 20,898 | 2026-10-14T14:10:35.604Z to 2026-10-15T19:54:48.695Z |
| R1 | 2,933 | 7 | 16 | 13,513 | 2026-10-14T09:36:38.214Z to 2026-10-14T19:36:43.642Z |
| R2 | 2,755 | 6 | 7 | 9,088 | 2026-10-15T07:08:43.689Z to 2026-10-15T13:56:00.813Z |

The discovery pass found 96 plain JSONL files with usable `session_meta` and 39 without it. It counted no malformed JSON or non-object JSON rows in the inspected plain-log pass. Compressed `.jsonl.zst` logs were not decoded for this sample, and metadata-free files were not used to build these trees. Available descendants therefore mean available **within this plain-JSONL scan**, not proof that no other local/archive thread exists. A string-valued `session_meta.source` is valid observed data; treating it as an object incorrectly excludes user logs.

Aliases such as `R0.4:L16` identify a containing log and a 1-based physical JSONL line. They replace private filenames and IDs; this report intentionally does not publish the private alias mapping. Counts refer to outer records unless explicitly labelled distinct IDs, nested objects, or thread totals. Embedded compaction histories are data inside one outer record, not additional inventory events. Field **presence** does not imply a nonempty value. Schema examples below replace all original identifiers and message bodies; no prompts, results, tool arguments/output, nicknames, account IDs or local paths are reproduced.

## 2. Complete observed event inventory

Every observed outer `type` / inner `payload.type` combination is listed below. `—` means no inner type. Every selected record has outer `type`, `payload`, `timestamp`, and `ordinal`. Outer `metadata` is additional on some response records, with coverage recorded in the schema table below.

| Outer type / payload.type | R0 | R1 | R2 | Total |
|---|---|---|---|---|
| compacted / — | 12 | 7 | 2 | 21 |
| event_msg / item_completed | 5,164 | 3,533 | 2,304 | 11,001 |
| event_msg / task_complete | 189 | 140 | 39 | 368 |
| event_msg / task_started | 238 | 166 | 47 | 451 |
| event_msg / thread_settings_applied | 63 | 45 | 14 | 122 |
| event_msg / token_count | 2,599 | 1,647 | 1,267 | 5,513 |
| event_msg / turn_aborted | 8 | 3 | 2 | 13 |
| inter_agent_communication_metadata / — | 778 | 438 | 392 | 1,608 |
| response_item / agent_message | 778 | 438 | 392 | 1,608 |
| response_item / custom_tool_call | 1,109 | 749 | 561 | 2,419 |
| response_item / custom_tool_call_output | 1,109 | 749 | 561 | 2,419 |
| response_item / function_call | 1,142 | 664 | 511 | 2,317 |
| response_item / function_call_output | 1,142 | 664 | 511 | 2,317 |
| response_item / message | 820 | 557 | 182 | 1,559 |
| response_item / reasoning | 2,615 | 1,863 | 1,100 | 5,578 |
| session_meta / — | 67 | 31 | 13 | 111 |
| token_usage_record / — | 2,380 | 1,501 | 1,105 | 4,986 |
| turn_context / — | 250 | 173 | 49 | 472 |
| world_state / — | 435 | 145 | 36 | 616 |
| **Total** | 20,898 | 13,513 | 9,088 | **43,499** |

The following is the complete union of **immediate payload field names** for each pair. A parenthesised count means that field was present in fewer than all records of that pair; unmarked fields were present in all. `type` is included where observed. Nested execution-relevant fields are described immediately afterwards. This reports fields, never their private values.

| Pair | Available payload fields (presence count if optional) | Outer metadata coverage |
|---|---|---|
| compacted / — | `compaction_response_id`, `first_window_id`, `guardian_history` (1/21), `latest_token_usage_record`, `message`, `previous_window_id`, `replacement_history`, `replacement_history_metadata`, `resume_metadata`, `retained_context`, `window_id`, `window_number` | 0/21 |
| event_msg / item_completed | `completed_at_ms`, `item`, `started_at_ms`, `thread_id`, `turn_id`, `type` | 0/11,001 |
| event_msg / task_complete | `completed_at`, `duration_ms`, `error` (4/368), `last_agent_message`, `root_turn_id`, `started_at`, `time_to_first_token_ms`, `turn_id`, `type` | 0/368 |
| event_msg / task_started | `collaboration_mode_kind`, `model_context_window`, `root_turn_id`, `started_at`, `turn_attribution`, `turn_id`, `type` | 0/451 |
| event_msg / thread_settings_applied | `thread_id`, `thread_settings`, `type` | 0/122 |
| event_msg / token_count | `info`, `rate_limits`, `type` | 0/5,513 |
| event_msg / turn_aborted | `completed_at`, `duration_ms`, `reason`, `root_turn_id`, `started_at`, `turn_id`, `type` | 0/13 |
| inter_agent_communication_metadata / — | `trigger_turn` | 0/1,608 |
| response_item / agent_message | `author`, `content`, `id`, `internal_chat_message_metadata_passthrough`, `recipient`, `type` | 1,608/1,608 |
| response_item / custom_tool_call | `call_id`, `id`, `input`, `internal_chat_message_metadata_passthrough`, `name`, `status`, `type` | 0/2,419 |
| response_item / custom_tool_call_output | `call_id`, `id`, `internal_chat_message_metadata_passthrough`, `output`, `type` | 2,419/2,419 |
| response_item / function_call | `arguments`, `call_id`, `id`, `internal_chat_message_metadata_passthrough`, `name`, `namespace` (2,308/2,317), `type` | 2,317/2,317 |
| response_item / function_call_output | `call_id`, `id`, `internal_chat_message_metadata_passthrough`, `output`, `type` | 2,317/2,317 |
| response_item / message | `content`, `id`, `internal_chat_message_metadata_passthrough`, `phase` (676/1,559), `role`, `type` | 1,220/1,559 |
| response_item / reasoning | `encrypted_content`, `id`, `internal_chat_message_metadata_passthrough`, `summary`, `type` | 7/5,578 |
| session_meta / — | `agent_nickname` (75/111), `agent_path` (75/111), `agent_role` (75/111), `base_instructions`, `cli_version`, `context_window`, `creator_account_id`, `creator_user_id`, `cwd`, `forked_from_id` (75/111), `history_mode`, `id`, `model_provider`, `multi_agent_version` (75/111), `originator`, `parent_thread_id` (75/111), `runtime_workspace_roots`, `session_id`, `source`, `subagent_history_start_ordinal` (75/111), `thread_source`, `timestamp` | 0/111 |
| token_usage_record / — | `response_id`, `root_turn_id`, `session_id`, `thread_id`, `thread_token_usage`, `turn_id`, `turn_token_usage`, `usage` | 0/4,986 |
| turn_context / — | `active_permission_profile`, `approval_policy`, `approvals_reviewer`, `collaboration_mode`, `comp_hash`, `current_date`, `cwd`, `cyber_access_program` (464/472), `disabled_plugin_ids`, `effort`, `model`, `multi_agent_version`, `permission_profile`, `personality`, `realtime_active`, `root_turn_id`, `sandbox_policy`, `summary`, `timezone`, `turn_id`, `workspace_roots` | 0/472 |
| world_state / — | `full`, `state` | 0/616 |

### What the records contain and can establish

| Record family | Nested fields and information | Execution value and limits |
|---|---|---|
| `session_meta` | `base_instructions.{text,provenance}`; `source.subagent.thread_spawn` when object-valued; `context_window.window_id`; identity, parent/fork, role/path/nickname and runtime metadata. | Identifies threads and ancestry. Role/nickname are labels, not join keys. Account/cwd/instruction values are private and omitted. Multiple metadata records require care; see relationship evidence. |
| `response_item/message` | `content[].{type,text}`, `role`, optional `phase`; internal metadata can carry turn IDs and creation time. | User/developer/assistant text is an item, not automatically a tool invocation or completed task. A final-phase message is a recorded answer, not proof of successful execution. |
| `response_item/reasoning` | `summary` and `encrypted_content` plus item ID. | A summary may be readable; field presence alone does not establish readable content. Encrypted reasoning cannot be reconstructed from these logs. |
| `response_item/agent_message` | `author`, `recipient`, `content`, `id`, internal turn metadata. | Inter-agent communication. Author path can link a sender; recipient and turn metadata are needed to distinguish parent delivery, peer messages and repeated appearances. |
| Function/custom calls and outputs | Function `arguments` is encoded structured input; custom `input` is tool-specific text. Outputs carry `call_id` and `output`, which may itself be text or structured content. | One call is one recorded outer invocation. Call and output are two halves of that invocation. Text inside `exec` is not independently recorded invocation evidence. |
| `item_completed` | `item.{id,type,kind,agent_thread_id,agent_path,status,error}` as applicable; variants also include command/exit code/output, tool/result fields, sender/receiver IDs, questions, patches and summaries. Outer payload has `thread_id`, `turn_id`, `started_at_ms`, `completed_at_ms`. | Lifecycle/timing evidence for completed items, including agent interaction states. Shares some IDs with response items but contributes extra fields; it is not a count of agents or successful actions. |
| `task_started`, `task_complete`, `turn_aborted` | `turn_id`, `root_turn_id`, `started_at`; terminal `completed_at`, `duration_ms`; complete has `time_to_first_token_ms`, `last_agent_message`, optional structured `error`; aborted has `reason`. | Turn timing and explicit completion/abort/error signals. Join within a containing thread, not by chronological adjacency. |
| `token_count` | `info.{total_token_usage,last_token_usage,model_context_window}`; usage counters include input, cached input, output, reasoning output and total; `rate_limits` is separate quota telemetry. | Cumulative and most-recent usage snapshots, not a new response for every event. Never sum successive cumulative values. |
| `token_usage_record` | `response_id`, `thread_id`, `session_id`, `turn_id`, `root_turn_id`; `usage`, `thread_token_usage`, `turn_token_usage` each contain `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`, `output_tokens`, `reasoning_output_tokens`, `total_tokens`. | Response contributions and thread/turn cumulative snapshots. Response IDs permit measured duplicate detection; thread/turn/session IDs have different scopes. |
| `inter_agent_communication_metadata` | `trigger_turn` is a boolean. | Whether communication triggers a turn; it is not a turn/message ID. Exact adjacency was observed, but there is no shared-ID join. |
| `turn_context`, `thread_settings_applied` | Turn/root IDs, model/effort and permission/settings context; `thread_settings` contains applied settings. | Describes execution conditions, not distinct work. Settings rows are not model invocations. |
| `world_state` | `full`, `state` with instructions, environments, tools, skills, model, permissions, collaboration and multi-agent context. | Context snapshots/deltas; not agent actions. Tool availability does not establish a tool was called. |
| `compacted` | Window IDs, `message`, `replacement_history`, metadata, `retained_context`, `resume_metadata`, and embedded `latest_token_usage_record`; `guardian_history` occurs once. | Compaction/context replacement. Nested messages/tools/token snapshots can repeat earlier evidence; counting them again would inflate actions and usage. |

The current inspector assigns broad categories to response messages, reasoning, calls, results and selected event messages; the inventory is more detailed than those categories. Raw classification, bounded previews and pairing are in [skills/codex-usage-dashboard/scripts/session_inspect.py:30](../skills/codex-usage-dashboard/scripts/session_inspect.py#L30) and [skills/codex-usage-dashboard/scripts/session_inspect.py:162](../skills/codex-usage-dashboard/scripts/session_inspect.py#L162). It reads details lazily from source offsets and removes `encrypted_content` from returned detail ([skills/codex-usage-dashboard/scripts/session_inspect.py:280](../skills/codex-usage-dashboard/scripts/session_inspect.py#L280)). The shared reader preserves line/offset references and emits parse-error diagnostics for malformed complete rows ([skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:1198](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L1198)). These are source-code observations; no application test suite was executed for this documentation-only change.

## 3. Agent identities, delegation and result links

There are **3 user roots and 54 available descendants**. All 54 descendant identities have parent links inside their selected tree. The 111 metadata records include 75 occurrences with `agent_role`, `agent_nickname`, `agent_path`, `parent_thread_id`, `forked_from_id`, and `subagent_history_start_ordinal`; these are **occurrences**, not 75 distinct agents. The field `root_session_id` was absent from all 111 metadata rows. The root is therefore established by parent traversal and user-source metadata, not an assumed root-ID field.

Each root file has one metadata record; all 54 child files have two, with different identities. For example, `R0.1:L1` and `R0.1:L2` are different metadata identities. The parser takes the first metadata and ignores subsequent metadata for source identity; the inspector stamps the file’s records with that source descriptor. The scan likewise uses the first identity. A later metadata record therefore does not establish an additional agent or a change of owner for the containing file. Embedded/inherited records must be distinguished from new work. See [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:1275](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L1275) and [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:3543](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L3543).

| Join | Observed coverage | What it establishes |
|---|---|---|
| Child `session_meta.parent_thread_id` → parent identity | 54/54 available descendants | Direct ancestry; role/nickname are descriptive only. |
| Call/output `(thread, family, call_id)` | 55/55 spawn calls have a paired output | Which response belongs to each recorded spawn request. |
| Spawn output `task_name` → child `agent_path`, scoped to parent | 54/55 spawn attempts resolve uniquely; R0 33/34, R1 15/15, R2 6/6 | Connects `arguments.message` and its role/task arguments to the available child. The remaining attempt is discussed below. |
| Parent `item_completed.item.agent_thread_id` → child identity | 857 direct-child reference rows across all trees; 420 in R0 | Independent activity/lifecycle references. Repetitions are not additional descendants. |
| Same field referencing other thread IDs | 751 rows across all trees; 360 in R0 | Not direct-child counts. They may concern self/peers/deeper threads; the direct-parent relation must come from metadata. |
| Agent message `author` → child `agent_path` | Per-child counts for R0 below | A sender-origin match; this alone does not prove a final result or delivery to the parent. |

All 55 spawn calls carry `arguments.message`. Their recorded arguments include `task_name`, `agent_type`, `fork_turns`, and `message`; the paired successful structured outputs expose `task_name`, rather than a child thread ID. The assignment body is the call’s `arguments.message`; a child’s `base_instructions.text` is a separate instruction source and is not interchangeable with that assignment. Follow-up calls/messages can assign later work, so one initial spawn instruction does not describe every later turn.

**All 55 assignment bodies are opaque strings beginning with `gAAAAA` (R0 34/34, R1 15/15, R2 6/6), including all 33 resolved R0 assignments.** This is a Fernet-style ciphertext marker; the exact producing algorithm was not independently established and no decryption key was examined. Assignment linkage and location are recoverable, but the instruction wording is not. Classifying these strings as ordinary text because they are JSON strings would be wrong. This is distinct from the separate `reasoning.encrypted_content` field. The report does not infer task meaning from role names or incidental substrings in ciphertext.

An alias-only structural example of the observed join is:

```text
parent response_item/function_call: name=spawn_agent, call_id=CALL-A,
  arguments={task_name:TASK-A, agent_type:ROLE-A, message:[assignment omitted]}
parent function_call_output: call_id=CALL-A, output={task_name:PATH-A}
child session_meta: id=THREAD-A, parent_thread_id=PARENT-A, agent_path=PATH-A
parent item_completed: item.agent_thread_id=THREAD-A
parent agent_message: author=PATH-A, recipient=[recorded recipient],
  content=[communication omitted]
```

This example preserves field relationships, not original values. `R0.0:L16` is a real assignment-call location resolving to `R0.4`; `R0.0:L22` resolves to `R0.3`. The exceptional attempt is `R0.1:L61`, with a same-call-ID output at `R0.1:L63`. Its output is a plain error string rather than a structured task-name result. Private inspection established an explicit **agent-thread-capacity spawn failure**; the error text is not reproduced. Thus R0 has 34 spawn attempts, 33 uniquely linked children and one confirmed failed attempt. It is not an unpaired tool call or evidence of an additional missing child log.

Parser ancestry/role extraction is in [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:3543](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L3543), spawn call/output handling in [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:3632](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L3632), and child references/timing in [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:3662](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L3662). Tree grouping explicitly handles missing parents/children, duplicate sources and cycles ([skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:2940](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L2940)). Recorded metadata and actual ID joins take precedence over a role name or prose mention of another agent.

## 4. Distinct activity, overlaps and invocation counts

Across the sample there are **2,317 function calls and 2,419 custom tool calls**, with exactly one output per `(containing thread, tool family, call_id)`: **4,736 operations represented by 9,472 rows**. There are zero missing call IDs, unmatched calls, unmatched outputs, or ambiguous IDs in this sample. These zeros describe the selected files; the inspector still supports orphan and ambiguity states ([skills/codex-usage-dashboard/scripts/session_inspect.py:239](../skills/codex-usage-dashboard/scripts/session_inspect.py#L239)).

| Recorded call name | Invocations |
|---|---|
| `exec` | 2,419 |
| `send_message` | 1,204 |
| `wait_agent` | 691 |
| `followup_task` | 161 |
| `list_agents` | 94 |
| `sleep` | 94 |
| `spawn_agent` | 55 |
| `request_user_input_async` | 9 |
| `js` | 8 |
| `interrupt_agent` | 1 |

These are outer tool invocations. A custom `exec` call can invoke multiple nested APIs or shell commands; those operations cannot be counted reliably from this outer-call table. A call without its result would still be an invocation, but no such orphan occurs here.

`item_completed.item.id` intersects `response_item.id` for **6,118 IDs**, each appearing exactly once in each stream: R0 **2,865**, R1 **2,066**, R2 **1,187**. That is a measured link between two recorded views. Completion telemetry adds timing and state, so it is not redundant content to discard. Exact equality between `item.kind` and `response_item.type` was zero because these are different labels: in R0 the actual shared-ID type pairs are **2,615 `Reasoning` → `reasoning`** and **250 `AgentMessage` → `message`**. For example, `R0.0:L14` (`item_completed.item.type = AgentMessage`) and `R0.0:L15` (`response_item.type = message`) share an ID. A kind label cannot substitute for the ID join.

There are **1,608 inter-agent metadata rows and 1,608 agent-message rows**. Every metadata row is immediately **followed by** a message, and every message is immediately **preceded by** metadata: R0 778/778, R1 438/438, R2 392/392. This directional rule gives nonoverlapping observational pairs. Undirected “either neighbour” matching is ambiguous for 209 messages (R0 113, R1 44, R2 52), which also have metadata after them. `trigger_turn` is a **boolean**, with true/false counts R0 117/661, R1 65/373, R2 32/360; it is not a turn or message ID. The directional pairs can be kept together as observed communication bundles, but adjacency is not an ID-based delivery join. Likewise, a task’s `last_agent_message`, a final response item and an agent-message result can represent related text without separately executed work. No text-equality deduplication is claimed.

Response messages and reasoning summaries are separate emitted items. Neither should be counted as a tool call. The 21 compaction rows contain retained/replacement histories and usage snapshots; their embedded items are excluded from outer-action and token-contribution counts. Repeated token snapshots are observations of accounting, not additional model responses.

Of the **5,578 reasoning items**, **1,005** have nonempty extracted summary text as well as encrypted content; **4,573** have encrypted content only; none is summary-only or empty in both fields. All 5,578 encrypted-content values have the `gAAAAA` marker. None of the 1,005 nonempty extracted summaries starts with that marker; this is a content-shape check, not a cryptographic or semantic validation of every summary block. A recorded summary does not recover the encrypted remainder. The 1,559 ordinary message items comprise **452 developer, 431 user and 676 assistant** messages. Phase counts are **312 commentary, 364 final_answer and 883 missing**. All ordinary-message and all 1,608 agent-message `content` values are lists; text must be extracted from their content blocks rather than assuming the field is a string. Final-answer rows are not extra completed tasks merely because a completion record also contains an answer.

### Copied history versus newly recorded activity

The 54 child metadata records supply `subagent_history_start_ordinal`. Comparing outer `ordinal` with that marker partitions the files into **1,925 pre-boundary records** and later records; roots have no boundary. The prefix also contains current-thread metadata, so not every pre-boundary record is a duplicate. Exact payload/ID comparisons are needed to establish copying.

| Tree | Pre-boundary records | Pre-boundary task completes | Pre-boundary task starts | Pre-boundary aborts | Pre-boundary messages | Shared response-item IDs across files | Shared call-ID/family keys |
|---|---|---|---|---|---|---|---|
| R0 | 1169 | 70 | 115 | 4 | 455 | 76 | 0 |
| R1 | 632 | 62 | 85 | 0 | 277 | 40 | 0 |
| R2 | 124 | 4 | 10 | 0 | 67 | 12 | 0 |

There are **136 extra cross-file copies of task completions**, with the same `turn_id` and identical full payload: R0 70, R1 62, R2 4; zero conflicting payload variants were observed for those shared IDs. These are duplicate observations of earlier work, not additional completed agent turns. Example: the completion at `R0.0:L227` is copied at `R0.1:L16` and in further child prefixes. Across all three trees, **zero tool call/output, reasoning, token-count or modern token-usage rows occur before the boundary**. No tool call-ID/family key is shared across files. The 4,736 tool operations are consequently not inflated by these inherited prefixes.

R0 also has **76 response-item ID keys shared across files**. Of these, 72 keys have identical payloads and account for **380 extra exact-copy rows**; the other four keys have payload variants, so ID equality alone is insufficient for those. Twenty-two repeated keys also participate in same-file response/completion telemetry joins. Response-copy consolidation consequently overlaps the telemetry grouping below and cannot be added blindly to its reduction. This is different from tool call IDs, for which no cross-file repeats were found.

## 5. Timing, token statistics and explicit failures

### Timing that can be calculated

All **368 raw `task_complete` rows** contain `duration_ms`, `started_at`, `completed_at`, and `time_to_first_token_ms`. After removing the 136 exact copied completions, there are **232 distinct completed turns**. For each source agent, the post-boundary task records give its recorded count/sum/min/max/mean of durations and first-token samples; these can be joined to starts by turn ID. A timestamp span is only the first-to-last logged observation, can include idle/inherited periods, and is not active execution time. Task durations include waiting and overlap across agents; their sums are not tree wall time or CPU time.

| Tree | Raw completion rows | Exact copied rows | Distinct completed turns | Raw duration sum (ms) | Distinct-turn duration sum (ms) | Raw abort records / post-boundary abort records |
|---|---|---|---|---|---|---|
| R0 | 189 | 70 | 119 | 88,528,425 | 32,632,786 | 8 / 4 |
| R1 | 140 | 62 | 78 | 38,949,777 | 20,097,543 | 3 / 3 |
| R2 | 39 | 4 | 35 | 21,915,382 | 17,246,870 | 2 / 2 |

The raw-file join `(containing file, turn_id)` gives **451 starts**, **368 completes plus 13 aborts = 381 terminals**, **73 starts without a terminal**, and **3 terminals without a start**. There are no repeated start/terminal IDs within an individual file or multiple-terminal joins. These are not globally unique task counts: copied histories repeat IDs across files. Post-boundary totals are 241 starts and 232 completes plus 9 abort records. Neither raw subtraction nor equal aggregate endpoint counts proves unfinished or successful work. Missing raw endpoints describe unbracketed evidence, not a hung task. Item timings are recorded in milliseconds and should be attributed through item ID and thread/turn context. Timestamp-derived intervals were not independently reconciled against every recorded `duration_ms`, so no exact interval-equality claim is made.

### Token totals that can be calculated

There are **5,513 legacy `token_count` snapshots** and **4,986 modern `token_usage_record` rows**. All modern rows have a nonmissing response ID, and there are zero duplicate IDs or conflicting contributions within a thread and zero response-ID overlaps across the 57 threads. All 4,986 `thread_id` values match the containing thread identity. `session_id` has a different scope: it is populated on every modern row, but only 1,073 match the containing thread identity. It must not replace `thread_id` for per-agent grouping.

For **all 57 threads**, summing the distinct modern `usage.total_tokens` values equals the final observed `thread_token_usage.total_tokens`. This supports a reproducible **recorded response-usage total** per thread and a sum across distinct response IDs in each tree. It is not a claim about billing, hidden activity, or complete causal attribution. The last legacy cumulative snapshot sometimes precedes the modern tail; these are two observations of accounting and must not be added together.

| Tree | Modern distinct response records | Sum distinct modern usage.total_tokens | Sum last legacy cumulative totals (comparison only) | Difference |
|---|---|---|---|---|
| R0 | 2,380 | 216,092,114 | 214,800,137 | 1,291,977 |
| R1 | 1,501 | 134,188,214 | 132,989,290 | 1,198,924 |
| R2 | 1,105 | 139,926,193 | 139,553,597 | 372,596 |

The recorded counter components are input, cached input, cache-write input, output, reasoning output and total. Cached/reasoning counters are subsets and must not be added again to input/output totals. The legacy scan observed zero counter-component decreases, zero rows missing `total_tokens`, and zero `total_tokens != input_tokens + output_tokens` inconsistencies. That does not prove every possible accounting invariant or six-component cross-family equality. Request counts based on modern response IDs are distinct from tool-invocation counts.

The parser treats legacy cumulative snapshots as authoritative when families overlap; it deduplicates modern contributions by response ID and only attaches a compatible modern tail. The implementation is in [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:3439](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L3439), [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:3641](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L3641) and [skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:3739](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L3739). Inherited usage is normalised by matching token-vector prefixes against a parent timeline ([skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:2478](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L2478)); it does not use `subagent_history_start_ordinal` as a causal accounting rule. An ordinal boundary alone cannot prove duplicated execution. The raw totals in this report are observed modern records, not a claim that parser-normalised attribution or billed totals must be identical.

The same normalisation routine filters task timing only when an inherited-token prefix establishes an inherited cutoff, then recomputes timing aggregates ([skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py:2580](../skills/codex-usage-dashboard/scripts/codex_usage_dashboard.py#L2580)). The observed task-only history copies therefore need their own evidence check; this report uses exact task payload/turn-ID duplication plus the boundary partition rather than assuming token normalisation proves timing attribution. No claim is made here that the dashboard output was executed and observed to equal these independently measured totals.

### Explicit failure evidence

**Four of 368 raw task completions carry nonempty structured `error` values**: `R2.0:L1737`, `R2.1:L506`, `R2.5:L127`, and `R2.6:L751`. They have four distinct turn IDs, all after the history boundary, so these are not copied failure observations. The error schema includes `message` and `codex_error_info`; private error text is omitted. The **13 raw `turn_aborted` records** (9 after the history boundary) are explicit abort signals. Neither a completion without an error field nor an agent lifecycle `completed` state proves semantic success. The explicit capacity failure at `R0.1:L61–63` is a separately established failed spawn attempt; it is included in tool invocation counts but has no linked child.

All **11,001 item-completion rows** occur after the boundary (zero inherited-prefix copies). Their explicit structured outcome values are measured below. These indicators overlap on the same item and **must not be added as independent failures**. Nonzero command exit status records process failure; it does not alone establish failure of the entire delegated task.

| Item field | Field present | Measured values |
|---|---|---|
| `item.exit_code` | 1,738/11,001 | 1,513 zero; 225 nonzero |
| `item.status` | 2,999/11,001 | 2,751 completed; 248 failed |
| `item.result.isError` | 281/11,001 | 259 false; 22 true |
| `item.error` nonempty | 1/11,001 | 1 structured object |

Row-level overlap checks found **248 flagged item rows**: 225 have both failed status and nonzero exit code, 22 have failed status and result.isError=true, and one has failed status plus nonempty item.error. The other 10,753 rows have none of these four indicators. This union counts observed item rows, not failed whole tasks.

Per-agent counts of explicit adverse item values follow; zero means no such value observed, not proof of success. `E`, `F`, `I`, `R` denote nonzero exit code, status failed, result.isError true, and nonempty item.error respectively. Task-completion errors and aborted turns are separate record families above.

| Agent | E | F | I | R |
|---|---|---|---|---|
| R0.0 | 14 | 14 | 0 | 0 |
| R0.1 | 0 | 0 | 0 | 0 |
| R0.2 | 1 | 1 | 0 | 0 |
| R0.3 | 0 | 0 | 0 | 0 |
| R0.4 | 5 | 5 | 0 | 0 |
| R0.5 | 0 | 0 | 0 | 0 |
| R0.6 | 16 | 16 | 0 | 0 |
| R0.7 | 1 | 1 | 0 | 0 |
| R0.8 | 0 | 0 | 0 | 0 |
| R0.9 | 12 | 12 | 0 | 0 |
| R0.10 | 1 | 2 | 1 | 0 |
| R0.11 | 9 | 9 | 0 | 0 |
| R0.12 | 6 | 6 | 0 | 0 |
| R0.13 | 0 | 0 | 0 | 0 |
| R0.14 | 13 | 13 | 0 | 0 |
| R0.15 | 2 | 3 | 1 | 0 |
| R0.16 | 8 | 8 | 0 | 0 |
| R0.17 | 13 | 13 | 0 | 0 |
| R0.18 | 2 | 2 | 0 | 0 |
| R0.19 | 0 | 0 | 0 | 0 |
| R0.20 | 0 | 0 | 0 | 0 |
| R0.21 | 0 | 0 | 0 | 0 |
| R0.22 | 0 | 0 | 0 | 0 |
| R0.23 | 0 | 1 | 1 | 0 |
| R0.24 | 0 | 2 | 2 | 0 |
| R0.25 | 0 | 1 | 1 | 0 |
| R0.26 | 0 | 1 | 1 | 0 |
| R0.27 | 0 | 0 | 0 | 0 |
| R0.28 | 0 | 0 | 0 | 0 |
| R0.29 | 0 | 0 | 0 | 0 |
| R0.30 | 0 | 0 | 0 | 0 |
| R0.31 | 0 | 0 | 0 | 0 |
| R0.32 | 0 | 0 | 0 | 0 |
| R0.33 | 0 | 0 | 0 | 0 |
| R1.0 | 0 | 0 | 0 | 0 |
| R1.1 | 0 | 0 | 0 | 0 |
| R1.2 | 0 | 0 | 0 | 0 |
| R1.3 | 14 | 14 | 0 | 0 |
| R1.4 | 4 | 4 | 0 | 0 |
| R1.5 | 11 | 12 | 1 | 0 |
| R1.6 | 39 | 39 | 0 | 0 |
| R1.7 | 0 | 0 | 0 | 0 |
| R1.8 | 0 | 0 | 0 | 0 |
| R1.9 | 0 | 0 | 0 | 0 |
| R1.10 | 0 | 1 | 1 | 0 |
| R1.11 | 0 | 2 | 2 | 0 |
| R1.12 | 0 | 1 | 1 | 0 |
| R1.13 | 0 | 0 | 0 | 0 |
| R1.14 | 0 | 8 | 8 | 0 |
| R1.15 | 0 | 3 | 2 | 1 |
| R2.0 | 10 | 10 | 0 | 0 |
| R2.1 | 4 | 4 | 0 | 0 |
| R2.2 | 1 | 1 | 0 | 0 |
| R2.3 | 33 | 33 | 0 | 0 |
| R2.4 | 1 | 1 | 0 | 0 |
| R2.5 | 2 | 2 | 0 | 0 |
| R2.6 | 3 | 3 | 0 | 0 |

The **4,736 tool-output rows** have 2,310 string outputs and 2,426 list outputs. Of the strings, 847 parse as JSON objects and 1,463 do not. None of the parsed objects has a top-level `error`, `failed`, `failure`, `status`, `success`, `exit_code`, `isError` or `returncode` field. This does not inspect arbitrary nested list content or classify non-JSON strings as outcomes; the capacity failure above was a separate private inspection. A key’s presence or an incidental “error” substring is not a failure count. There is no universal total of failed tasks derivable by adding these heterogeneous signals.

## 6. Concrete reconstruction of R0

R0 has **one orchestrator, 20 direct children and 13 grandchildren**. The tree below uses actual metadata parent links. Role names are recorded labels; `Main` is this report’s label for the user root.

```text
R0.0 Main
├─ R0.1 debugger
│  ├─ R0.21 debug-specialist
│  ├─ R0.22 explorer
│  ├─ R0.23 explorer
│  ├─ R0.24 explorer
│  ├─ R0.25 explorer
│  └─ R0.26 explorer
├─ R0.2 debugger
├─ R0.3 designer
│  └─ R0.27 design-specialist
├─ R0.4 explorer
├─ R0.5 explorer
├─ R0.6 explorer
├─ R0.7 explorer
├─ R0.8 reviewer
│  ├─ R0.28 explorer
│  ├─ R0.29 explorer
│  ├─ R0.30 explorer
│  ├─ R0.31 explorer
│  ├─ R0.32 explorer
│  └─ R0.33 review-specialist
├─ R0.9 validator
├─ R0.10 validator
├─ R0.11 validator
├─ R0.12 validator
├─ R0.13 worker
├─ R0.14 worker
├─ R0.15 worker
├─ R0.16 worker
├─ R0.17 worker
├─ R0.18 worker
├─ R0.19 worker-sol
└─ R0.20 worker-sol
```

The following supplies the assignment and return evidence for **every available R0 edge**. “Assignment” is the parent log line containing the opaque `spawn_agent.arguments.message`; its wording cannot be reconstructed. “Completed” counts `item_completed.item.kind = completed` references to that child, and “author messages” counts child-path authors found in the parent log. These are recorded lifecycle/communication results, not a success claim or a count of distinct final answers. Initial assignments can be followed by additional work.

| Child | Parent / assignment source | Assignment body present | Lifecycle rows / completed states | Author messages in parent |
|---|---|---|---|---|
| R0.1 | R0.0:L636 | yes | 31 / 8 | 23 |
| R0.2 | R0.0:L2771 | yes | 15 / 6 | 15 |
| R0.3 | R0.0:L22 | yes | 18 / 2 | 6 |
| R0.4 | R0.0:L16 | yes | 14 / 3 | 9 |
| R0.5 | R0.0:L86 | yes | 2 / 1 | 1 |
| R0.6 | R0.0:L235 | yes | 36 / 13 | 36 |
| R0.7 | R0.0:L3898 | yes | 10 / 5 | 5 |
| R0.8 | R0.0:L584 | yes | 10 / 3 | 8 |
| R0.9 | R0.0:L447 | yes | 33 / 4 | 41 |
| R0.10 | R0.0:L1728 | yes | 3 / 1 | 5 |
| R0.11 | R0.0:L1949 | yes | 13 / 2 | 19 |
| R0.12 | R0.0:L2617 | yes | 18 / 4 | 25 |
| R0.13 | R0.0:L276 | yes | 2 / 1 | 1 |
| R0.14 | R0.0:L404 | yes | 33 / 2 | 36 |
| R0.15 | R0.0:L1649 | yes | 7 / 1 | 7 |
| R0.16 | R0.0:L1697 | yes | 4 / 1 | 7 |
| R0.17 | R0.0:L1897 | yes | 21 / 2 | 14 |
| R0.18 | R0.0:L4056 | yes | 2 / 1 | 2 |
| R0.19 | R0.0:L2488 | yes | 34 / 6 | 25 |
| R0.20 | R0.0:L4168 | yes | 2 / 1 | 3 |
| R0.21 | R0.1:L38 | yes | 38 / 11 | 33 |
| R0.22 | R0.1:L55 | yes | 2 / 1 | 2 |
| R0.23 | R0.1:L136 | yes | 2 / 1 | 2 |
| R0.24 | R0.1:L226 | yes | 14 / 4 | 11 |
| R0.25 | R0.1:L940 | yes | 6 / 3 | 6 |
| R0.26 | R0.1:L1136 | yes | 2 / 1 | 2 |
| R0.27 | R0.3:L24 | yes | 14 / 4 | 4 |
| R0.28 | R0.8:L54 | yes | 4 / 2 | 3 |
| R0.29 | R0.8:L60 | yes | 2 / 1 | 1 |
| R0.30 | R0.8:L66 | yes | 2 / 1 | 2 |
| R0.31 | R0.8:L272 | yes | 2 / 1 | 2 |
| R0.32 | R0.8:L393 | yes | 2 / 1 | 1 |
| R0.33 | R0.8:L36 | yes | 22 / 6 | 7 |

All 33 children have a nonempty final `task_complete.last_agent_message`. Across these edges the callers contain **364 child-authored message rows**, all with a string `recipient` and adjacent `inter_agent_communication_metadata.trigger_turn`; none has a payload `turn_id`. Exact recipient-to-parent-path comparisons produced zero matches, and no parent communication exactly matched the child’s final completion text in the comparison performed. Thus a child-origin communication can be associated with the agent, but a unique final-result delivery to its parent is not established by those fields alone.

A concrete return example is `R0.1:L1270`: its final completion body was readable and reported likely causes plus a bounded correction with completeness checks (high-level sanitised paraphrase). The corresponding initial assignment is opaque at `R0.0:L636`, with spawn output at `R0.0:L639`; child-origin communications appear in the root from `R0.0:L726` through `R0.0:L2255`. These establish agent association, not an exact identity between that final body and one delivered parent message.

| Child | Caller / assignment → spawn output lines | Child final-completion line | Caller first / last child-origin message lines |
|---|---|---|---|
| R0.1 | R0.0:L636 → L639 | R0.1:L1270 | L726 / L2255 |
| R0.2 | R0.0:L2771 → L2774 | R0.2:L308 | L2804 / L3667 |
| R0.3 | R0.0:L22 → L25 | R0.3:L339 | L50 / L442 |
| R0.4 | R0.0:L16 → L19 | R0.4:L362 | L28 / L311 |
| R0.5 | R0.0:L86 → L89 | R0.5:L113 | L116 / L116 |
| R0.6 | R0.0:L235 → L238 | R0.6:L1641 | L273 / L3706 |
| R0.7 | R0.0:L3898 → L3901 | R0.7:L263 | L3915 / L4141 |
| R0.8 | R0.0:L584 → L587 | R0.8:L473 | L618 / L1491 |
| R0.9 | R0.0:L447 → L450 | R0.9:L1800 | L461 / L1597 |
| R0.10 | R0.0:L1728 → L1731 | R0.10:L321 | L1740 / L1851 |
| R0.11 | R0.0:L1949 → L1952 | R0.11:L908 | L1961 / L2354 |
| R0.12 | R0.0:L2617 → L2620 | R0.12:L885 | L2629 / L3863 |
| R0.13 | R0.0:L276 → L279 | R0.13:L103 | L342 / L342 |
| R0.14 | R0.0:L404 → L407 | R0.14:L1956 | L423 / L1636 |
| R0.15 | R0.0:L1649 → L1652 | R0.15:L529 | L1666 / L1869 |
| R0.16 | R0.0:L1697 → L1700 | R0.16:L453 | L1738 / L1817 |
| R0.17 | R0.0:L1897 → L1900 | R0.17:L1319 | L1984 / L2454 |
| R0.18 | R0.0:L4056 → L4059 | R0.18:L125 | L4076 / L4082 |
| R0.19 | R0.0:L2488 → L2491 | R0.19:L759 | L2500 / L3776 |
| R0.20 | R0.0:L4168 → L4171 | R0.20:L131 | L4197 / L4213 |
| R0.21 | R0.1:L38 → L41 | R0.21:L445 | L52 / L1263 |
| R0.22 | R0.1:L55 → L58 | R0.22:L107 | L91 / L101 |
| R0.23 | R0.1:L136 → L139 | R0.23:L105 | L159 / L165 |
| R0.24 | R0.1:L226 → L229 | R0.24:L594 | L286 / L913 |
| R0.25 | R0.1:L940 → L943 | R0.25:L225 | L985 / L1174 |
| R0.26 | R0.1:L1136 → L1139 | R0.26:L208 | L1215 / L1225 |
| R0.27 | R0.3:L24 → L27 | R0.27:L86 | L54 / L325 |
| R0.28 | R0.8:L54 → L57 | R0.28:L123 | L88 / L218 |
| R0.29 | R0.8:L60 → L63 | R0.29:L107 | L94 / L94 |
| R0.30 | R0.8:L66 → L69 | R0.30:L186 | L144 / L161 |
| R0.31 | R0.8:L272 → L275 | R0.31:L120 | L291 / L301 |
| R0.32 | R0.8:L393 → L396 | R0.32:L131 | L415 / L415 |
| R0.33 | R0.8:L36 → L39 | R0.33:L139 | L51 / L459 |

R0’s activity and usage are quantified per node below. Outer-record counts include context copies. Calls are exact call/output operations and have no inherited prefix copies in this sample. Tasks/duration use **post-boundary** completion records (root: all its own completions); these total the same 119 unique turn IDs after exact-copy checks. Responses count unique modern response IDs, and tokens sum `usage.total_tokens`. Zero calls can coexist with messages/reasoning. Full task wall time, billing and result correctness are not inferred.

| Agent | Outer records | Tool operations | Own completed turns | Own duration sum (ms) | Modern responses | Recorded modern total tokens |
|---|---|---|---|---|---|---|
| R0.0 | 4,261 | 432 | 14 | 11,180,457 | 450 | 49,562,380 |
| R0.1 | 1,270 | 127 | 8 | 1,190,337 | 135 | 9,622,428 |
| R0.2 | 308 | 36 | 6 | 488,152 | 42 | 3,361,376 |
| R0.3 | 339 | 37 | 2 | 837,733 | 39 | 1,678,342 |
| R0.4 | 362 | 41 | 3 | 299,120 | 44 | 3,545,024 |
| R0.5 | 113 | 12 | 1 | 67,302 | 13 | 739,337 |
| R0.6 | 1,641 | 192 | 13 | 1,432,766 | 207 | 22,068,229 |
| R0.7 | 263 | 22 | 5 | 237,660 | 27 | 2,319,616 |
| R0.8 | 474 | 52 | 3 | 669,955 | 55 | 2,765,931 |
| R0.9 | 1,800 | 216 | 4 | 2,852,977 | 221 | 19,034,567 |
| R0.10 | 321 | 35 | 1 | 486,659 | 36 | 1,922,464 |
| R0.11 | 908 | 109 | 3 | 899,120 | 112 | 11,626,405 |
| R0.12 | 885 | 117 | 4 | 2,291,442 | 121 | 12,390,957 |
| R0.13 | 103 | 9 | 1 | 90,004 | 10 | 434,638 |
| R0.14 | 1,956 | 241 | 2 | 3,158,427 | 244 | 23,581,792 |
| R0.15 | 530 | 63 | 1 | 844,762 | 64 | 4,959,171 |
| R0.16 | 453 | 50 | 1 | 448,132 | 51 | 3,425,022 |
| R0.17 | 1,320 | 155 | 2 | 91,565 | 158 | 15,468,433 |
| R0.18 | 125 | 8 | 1 | 61,543 | 9 | 544,318 |
| R0.19 | 759 | 74 | 6 | 2,340,199 | 80 | 9,499,870 |
| R0.20 | 131 | 9 | 1 | 89,971 | 10 | 486,522 |
| R0.21 | 445 | 37 | 11 | 1,026,174 | 48 | 2,569,385 |
| R0.22 | 107 | 9 | 1 | 44,118 | 10 | 537,180 |
| R0.23 | 105 | 9 | 1 | 41,143 | 10 | 508,072 |
| R0.24 | 594 | 63 | 4 | 586,969 | 68 | 6,727,993 |
| R0.25 | 225 | 18 | 3 | 124,675 | 21 | 1,413,332 |
| R0.26 | 208 | 18 | 1 | 90,694 | 19 | 1,068,224 |
| R0.27 | 86 | 0 | 4 | 155,184 | 4 | 173,045 |
| R0.28 | 123 | 9 | 2 | 76,299 | 11 | 616,565 |
| R0.29 | 107 | 9 | 1 | 48,306 | 10 | 439,029 |
| R0.30 | 186 | 20 | 1 | 162,187 | 21 | 1,418,945 |
| R0.31 | 120 | 10 | 1 | 52,719 | 11 | 546,831 |
| R0.32 | 131 | 10 | 1 | 61,029 | 11 | 687,486 |
| R0.33 | 139 | 2 | 6 | 105,006 | 8 | 349,205 |

### Quantified grouping of this recorded tree

These are arithmetic reductions in a compact representation of the evidence, not proposed product behaviour or deletions of source evidence. Grouped records retain their constituent timing, inputs and outputs.

| R0 grouping | Source rows | Groups | Rows no longer separate | Meaning / information retained |
|---|---|---|---|---|
| Function call + its output | 2,284 | 1,142 | 1,142 | Exact thread/family/call-ID pairs. |
| Custom call + its output | 2,218 | 1,109 | 1,109 | Exact thread/family/call-ID pairs. |
| Direct-parent child lifecycle references | 420 | 33 | 387 | One group per available parent→child edge; retain all started/interacted/completed/interrupted entries inside it. This is aggregation, not duplicate removal. |
| One response item + its same-ID completion telemetry | 5,730 | 2,865 | 2,865 | Exact one-to-one reasoning/message ID pairs. Preserve telemetry fields; no tool calls occur among these shared IDs. |

The four rows are disjoint in this sample: none of R0’s 2,865 same-ID completion rows also references a direct child, and none is a tool call/output. Together **10,652 source rows → 5,149 groups**, eliminating **5,503 separate rows** from the presentation. Separately, consolidating the 70 exact copied task-completion rows removes 70 repeated observations; those records are outside the four groups above. An additional **778 directional metadata→following-agent-message bundles** would represent 1,556 rows as 778 bundles, eliminating 778 separate rows; this uses the measured nonoverlapping direction, not ambiguous either-neighbour matching or proven ID-based duplication. Their record families are disjoint from the four groups, so including that option gives **6,281 fewer separate rows**, or **6,351** when the 70 exact task copies are also consolidated. No grouping recovers encrypted content or makes differing record families equivalent actions.

## 7. Reconstruction boundaries and verification

The reliable reconstruction is a parent-linked tree with explicit spawn instruction locations, paired calls/results, response and lifecycle ID joins, task endpoints where present, and recorded response-usage totals. It does **not** recover encrypted reasoning, absent logs, hidden tool work inside an opaque call, unrecorded message deliveries, semantic success, CPU time, billed cost, or a complete causal explanation of inherited context. Event counts do not become action counts without specifying the join and unit.

Verification of this document consists of inventory-sum checks, per-tree/per-agent rollups, exact-ID multiplicity checks, modern-response uniqueness and total reconciliation, review against the cited parser surfaces, and a privacy/diff review. Temporary analysis scripts and sanitised evidence packets were kept outside tracked files; only this report is intended for the commit. No private session content is included.

Existing tests provide additional source context, without being rerun or treated as new empirical log evidence: [tests/test_session_inspect.py:79](../tests/test_session_inspect.py#L79) covers pairing/orphans/ambiguity; [tests/test_session_inspect.py:103](../tests/test_session_inspect.py#L103) covers reasoning availability; [tests/test_session_inspect.py:131](../tests/test_session_inspect.py#L131) and [tests/test_session_inspect.py:149](../tests/test_session_inspect.py#L149) cover lazy large outputs and mutated sources. [tests/test_session_analysis.py:66](../tests/test_session_analysis.py#L66), [tests/test_session_analysis.py:89](../tests/test_session_analysis.py#L89), [tests/test_session_analysis.py:114](../tests/test_session_analysis.py#L114) and [tests/test_session_analysis.py:152](../tests/test_session_analysis.py#L152) cover rollups, dual-family response deduplication, inherited-prefix exclusion and missing children. The measurements above come from real logs, not synthetic test fixtures.
