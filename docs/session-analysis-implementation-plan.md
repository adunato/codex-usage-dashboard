# Implementation Plan: Session analysis

## 1. Implementation Summary

Implement the approved Sessions → Usage → Inspect workflow using the existing scanner, parser, fork normalization, snapshot publication and standard-library HTTP server. Extend the canonical usage pipeline and add root-conversation aggregates. Keep event inspection lazy in a small sibling module and serve a new English UI from a second sibling module. Existing launcher, installer and legacy JSON endpoints remain compatible.

## 2. HLD Reference

The approved functional design is [session-analysis-design.md](session-analysis-design.md). Usage and Inspect ship together. Counters reconcile by role, distinct agent and effective model; incomplete data remains visible with explicit reasons. Events are recorded source material, never generated interpretation. Cached input and reasoning output are subsets, not additional total tokens. Pricing, charts and qualitative evaluation are outside this change.

## 3. Repository Assessment

Evidence: `session-analysis-2026-10-16-v1`, inspected revision `41d86e7`. Main supplied the isolated `codex/session-analysis` worktree. The unrelated primary-checkout cache identity change is protected.

The monolith already discovers active/archived logs, tracks parent metadata and event models, normalizes inherited fork counters, publishes snapshot tokens, and supports local/remote summaries. Its list reader deliberately projects away large payloads. Its latest-model summary is unsuitable for new model attribution. Actual recent logs also contain `token_usage_record`; deduplication must treat both usage record families as overlapping observations. The snapshot/event/HTTP contracts are detailed in [session-analysis-lld.md](session-analysis-lld.md).

## 4. Implementation Approach

### 4.1 Canonical usage and root grouping

Extend the existing reader with opt-in full records and source positions, preserving default projection/cache behavior. Extend parser output with usage provenance, accounting warnings and recorded child references. Normalize both cumulative usage families into one timeline, deduplicate, apply existing inherited-usage normalization and then derive model-at-event deltas. Group environment-scoped thread identities by recorded ancestry; retain distinct instances with the same role. Add root summaries and usage indexes to published snapshots without exposing internal source descriptors.

### 4.2 Inspect inventory and original record retrieval

Add `session_inspect.py`, receiving the shared reader as a callback. Scan only a selected root's local source files, retain compact event metadata and byte locations, classify all record types, pair tool records by IDs within their thread, and expose inventory plus filtered/paginated events. Expand an event by reading its original record on demand. Validate source identity and constrain reads to discovered local sources. Remote-only histories return an explicit unavailable state.

### 4.3 English browser workflow

Add `session_analysis_ui.py` with an HTML string and no external dependencies. Sessions supports search and date/token sorting; Usage presents totals, expandable role/agent rows and models; Inspect shows inventory, filters, source positions and lazy expansions. All log-controlled text uses text nodes or escaping. Loading, empty, missing/encrypted, stale snapshot and truncated-output states are explicit.

### 4.4 Integration and documentation

The core worker owns the monolith and API routing. Inspect and UI workers own separate modules. Main owns README and any installer adjustment; the installer recursively copies the skill tree, so sibling modules require no structural installer change. Direct script execution and importlib-based tests must both locate sibling modules. Retain old JSON APIs and launcher health behavior. The replacement browser UI need not preserve the old visual layout.

## 5. Implementation Sequence

1. Freeze the shared contracts in the LLD and worker handoffs.
2. Implement shared reader changes, canonical accounting and snapshot root indexes in the core worker. Inspect and UI modules can develop independently against the contract.
3. Connect the new routes, source descriptors and UI HTML; invalidate old persistent parser caches if the stored parser schema changes.
4. Run focused arithmetic, identity, source, security and API tests. Resolve substantive failures through Main.
5. Run existing regressions, installer validation and a browser smoke test using synthetic fixtures followed by local-log read-only validation. Update README with actual supported formats and limitations.

## 6. Development Integrity Checks

- `python -m py_compile` for modified/new Python modules.
- `python -m unittest discover -s tests -v`.
- `npm run validate`.
- Browser JavaScript syntax/runtime smoke through the served UI; check HTTP errors and console errors when tooling permits.

## 7. Validation Requirements

Unit/integration checks must prove reconciliation across every counter, no addition of subsets, model switching, same-role distinct agents, inherited-prefix subtraction, both overlapping token families, response-ID duplicates, resumed/archived discovery and unknown attribution. Warnings must distinguish missing sources, malformed records, unresolved inherited/dedup coverage and inconsistent totals.

Inspect checks cover physical source line/offset references, all categories and unknown raw types, timestamp ordering with stable ties, ID-based interleaved call/result matching, missing results, readable/encrypted/unavailable reasoning, lazy full-payload expansion, explicit truncation, escaped hostile content, invalid IDs, path traversal rejection and source mutation/stale snapshots. Remote-only summaries must remain selectable and explain unavailable originals.

Browser acceptance: open a root with multiple agents, reconcile Usage, expand a role, filter Inspect by instance/category, expand a message and a paired tool record or explicit unavailable state, and navigate back without losing the selected root. Local originals must remain unchanged. Launcher and installed skill execution must still work.

## 8. Open Implementation Questions

No user decision is required. Fixed-byte local inspection confirmed that modern response usage usually matches the following legacy contribution, while some cumulative vectors disagree by unresolved offsets. The implementation uses one canonical authority and marks those mismatches Incomplete. Unsupported schemas remain visible rather than guessed.

## 9. Low-Level Design Decision

**LLD required: Yes.** The new canonical accounting, snapshot identities, private source descriptors, Inspect callbacks and browser API share contracts across separate implementation surfaces. The companion LLD fixes those interfaces and edge behavior before parallel implementation.

## 10. Implementation Checklist

- [x] Extend shared JSONL reader and canonical accounting.
- [x] Publish grouped root/role/agent/model analysis and source descriptors.
- [x] Implement lazy Inspect inventory/details and API integration.
- [x] Implement Sessions, Usage and Inspect browser screens.
- [x] Update README and verify installed launcher.
- [x] Complete focused and regression checks, local-log demonstration and change handoff.

