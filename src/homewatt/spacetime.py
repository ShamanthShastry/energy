"""SpacetimeDB client for server-side Python components (TRS-SYS-06 data store after v0.3).

Two operations only:
  call(reducer, *args)  -> POST /v1/database/{db}/call/{reducer} with a JSON argument array
  sql(query)            -> POST /v1/database/{db}/sql, decoded into a DataFrame

Auth is the owner token: HOMEWATT_SPACETIME_TOKEN, else `spacetime login show --token`.
Only the owner may call write reducers (module `requireOwner`), which is how TRS-05-05 and
TRS-15-06 are enforced in V1: components share the owner identity; the dashboard never has it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_HOST = "https://maincloud.spacetimedb.com"


class SpacetimeError(RuntimeError):
    pass


class SpacetimeUnavailable(SpacetimeError):
    """Network or 5xx: the caller may buffer and retry (CMP-05 error handling)."""


@lru_cache(maxsize=1)
def cli_token() -> str:
    out = subprocess.run(["spacetime", "login", "show", "--token"], capture_output=True, text=True, check=True).stdout
    m = re.search(r"token[^\n]*?:\s*(\S+)", out, re.I) or re.search(r"\b(ey[A-Za-z0-9_\-\.]+)\b", out)
    if not m:
        raise SpacetimeError("could not read a token from `spacetime login show --token`")
    return m.group(1)


def _json_default(o: Any):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o)}")


@dataclass
class SpacetimeClient:
    database: str
    host: str = DEFAULT_HOST
    token: str | None = None
    timeout: float = 60.0

    def __post_init__(self):
        self.token = self.token or os.environ.get("HOMEWATT_SPACETIME_TOKEN") or cli_token()
        self._http = httpx.Client(
            base_url=f"{self.host.rstrip('/')}/v1/database/{self.database}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=self.timeout,
        )

    @classmethod
    def from_settings(cls) -> SpacetimeClient:
        from homewatt.config import get_settings

        s = get_settings()
        return cls(database=s.spacetime_database, host=s.spacetime_host)

    # ---- reducers
    def call(self, reducer: str, *args: Any) -> None:
        body = json.dumps(list(args), default=_json_default)
        try:
            r = self._http.post(f"/call/{reducer}", content=body, headers={"content-type": "application/json"})
        except httpx.HTTPError as e:
            raise SpacetimeUnavailable(str(e)) from e
        if r.status_code >= 500:
            raise SpacetimeUnavailable(f"{reducer}: HTTP {r.status_code} {r.text[:300]}")
        if r.status_code >= 400:
            raise SpacetimeError(f"{reducer}: HTTP {r.status_code} {r.text[:500]}")

    # ---- SQL
    def sql_raw(self, query: str) -> list[dict]:
        try:
            r = self._http.post("/sql", content=query, headers={"content-type": "text/plain"})
        except httpx.HTTPError as e:
            raise SpacetimeUnavailable(str(e)) from e
        if r.status_code >= 500:
            raise SpacetimeUnavailable(f"sql: HTTP {r.status_code} {r.text[:300]}")
        if r.status_code >= 400:
            raise SpacetimeError(f"sql: HTTP {r.status_code} {r.text[:500]}")
        return r.json()

    def sql(self, query: str) -> pd.DataFrame:
        """Run one statement and return a DataFrame with the schema's column names."""
        results = self.sql_raw(query)
        if not results:
            return pd.DataFrame()
        res = results[0]
        elems = res["schema"]["elements"]
        cols = [_elem_name(e, i) for i, e in enumerate(elems)]
        types = [e["algebraic_type"] for e in elems]
        rows = [[_decode(v, ty) for v, ty in zip(row, types, strict=True)] for row in res["rows"]]
        return pd.DataFrame(rows, columns=cols)

    def close(self) -> None:
        self._http.close()


def _elem_name(e: dict, i: int) -> str:
    n = e.get("name")
    if isinstance(n, dict):
        n = n.get("some")
    return n or f"col{i}"


def _decode(v: Any, ty: dict | None = None) -> Any:
    """SATS-JSON values. Products come back positional (lists); the schema says what they are.
    Special products (Timestamp, Identity, ...) have one element named `__xxx__`."""
    if ty and "Product" in ty:
        elems = ty["Product"]["elements"]
        if len(elems) == 1 and str(_elem_name(elems[0], 0)).startswith("__"):
            inner = v[0] if isinstance(v, list) else v
            return _decode(inner, elems[0]["algebraic_type"])
        if isinstance(v, list):
            return {_elem_name(e, i): _decode(x, e["algebraic_type"]) for i, (e, x) in enumerate(zip(elems, v, strict=True))}
    if ty and "Sum" in ty and isinstance(v, dict):  # option / enum
        if "some" in v:
            return _decode(v["some"], ty["Sum"]["variants"][0]["algebraic_type"])
        if "none" in v:
            return None
    if ty and "Array" in ty and isinstance(v, list):
        return [_decode(x, ty["Array"]) for x in v]
    return v


_EPOCH = pd.Timestamp("1970-01-01T00:00:00Z")


def us(ts) -> int:
    """UTC timestamp -> microseconds since the epoch (int). Exact integer arithmetic."""
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return int((t - _EPOCH) // pd.Timedelta(microseconds=1))


def us_array(ts) -> np.ndarray:
    """Vectorised `us` for a Series/DatetimeIndex (UTC)."""
    import numpy as np

    idx = pd.DatetimeIndex(ts)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return ((idx - _EPOCH) // pd.Timedelta(microseconds=1)).to_numpy().astype(np.int64)


def from_us(x: int | pd.Series):
    return pd.to_datetime(x, unit="us", utc=True)
