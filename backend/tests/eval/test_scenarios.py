import pathlib
import yaml
import pytest
from gtm.contracts.scenario import Scenario
from gtm.eval import runner as R

DIR = pathlib.Path(__file__).resolve().parents[2] / "scenarios"
WANTED = "S01 S02 S03 S04 S05 S06 S07 S09 S10 S11 S13 S14 S15 S16 S17 S18 S19 S22 S24 S25 S30 S45 S46 S47 S48 S49 S50 S52".split()
FILES = sorted(DIR.glob("S*.yaml"))


def test_every_wanted_scenario_exists():
    assert sorted(f.stem for f in FILES) == sorted(WANTED)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_yaml_parses_against_schema_and_lints(path):
    sc = Scenario.model_validate(yaml.safe_load(path.read_text()))
    assert sc.id == path.stem
    assert R.validate_scenario(sc) == []


def test_ids_unique_and_loader_works():
    scs = R.load_scenarios(DIR)
    assert len({s.id for s in scs}) == len(scs) == len(WANTED)
    assert [s.id for s in R.load_scenarios(DIR, ["S05", "S01"])] == ["S01", "S05"]
    with pytest.raises(R.ScenarioError):
        R.load_scenarios(DIR, ["S99"])


def test_headline_safety_scenarios_assert_invariants():
    for s in R.load_scenarios(DIR):
        if s.id in ("S01", "S13", "S17", "S24", "S25", "S45", "S46", "S49"):
            assert any(e.kind == "invariant" for e in s.expectations), s.id


def test_no_scenario_claims_accuracy_from_planted_or_scripted_answers():
    for s in R.load_scenarios(DIR):
        if "PLT" in s.data_origins:
            assert s.evidence_basis.value == "machinery_check", s.id


def test_validator_catches_mistakes():
    bad = Scenario.model_validate({"id": "S99", "title": "t", "pass_criterion": "c", "truth_source": "t", "evidence_basis": "machinery_check",
                                   "data_origins": ["XX"], "milestone": "M1", "covers": ["X"],
                                   "script": [{"kind": "enquiry", "ref": "nope"}, {"kind": "tamper", "params": {"what": "x"}}],
                                   "expectations": [{"kind": "metric", "name": "bogus"}, {"kind": "state", "name": "n", "spec": {"sql": "SELECT 1"}},
                                                    {"kind": "invariant", "name": "nope"}]})
    assert len(R.validate_scenario(bad)) >= 6


def test_cli_validate_and_list():
    assert R.main(["--validate"]) == 0
    assert R.main(["--list", "--scenarios", "S01,S02"]) == 0


def test_pending_scenarios_also_lint():
    from gtm.contracts.scenario import Scenario
    files = sorted((DIR / "pending").glob("S*.yaml"))
    assert files
    for f in files:
        assert R.validate_scenario(Scenario.model_validate(yaml.safe_load(f.read_text()))) == [], f.name


def test_coverage_matrix(tmp_path):
    from gtm.eval import coverage
    docs = tmp_path / "r.md"
    docs.write_text("| FR-INB-01 | Normalise | M |\n| FR-INB-02 | Dedupe | M |\n| NFR-SAF-01 | Safety | Safety text | M |\n| FR-X-09 | later | S |\ntext\n")
    sd = tmp_path / "scn"; (sd / "pending").mkdir(parents=True)
    (sd / "S01.yaml").write_text("id: S01\ncovers: [FR-INB-01, FR-ZZZ-01]\n")
    (sd / "pending" / "S08.yaml").write_text("id: S08\ncovers: [NFR-SAF-01]\n")
    rep = coverage.build(docs, sd)
    assert rep["requirements"] == {"FR-INB-01": "M", "FR-INB-02": "M", "NFR-SAF-01": "M", "FR-X-09": "S"}
    assert rep["uncovered"] == ["FR-INB-02", "NFR-SAF-01", "FR-X-09"] and rep["pending_only"] == ["NFR-SAF-01"] and rep["unknown"] == ["FR-ZZZ-01"]
    assert "FR-INB-02" in coverage.render(rep)
    assert coverage.main(["--docs", str(docs), "--scenarios-dir", str(sd), "--strict"]) == 1


def test_real_coverage_runs():
    from gtm.eval import coverage
    rep = coverage.build(coverage.DEFAULT_DOCS, DIR)
    assert len(rep["requirements"]) > 100 and rep["unknown"] == []
