"""Shared field definitions. The 37-field aggregate sample record (CMP-01 output) and the
closed appliance type list (TRS-14-02). Every component imports these; nobody redefines them.

37 fields = ts + p_active_w + irms_a + vrms_v + power_factor + h1..h32 (TRS-01-01).
household_id travels alongside and is not counted.
"""

from __future__ import annotations

from enum import StrEnum

HARMONICS: tuple[str, ...] = tuple(f"h{i}" for i in range(1, 33))

#: The 36 numeric fields of a sample, in canonical order.
NUMERIC_FIELDS: tuple[str, ...] = ("p_active_w", "irms_a", "vrms_v", "power_factor", *HARMONICS)

#: The 37-field record (TRS-01-04: replay and live are byte-identical in schema).
SAMPLE_FIELDS: tuple[str, ...] = ("ts", *NUMERIC_FIELDS)

assert len(SAMPLE_FIELDS) == 37

#: Index of each numeric field inside a sample's value vector.
FIELD_INDEX: dict[str, int] = {name: i for i, name in enumerate(NUMERIC_FIELDS)}
IDX_P_ACTIVE = FIELD_INDEX["p_active_w"]
IDX_IRMS = FIELD_INDEX["irms_a"]
IDX_VRMS = FIELD_INDEX["vrms_v"]
IDX_PF = FIELD_INDEX["power_factor"]
IDX_H1 = FIELD_INDEX["h1"]
IDX_H32 = FIELD_INDEX["h32"]

#: Nominal sensor cadence (TRS-01-02) and the gap threshold (TRS-01-02, TRS-05-03).
SAMPLE_PERIOD_S: float = 2.0
GAP_THRESHOLD_S: float = 10.0

#: Appliance on/off threshold used by CMP-00 extraction, CMP-09 F1, and the hourly on_s rollup.
ON_THRESHOLD_W: float = 10.0

#: CMP-05 validation bounds (TRS-05-02).
VRMS_MIN_V: float = 90.0
VRMS_MAX_V: float = 290.0


class ApplianceType(StrEnum):
    """TRS-14-02 closed list. Selects the NILM head, anomaly features, and action templates."""

    fridge = "fridge"
    water_heater = "water_heater"
    hair_dryer = "hair_dryer"
    iron = "iron"
    laptop = "laptop"
    screen = "screen"
    lamp = "lamp"
    straightener = "straightener"
    hvac = "hvac"
    dryer = "dryer"
    oven = "oven"
    ev = "ev"
    other = "other"


#: Dinar et al. dataset file -> appliance type. S1P3 is the aggregate.
DATASET_FILES: dict[str, str] = {
    "S1P1.csv": ApplianceType.hair_dryer,
    "S1P2.csv": ApplianceType.water_heater,
    "S2P4.csv": ApplianceType.straightener,
    "S2P5.csv": ApplianceType.fridge,
    "S3P7.csv": ApplianceType.iron,
    "S3P8.csv": ApplianceType.screen,
    "S4P10.csv": ApplianceType.laptop,
    "S4P11.csv": ApplianceType.lamp,
}
DATASET_AGGREGATE_FILE = "S1P3.csv"

#: Dataset CSV column -> canonical field name. `time` and `p_apparente` are handled separately.
DATASET_COLUMN_MAP: dict[str, str] = {
    "irms": "irms_a",
    "vrms": "vrms_v",
    "power_factor": "power_factor",
    "p_active": "p_active_w",
    **{h: h for h in HARMONICS},
}

#: Appliances present in the real dataset (everything except hvac, dryer, oven, ev, other).
DATASET_APPLIANCE_TYPES: tuple[str, ...] = tuple(sorted(set(DATASET_FILES.values())))
