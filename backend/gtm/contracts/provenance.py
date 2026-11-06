"""Data-provenance labels (docs/evaluation-strategy.md section 9). Every non-production record and metric is labelled."""
from enum import StrEnum


class DataOrigin(StrEnum):
    GT = "GT"            # generated ground truth
    SIM = "SIM"          # simulated provider output (degraded truth)
    SCR = "SCR"          # scripted prospect/customer response or scenario data
    MOD = "MOD"          # model-generated (record model_id and mode: replay|mock|live)
    HUM_SIM = "HUM-sim"  # simulated reviewer decision
    HUM_REAL = "HUM-real"  # real human decision (the person using the demo)
    PLT = "PLT"          # planted effect/theme


class EvidenceBasis(StrEnum):
    MEASURED_ON_SIMULATION = "measured_on_simulation"
    MACHINERY_CHECK = "machinery_check"
    MODELLED_IMPACT = "modelled_impact"
