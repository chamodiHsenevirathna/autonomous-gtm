"""Requirements-to-scenarios matrix: ``python -m gtm.eval.coverage [--docs PATH] [--strict]``.

Reads requirement ids from the rows of docs/requirements.md (lines starting ``| FR-`` or ``| NFR-``; the last single-letter cell is the
priority M/S/C/X) and the ``covers`` of scenarios/*.yaml (and scenarios/pending/*.yaml, shown separately). Prints the matrix and the
requirements no runnable scenario covers. Covered means "some scenario is written for it", not "the requirement is met".
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

BACKEND = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_DOCS = BACKEND.parent / "docs" / "requirements.md"
ROW = re.compile(r"^\|\s*((?:N?FR)-[A-Z]+-\d+)\b[^|]*\|(.*)$")


def load_requirements(path: pathlib.Path) -> dict[str, str]:
    """id -> priority letter ('' if unknown). First definition wins (later amendments repeat ids)."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        m = ROW.match(line)
        if m and m.group(1) not in out:
            cells = [c.strip() for c in m.group(2).split("|") if c.strip()]
            prio = next((c for c in reversed(cells) if re.fullmatch(r"[MSCX]", c)), "")
            out[m.group(1)] = prio
    return out


def load_covers(scen_dir: pathlib.Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    def read(d):
        cov: dict[str, list[str]] = {}
        for f in sorted(d.glob("S*.yaml")):
            doc = yaml.safe_load(f.read_text())
            for r in doc.get("covers", []):
                cov.setdefault(r, []).append(doc["id"])
        return cov
    return read(scen_dir), read(scen_dir / "pending")


def build(docs: pathlib.Path, scen_dir: pathlib.Path) -> dict:
    reqs = load_requirements(docs)
    runnable, pending = load_covers(scen_dir)
    return {"requirements": reqs, "runnable": runnable, "pending": pending,
            "uncovered": [r for r in reqs if r not in runnable],
            "pending_only": [r for r in reqs if r not in runnable and r in pending],
            "unknown": sorted((set(runnable) | set(pending)) - set(reqs))}


def render(rep: dict) -> str:
    L = ["| Requirement | Priority | Scenarios | Pending scenarios |", "|---|---|---|---|"]
    for r, prio in rep["requirements"].items():
        L.append(f"| {r} | {prio} | {', '.join(rep['runnable'].get(r, [])) or '-'} | {', '.join(rep['pending'].get(r, [])) or '-'} |")
    n, c = len(rep["requirements"]), len(rep["requirements"]) - len(rep["uncovered"])
    must = [r for r in rep["uncovered"] if rep["requirements"][r] == "M"]
    L += ["", f"{c}/{n} requirements have at least one runnable scenario ({len(rep['pending_only'])} more only have a pending one).",
          f"Uncovered must-have (M) requirements: {len(must)}", ", ".join(must) or "none"]
    if rep["unknown"]:
        L += ["", "Scenario `covers` ids that are not in the requirements document: " + ", ".join(rep["unknown"])]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m gtm.eval.coverage", description=__doc__)
    ap.add_argument("--docs", default=str(DEFAULT_DOCS))
    ap.add_argument("--scenarios-dir", default=str(BACKEND / "scenarios"))
    ap.add_argument("--strict", action="store_true", help="exit 1 if a must-have requirement is uncovered or a covers id is unknown")
    a = ap.parse_args(argv)
    rep = build(pathlib.Path(a.docs), pathlib.Path(a.scenarios_dir))
    print(render(rep))
    bad = rep["unknown"] or [r for r in rep["uncovered"] if rep["requirements"][r] == "M"]
    return 1 if a.strict and bad else 0


if __name__ == "__main__":
    sys.exit(main())
