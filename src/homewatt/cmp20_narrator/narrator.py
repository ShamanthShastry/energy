"""Records in, checked sentences out.

Checks on every statement (a failing statement is discarded and logged, and the Actions tab
falls back to the action's assumption_text, marked unnarrated):
  TRS-20-02 every number in the text appears, as a string, in that action's input record;
  TRS-20-03 one statement per input action; names no appliance other than its own;
  TRS-20-04 schema-valid JSON, retried once with the error, then discarded;
  TRS-20-05 at most 30 words, no symbols ($ % ° ₂) or abbreviations like CO2 / kWh;
  TRS-20-10 never implies a not-verified action saved money.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass

from homewatt.cmp20_narrator.backend import BackendUnavailable, NarratorBackend
from homewatt.config import REPO_ROOT
from homewatt.display import kg, money, per_month, plain_change

log = logging.getLogger(__name__)

MAX_WORDS = 30
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
FORBIDDEN = re.compile(r"[$%°₂]|\bCO2\b|\bkWh\b|\bkg\b|\bA/C\b", re.IGNORECASE)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "statements": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {"action_id": {"type": "STRING"}, "text": {"type": "STRING"}},
                "required": ["action_id", "text"],
            },
        }
    },
    "required": ["statements"],
}

PROMPT_PATH = REPO_ROOT / "config" / "narrator.md"  # Gemini's instructions; edit the file, not this module


def system_prompt() -> str:
    return PROMPT_PATH.read_text()


SYSTEM = system_prompt()


@dataclass
class Statement:
    action_id: str
    text: str
    narrated: bool
    reason: str = ""


def record_for(action: dict, labels: dict[str, str], first_week: bool, history: list[dict]) -> dict:
    """The structured input for one action (TRS-20-01). All figures are display strings."""
    hist = [h for h in history if h.get("appliance_id") == action["appliance_id"]]
    rec = {
        "action_id": action["action_id"],
        "appliance": labels.get(action["appliance_id"], action["appliance_id"]),
        "change": plain_change(action["assumption_text"]),
        "saving_dollars_per_month": money(per_month(float(action["saving_usd"]))),
        "carbon_kilograms_per_month": kg(per_month(float(action["saving_kg_co_2"]))),
        "first_week": bool(first_week),
        "history": [
            {"appliance": labels.get(h["appliance_id"], h["appliance_id"]), "change": plain_change(h["assumption_text"]), "status": h["status"],
             **({"verified_saving_dollars": money(float(h["verified_saving_usd"]))} if h["status"] == "verified" else {})}
            for h in hist
        ],
    }
    if rec["carbon_kilograms_per_month"] == "0.0":  # a time shift saves no carbon at a static intensity; say nothing
        del rec["carbon_kilograms_per_month"]
    return rec


def _numbers_in(obj) -> set[str]:
    out: set[str] = set()
    if isinstance(obj, dict):
        for v in obj.values():
            out |= _numbers_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _numbers_in(v)
    elif isinstance(obj, str):
        out |= set(NUMBER_RE.findall(obj))
    return out


def check(text: str, record: dict, all_labels: list[str]) -> str | None:
    """Return the reason a statement fails, or None when it passes."""
    words = text.split()
    if not words:
        return "empty"
    if len(words) > MAX_WORDS:
        return f"{len(words)} words > {MAX_WORDS} (TRS-20-05)"
    if FORBIDDEN.search(text):
        return "symbol or abbreviation (TRS-20-05)"
    allowed = _numbers_in(record)
    for n in NUMBER_RE.findall(text):
        if n not in allowed:
            return f"number {n} not in the input (TRS-20-02)"
    own = record["appliance"].lower()
    low = text.lower()
    for lab in all_labels:
        lab_l = lab.lower()
        if lab_l != own and lab_l not in own and re.search(rf"\b{re.escape(lab_l)}\b", low):
            return f"names another appliance: {lab} (TRS-20-03)"
    for h in record.get("history", []):
        if h["status"] == "not_verified" and re.search(r"\bsav(ed|ing)\b", low) and "last week" in low:
            return "implies a not-verified action saved money (TRS-20-10)"
    return None


def narrate(backend: NarratorBackend, records: list[dict], all_labels: list[str]) -> list[Statement]:
    """One statement per record; failures fall back to the record's change text, unnarrated."""
    user = json.dumps({"actions": records}, ensure_ascii=False, indent=1)
    by_id = {r["action_id"]: r for r in records}
    parsed: dict[str, str] = {}
    err = None
    for attempt in range(2):  # TRS-20-04: one retry with the schema error
        prompt = user if err is None else f"{user}\n\nYour previous reply was rejected: {err}. Reply again with valid JSON."
        try:
            raw = backend.generate(system_prompt(), prompt, SCHEMA)
            data = json.loads(raw)
            items = data["statements"]
            if not isinstance(items, list) or not all(isinstance(i, dict) and "action_id" in i and "text" in i for i in items):
                raise ValueError("statements must be a list of {action_id, text}")
            parsed = {i["action_id"]: str(i["text"]).strip() for i in items if i["action_id"] in by_id}
            err = None
            break
        except BackendUnavailable as e:
            log.warning("narrator backend unavailable: %s", e)
            err = str(e)
            break
        except (ValueError, KeyError, TypeError) as e:
            err = f"{type(e).__name__}: {e}"
            log.warning("narrator response invalid (attempt %d): %s", attempt + 1, err)
    out = []
    for aid, rec in by_id.items():
        text = parsed.get(aid)
        reason = "provider unavailable or invalid response" if text is None else check(text, rec, all_labels)
        if reason is None:
            out.append(Statement(aid, text, True))
        else:
            log.warning("statement for %s discarded: %s", aid, reason)
            out.append(Statement(aid, rec["change"], False, reason))
    return out


def input_sha(record: dict) -> str:
    """Record plus prompt: editing config/narrator.md re-narrates every open action (TRS-20-06)."""
    return hashlib.sha256((json.dumps(record, sort_keys=True) + system_prompt()).encode()).hexdigest()[:16]


def run(client, household_id: str, week_id: str, backend: NarratorBackend | None) -> list[Statement]:
    """TRS-20-06: narrate the week's batch when its records changed (new or re-priced actions)."""
    acts = client.sql(f"SELECT * FROM action WHERE household_id = '{household_id}' AND week_id = '{week_id}'")
    acts = acts[acts["status"].isin(["proposed", "accepted"])] if len(acts) else acts
    if acts.empty:
        return []
    apps = client.sql(f"SELECT appliance_id, label FROM appliance WHERE household_id = '{household_id}'")
    labels = dict(zip(apps["appliance_id"], apps["label"], strict=True))
    hist = client.sql(f"SELECT * FROM action WHERE household_id = '{household_id}' AND week_id < '{week_id}'")
    last_week = sorted(hist["week_id"].unique())[-1] if len(hist) else None
    history = hist[hist["week_id"] == last_week].to_dict("records") if last_week else []
    first_week = len(hist) == 0
    current = client.sql(f"SELECT action_id, input_sha, unnarrated FROM statement WHERE household_id = '{household_id}' AND superseded_at_us = 0")
    # A fallback (unnarrated) statement is retried on the next run; a narrated one only when its input changed.
    have = {r["action_id"]: r["input_sha"] for r in current.to_dict("records") if not r["unnarrated"]} if len(current) else {}
    records = []
    for a in acts.to_dict("records"):
        rec = record_for(a, labels, first_week, history)
        if have.get(a["action_id"]) != input_sha(rec):
            records.append(rec)
    if not records:
        return []
    statements = narrate(backend, records, list(labels.values())) if backend is not None else [
        Statement(r["action_id"], r["change"], False, "no backend") for r in records
    ]
    shas = {r["action_id"]: input_sha(r) for r in records}
    for s in statements:
        client.call("write_statement", str(uuid.uuid4()), household_id, s.action_id, "", s.text,
                    backend.model_version if (backend is not None and s.narrated) else "fallback", not s.narrated, shas[s.action_id])
    return statements


def default_backend() -> NarratorBackend | None:
    from homewatt.config import get_settings

    s = get_settings()
    if not s.gemini_api_key:
        return None
    from homewatt.cmp20_narrator.backend import GeminiBackend

    return GeminiBackend(s.gemini_api_key, s.gemini_model)
