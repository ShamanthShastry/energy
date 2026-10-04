"""TRS-00-02: sessions are split into train (12) and test (3) once, by session, and the split
is recorded in a file. No component re-splits. write_split refuses to overwrite.

Test sessions are chosen by a fixed rule, not at random: the three longest sessions that have
every sub-meter covering the whole session, one from each calendar stretch of the recording
(mid-May, late May, late June). Everything retained and not in TEST_SESSIONS is train.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

TEST_SESSIONS: tuple[str, ...] = ("05-16", "05-26", "06-24")
EXPECTED_TRAIN = 12
EXPECTED_TEST = 3


class SplitExistsError(RuntimeError):
    pass


def make_split(retained: list[str], excluded: dict[str, str]) -> dict:
    test = [s for s in retained if s in TEST_SESSIONS]
    train = [s for s in retained if s not in TEST_SESSIONS]
    missing = set(TEST_SESSIONS) - set(test)
    if missing:
        raise ValueError(f"test sessions not present among retained sessions: {sorted(missing)}")
    return {
        "trs": "TRS-00-02",
        "written_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rule": "by recording session; never by shuffled sample (TRS-SYS-07)",
        "train": train,
        "test": test,
        "excluded": excluded,
    }


def write_split(path: Path, split: dict, force: bool = False) -> None:
    if path.exists() and not force:
        raise SplitExistsError(
            f"{path} already exists; the split is written once and never re-split (TRS-00-02)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(split, indent=2) + "\n")


def read_split(path: Path) -> dict:
    return json.loads(path.read_text())
