"""Owner policy 2026-11-07 (employee count) and 2026-11-08 (region, same rule): evidence below the confidence threshold, or without a confidence, can never by itself
hold or disqualify a lead; it is flagged for human verification. 0.6 is a configurable business-policy threshold, not a statistically validated one."""
import pytest
from gtm.agents.intake import HARD_CONSTRAINT_MIN_CONFIDENCE as MIN, apply_hard_constraints as hc, triage_gate
from gtm.config import Settings

F = lambda emp=800, conf=0.9, region="EMEA", rconf=0.9: {"employee_count": {"value": emp, "confidence": conf}, "region": {"value": region, "confidence": rconf}}
fields = lambda needed: [n["field"] for n in needed]


def test_default_threshold_is_the_documented_policy_value():
    assert MIN == 0.6 and Settings().hard_constraint_min_confidence == 0.6


def test_confident_small_company_is_capped_at_low_and_not_flagged():
    band, why, needed = hc("high", F(30, 0.9))
    assert band == "low" and why and not needed


def test_confident_unserved_region_is_capped_at_low_and_not_flagged():
    band, why, needed = hc("high", F(900, 0.9, "LATAM", 0.9))
    assert band == "low" and "region" in why[0] and not needed


@pytest.mark.parametrize("conf", [0.0, 0.3, MIN - 0.01, None])
def test_low_or_missing_confidence_employee_count_never_holds_but_is_flagged(conf):
    band, why, needed = hc("high", F(30, conf))
    assert band == "high" and not why
    assert fields(needed) == ["employee_count"] and needed[0]["would_have_applied"] is True and needed[0]["value"] == 30


@pytest.mark.parametrize("conf", [0.0, 0.25, MIN - 0.01, None])
def test_low_or_missing_confidence_region_never_holds_but_is_flagged(conf):
    band, why, needed = hc("high", F(900, 0.9, "LATAM", conf))
    assert band == "high" and not why
    assert fields(needed) == ["region"] and needed[0]["would_have_applied"] is True


def test_low_confidence_value_that_would_not_breach_is_still_flagged_as_unverified():
    band, why, needed = hc("high", F(800, 0.2, "NA", 0.2))
    assert band == "high" and not why and fields(needed) == ["employee_count", "region"]
    assert all(n["would_have_applied"] is False for n in needed)


def test_threshold_boundary_is_inclusive_for_both_fields():
    assert hc("medium", F(30, MIN))[0] == "low" and hc("medium", F(900, 0.9, "LATAM", MIN))[0] == "low"


def test_missing_value_is_flagged_not_rejected():
    band, why, needed = hc("high", {})
    assert band == "high" and not why and fields(needed) == ["employee_count", "region"]
    assert all(n["value"] is None and "mandatory" in n["reason"] for n in needed)


def test_both_fields_low_confidence_nothing_is_held_and_both_are_flagged():
    band, why, needed = hc("high", F(12, 0.2, "LATAM", 0.2))
    assert band == "high" and not why and fields(needed) == ["employee_count", "region"]


def test_one_confident_breach_holds_while_the_other_uncertain_field_is_flagged():
    band, why, needed = hc("high", F(30, 0.2, "LATAM", 0.9))
    assert band == "low" and len(why) == 1 and "region" in why[0] and fields(needed) == ["employee_count"]


def test_constraints_never_upgrade():
    assert hc("none", F(30, 0.9))[0] == "none" and hc("low", F(800, 0.9))[0] == "low"


def test_threshold_is_configurable():
    assert hc("high", F(30, 0.5), min_confidence=0.4)[0] == "low"        # 0.5 is now 'confident enough'
    assert hc("high", F(30, 0.5), min_confidence=0.9)[0] == "high"       # and not under a stricter policy


def test_threshold_env_override_and_validation(monkeypatch):
    monkeypatch.setenv("GTM_HARD_CONSTRAINT_MIN_CONFIDENCE", "0.8")
    assert hc("high", F(30, 0.7))[0] == "high"
    monkeypatch.setenv("GTM_HARD_CONSTRAINT_MIN_CONFIDENCE", "1.5")
    with pytest.raises(ValueError):
        hc("high", F(30, 0.9))


# ---- triage gate (policy: spam/phishing held for review, never archived; unclear intent requires human review)
T = lambda label, conf=0.9, inj=False: {"label": label, "confidence": conf, "injection_suspected": inj}


@pytest.mark.parametrize("label,conf,known,expect", [("unclear", 0.4, False, "hold"), ("unclear", 0.9, True, "hold"), ("spam", 0.9, False, "hold"), ("spam", 0.3, False, "hold"), ("spam", 0.5, True, "hold"), ("vendor", 0.5, False, "go"), ("genuine", 0.9, False, "go"),
                                                     ("genuine", 0.9, True, "go"), ("vendor", 0.9, True, "go")])
def test_triage_gate(label, conf, known, expect):
    assert triage_gate(T(label, conf), known) == expect


def test_injection_is_always_held():
    assert triage_gate(T("genuine", 0.99, True), True) == "hold"
