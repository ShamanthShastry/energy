"""CMP-15 — Query and Costing API (TRS-15-01 .. TRS-15-06). The only thing the dashboard talks to.
Every dollar figure is Σ kWh(ts) × rate(ts) computed here (TRS-15-01); every number leaves as a
display string so the dashboard holds no costing or formatting logic (TRS-16-10)."""
