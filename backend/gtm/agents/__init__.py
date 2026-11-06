"""Agents and workflows (mock model by default). build_graphs() returns every graph; register them with Runner.register."""
from . import account, execute, ingest, intake, resume
from .mockmodel import register_all


def build_graphs():
    register_all()
    return [intake.build_graph(), account.build_graph(), execute.build_graph(), ingest.build_graph(), resume.build_graph()]


__all__ = ["build_graphs", "register_all", "account", "execute", "ingest", "intake", "resume"]
