"""A first-time case's actions don't exist in the graph yet. TigerGraph answers a lookup of an unknown id with error
601, and that must read as "not there", not as a failed write (on 29 Oct it marked every official answer incomplete)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.case_writer import existing_vertices  # noqa: E402


class FakeGraph:
    def __init__(self, stored):
        self.stored = stored

    def getVerticesById(self, vtype, vid):
        if vid not in self.stored:
            raise RuntimeError(f"(\"The input vertex id '{vid}' is not a valid vertex id for vertex type = {vtype}.\", '601')")
        return [{"v_id": vid, "attributes": self.stored[vid]}]


def no_retry(fn):
    return fn()


def test_unknown_ids_are_missing_not_errors():
    graph = FakeGraph({"A1": {"status": "approved"}})
    found = existing_vertices(graph, "ActionRecord", ["NEW-1", "A1", "NEW-2"], no_retry)
    assert [v["v_id"] for v in found] == ["A1"]


def test_other_graph_errors_still_fail_the_write():
    class Down(FakeGraph):
        def getVerticesById(self, vtype, vid):
            raise RuntimeError("REST-10001 graph is unavailable")

    with pytest.raises(RuntimeError):
        existing_vertices(Down({}), "ActionRecord", ["X"], no_retry)
