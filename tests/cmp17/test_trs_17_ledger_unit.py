import pandas as pd

from homewatt.cmp13_simulator.simulator import (
    active_suppressions,
    iso_week_id,
    suppressed_action_types,
)
from tests.conftest import REPO

INDEX = (REPO / "spacetimedb" / "src" / "index.ts").read_text()


def test_week_id_uses_household_local_time():
    # Monday 2025-07-14 02:00 UTC is still Sunday 22:00 in Detroit: week 28, not 29.
    ts = pd.Timestamp("2025-07-14T02:00:00Z")
    assert iso_week_id(ts) == "2025-W29"
    assert iso_week_id(ts, "America/Detroit") == "2025-W28"


def test_trs_13_10_suppression_lasts_its_full_four_weeks():
    recs = [("trim_standby", "2025-W29", "2025-W32")]
    assert all("trim_standby" in active_suppressions(recs, w) for w in ("2025-W29", "2025-W30", "2025-W31", "2025-W32"))
    assert "trim_standby" not in active_suppressions(recs, "2025-W33")


def test_trs_13_10_expired_weeks_count_as_dismissals():
    # Not taken three weeks running (expired) is the same signal as three user dismissals.
    sup = suppressed_action_types({"trim_standby": ["2025-W26", "2025-W27", "2025-W28"]}, "2025-W29")
    assert sup == {"trim_standby": ("2025-W29", "2025-W32")}


def test_trs_17_06_week_close_and_user_transitions_exist_and_are_logged():
    assert "export const closeWeek" in INDEX and "export const dismissAction" in INDEX and "export const acceptAction" in INDEX
    assert "statusReason: 'expired'" in INDEX and "'week_close', 'expired'" in INDEX
    assert "userTransition(ctx, actionId, 'dismissed', 'user')" in INDEX
    # propose_actions closes earlier weeks before issuing, so no proposal outlives its week
    body = INDEX.split("export const proposeActions")[1].split("export const closeWeek")[0]
    assert "closeOpenProposals(ctx, householdId, w => w < weekId);" in body


def test_trs_13_08_batch_is_not_superseded_within_a_week():
    body = INDEX.split("export const proposeActions")[1].split("export const closeWeek")[0]
    assert "superseded" not in body
    assert "members >= MAX_ACTIONS" in body


def test_trs_17_01_no_reducer_deletes_ledger_rows():
    assert "ctx.db.action.id.delete" not in INDEX and "ctx.db.actionTransition.id.delete" not in INDEX
