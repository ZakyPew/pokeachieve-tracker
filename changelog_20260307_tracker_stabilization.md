# PokeAchieve Tracker Stabilization Log (2026-03-07)

This log summarizes the work completed to stabilize and improve core tracker functionality for:
- Pokedex and collection sync
- Achievement loading/unlock reporting
- Party detection, logging, and party-to-platform sync

## Scope

Primary files:
- `tracker_gui.py`
- `scripts/validate_reporting.py`
- `game_configs.py` (configuration support updates used by tracker logic)

## 1) RetroArch Connection and Polling Stability

- Added explicit offline/online state messages:
  - `retroarch_closed_waiting` with status `RetroArch Closed, waiting on RetroArch launch`
  - `retroarch_reconnected` with downtime timing
- Reduced noisy repeated socket error output when RetroArch is closed.
- Added polling wait-state reporting while disconnected.
- Preserved smooth resume behavior when RetroArch reconnects.

## 2) API and Authentication Behavior

- Removed unnecessary calls to `/api/users/me/achievements` when API key auth is active.
  - This eliminated repeated `401 Invalid authentication credentials` errors in tracker runs.
- Improved unlock/progress reconciliation with catalog-backed name augmentation.
- Kept unlock/report requests retry-safe while avoiding non-retryable API spam.

## 3) Pokedex and Collection Sync

- Stabilized baseline initialization:
  - When catches are ready but party is not yet stable, baseline sync is deferred.
  - Deferred baseline flushes once party becomes available (`party_sync_deferred` + `collection_baseline_sync_flushed`).
- Improved startup behavior to prevent false sync noise during first polls.
- Preserved and validated batch catch sync (`/api/collection/batch-update`).

## 4) Party Memory Parsing and Gen 3 Reliability

- Reworked Gen 3 party decode and validation pipeline for Emerald/RS/FRLG:
  - Corrected and hardened party base/stride candidate handling.
  - Added canonical Gen 3 encrypted substructure order usage.
  - Added checksum-aware decode validation.
  - Added internal-species to National Dex normalization.
- Improved party read transport reliability:
  - Better command/response matching for UDP command stream.
  - Chunked large memory reads to avoid UDP buffer overflow (`WinError 10040`).
- Added decode-budget observability (`gen3_party_decode_budget_hit`) and controlled fallbacks.

## 5) Party Change Safety (False-Drop Prevention)

- Added incomplete-read guard for party reductions:
  - A detected party drop with incomplete decode is held for confirmation.
  - Drop is only applied after a matching follow-up read (`party_drop_confirmed_after_retry`).
- This avoids accidental one-poll party shrink artifacts from noisy memory reads.

## 6) Tracker Log Readability and Formatting

- Standardized tracker log level prefixes to plain ASCII labels:
  - `INFO`, `OK`, `WARN`, `ERROR`, `UNLOCK`, `API`, `COLLECTION`, `PARTY`
- Added readable per-slot party output in tracker log:
  - `PARTY: SLOT 1: Lv.31 Combusken`
- Added party delta action logging:
  - `PARTY: Lv.3 Zigzagoon deposited into PC`
  - `PARTY: Lv.3 Zigzagoon withdrawn from PC`
- Added catch-to-party messaging for newly added party mons when not classified as PC action:
  - `PARTY: Lv.4 Zigzagoon was caught!`
  - `PARTY: Lv.4 Zigzagoon was added to the party.`
- Suppressed false PC-withdraw messages on startup baseline formation.
- Removed mojibake/non-ASCII icon issues in tracker panel output.

## 7) Validation and Test Coverage

- Expanded regression coverage in `scripts/validate_reporting.py` for:
  - baseline defer/flush behavior
  - party drop confirmation logic
  - Gen 3 party decode/recovery edge cases
  - unlock/progress reconciliation paths
- Validation status at snapshot:
  - `py_compile` passes
  - `scripts/validate_reporting.py` passes (`36/36`)

## 8) Snapshot Baselines

The following snapshot checkpoints were created during stabilization:
- `6f3cc51` - stable tracker baseline (fast startup + clean logs)
- `fa3f23a` - clean RetroArch offline logging baseline
- `bf6f87c` - stabilize party tracking and tracker log formatting

This PR carries these stabilized changes plus this written log for review.
