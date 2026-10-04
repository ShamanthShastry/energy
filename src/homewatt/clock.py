"""Demo-aware "now" (§4.2). The replayed demo runs on the timeline's clock, stored in the
sim_clock table by the demo driver; without a row the wall clock is used."""

from __future__ import annotations

import pandas as pd


def now(client, household_id: str) -> pd.Timestamp:
    df = client.sql(f"SELECT now_us FROM sim_clock WHERE household_id = '{household_id}'")
    if len(df):
        return pd.Timestamp(int(df.iloc[0]["now_us"]), unit="us", tz="UTC")
    return pd.Timestamp.now(tz="UTC").floor("s")


def is_simulated(client, household_id: str) -> bool:
    return len(client.sql(f"SELECT now_us FROM sim_clock WHERE household_id = '{household_id}'")) > 0


def set_now(client, household_id: str, ts) -> None:
    from homewatt.spacetime import us

    client.call("set_sim_clock", household_id, us(ts))
