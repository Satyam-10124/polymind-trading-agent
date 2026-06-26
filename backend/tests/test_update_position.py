"""
Persistence of partial take-profit state.

Regression guard for the bug where a partial TP sold 75% but only mutated the
position dict in memory — get_open_positions() then reloaded the original full
share count from SQLite, so the partial re-triggered and the remaining 25% was
mis-valued. update_position() must persist the reduced shares/size AND a
partial_tp_done flag that survives the reload.
"""
import db.models as models


def _seed_position(pos_id="p1", shares=100.0, size=40.0):
    models.save_position({
        "id": pos_id,
        "question": "Will X happen?",
        "market_id": "m1",
        "token_id": "tok-1",
        "direction": "YES",
        "entry_price": 0.40,
        "size": size,
        "shares": shares,
    })


def test_update_position_persists_reduced_shares(temp_db):
    _seed_position()
    # Sell 75%: 100 -> 25 shares, size re-based at entry price.
    models.update_position("p1", shares=25.0, size=25.0 * 0.40,
                           partial_tp_done=True)

    pos = models.get_open_positions()[0]
    assert pos["shares"] == 25.0
    assert pos["size"] == 10.0
    assert int(pos["partial_tp_done"]) == 1


def test_partial_flag_survives_reload(temp_db):
    # The whole point: the flag is read back from SQLite, not held in memory.
    _seed_position(pos_id="p2")
    models.update_position("p2", shares=25.0, size=10.0, partial_tp_done=True)

    reloaded = {p["id"]: p for p in models.get_open_positions()}
    assert int(reloaded["p2"]["partial_tp_done"]) == 1


def test_update_without_flag_leaves_flag_untouched(temp_db):
    # Calling update_position without partial_tp_done must not clobber it.
    _seed_position(pos_id="p3")
    models.update_position("p3", shares=25.0, size=10.0, partial_tp_done=True)
    # A later size-only correction (flag omitted) keeps the flag set.
    models.update_position("p3", shares=25.0, size=9.5)

    pos = {p["id"]: p for p in models.get_open_positions()}["p3"]
    assert pos["size"] == 9.5
    assert int(pos["partial_tp_done"]) == 1
