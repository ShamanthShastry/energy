"""Ledger operations used by the weekly job and by CMP-15 (step 7).

TRS-17-06: at the end of each week every action of that week still proposed becomes dismissed
with reason 'expired' and actor 'week_close'. close_ended_weeks runs it for every week before
the one containing `now` (household local time). propose_actions also runs it before issuing a
new week, so no proposal can outlive its week even if the weekly job did not run."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from homewatt.cmp13_simulator.simulator import iso_week_id, previous_week_ids


def close_ended_weeks(client, household_id: str, now: datetime, tz: str) -> str:
    """Close every week that ended before `now`. Returns the last closed week_id."""
    current = iso_week_id(pd.Timestamp(now), tz)
    through = previous_week_ids(current, 1)[0]
    client.call("close_week", household_id, through)
    return through


def dismiss(client, action_id: str) -> None:
    """Dismiss button (TRS-16-11): proposed -> dismissed, reason 'user', actor 'user'."""
    client.call("dismiss_action", action_id)


def accept(client, action_id: str) -> None:
    """Ledger half of Take action: proposed -> accepted, actor 'user'."""
    client.call("accept_action", action_id)


def read_transitions(client, action_id: str) -> pd.DataFrame:
    df = client.sql(f"SELECT * FROM action_transition WHERE action_id = '{action_id}'")
    return df.sort_values("at_us").reset_index(drop=True) if len(df) else df
