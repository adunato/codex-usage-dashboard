# Session analysis validation

Validated on Windows with Python 3.12 and Node.js 24.

- `python -m unittest discover -s tests -v`: 86 tests run, 85 passed, one skipped because this account cannot create Windows symlinks. No failures or errors.
- `python -m compileall -q scripts tests skills`: passed.
- `npm run validate`: passed.
- `git diff --check`: passed.
- Extracted browser JavaScript: `node --check` passed. Independent review found no unresolved substantive defects after corrections.

## Automated browser demonstration

Headless Microsoft Edge exercised the served application with a synthetic four-agent conversation. Usage reconciled to 43,000 tokens: Main 17,000, two Explorers 13,500 combined, Worker Sol 12,500. Model rows reconciled to 29,500 and 13,500. Role expansion preserved distinct Explorer instances. Inspect filtered by agent/category, expanded a recorded message, and loaded a tool call with its paired result. Deliberately hostile HTML remained plain text; no browser runtime errors occurred. The UI was also visually inspected.

The existing launcher started the redesigned app on localhost. A local scan found 53 root conversations, 11 with multiple agents. A historical conversation with 59 threads was exercised through Usage and Inspect, including agent filtering, original message/tool content and paired results. SHA-256 checks of all 59 original source files were unchanged before and after browsing. No private transcripts, source identifiers or source paths are committed.

The selected historical conversation shows Incomplete with a usage-overlap explanation because the recorded modern and legacy cumulative counters disagree. Its role and model totals reconcile to the same known amount. The app does not assert that the unresolved counters represent additional consumption.

The npm installer was run with a temporary Codex home. All sibling modules were copied and the installed CLI successfully scanned the synthetic four-thread fixture. The user's installed skill was not replaced.

## Coverage and limitations

New tests cover per-model contributions, overlapping token families, inherited prefixes, same-role instances, unknown metadata, missing root/parent/child files, remote summary-only sessions, repeated resumed sources, malformed counters, source positions, API snapshot consistency, unknown/encrypted events, interleaved tool IDs, bounded lazy content and source replacement. Legacy accounting/cache/launcher/API regressions remain covered.

Review corrections included preserving undated known usage, validating all cumulative components and aggregate arithmetic, retaining summary-only imports, labeling same-role instances distinctly, handling absent parents, positive Inspect API integration, and invalidating stale UI data on HTTP 409. Preexisting Windows fixes cover SQLite file identities, CRLF fast parsing, deterministic byte fixtures and test connection closure.

No archived local rollout was available for a real-log demonstration; archived discovery is covered by synthetic fixtures. The symlink creation test remains unexecuted on this host because of Windows privileges; containment checks and source mutation/replacement tests pass. Large expanded records are visibly bounded at 200,000 characters. Unsupported or conflicting accounting remains explicitly Incomplete.

No additional manual validation is required.
