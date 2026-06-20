# Known Issues

Deferred items found during the hardening sweep. These should be transferred to
GitHub Issues (the `gh` CLI was unavailable in the working environment, so they
are tracked here in the meantime). Each notes why it was deferred rather than
fixed inline.

## Open

### 1. Partial take-profit is not persisted (correctness bug)
`scheduler/jobs.py` `position_check_job`, on `take_profit_partial`, sells 75% and
mutates `pos["shares"]` / `pos["size"]` **in memory only** — there is no DB write.
On the next position check, `get_open_positions()` reloads the original full share
count from SQLite, so the remaining 25% is mis-valued and the partial sell can be
re-triggered. The position also never transitions out of the partial state.

**Fix sketch:** add an `update_position(id, shares, size)` helper in
`db/models.py` and call it after the partial sell; consider a `partial_tp_done`
flag so it fires once. Needs its own tests.

**Why deferred:** it's a real bug, not a cleanup — touches DB schema/helpers and
the live exit path, so it warrants a focused change + tests rather than riding
along on a sweep commit. The `0.75` / `0.25` split literals at
`jobs.py:343-349` should become named constants (or config) as part of that fix.

### 2. `pnl < 50000` fallback in `filter_whales` is an unnamed threshold
`whale/monitor.py:56` admits a whale on big absolute PnL even when `pnl_margin`
is thin, using a bare `50000`. It mixes an unnamed literal with the named
`WHALE_MIN_PNL_MARGIN` gate.

**Fix sketch:** promote to `WHALE_BIG_PNL_OVERRIDE` in `config.py` +
`.env.example`.

**Why deferred:** pre-existing behavior, purely cosmetic; no functional change.

## Resolved in the sweep
- `jobs.py` hardcoded `bankroll * 0.10` per-trade cap now uses `MAX_BET_PCT`
  (it silently ignored a more-conservative configured cap). Fixed.
