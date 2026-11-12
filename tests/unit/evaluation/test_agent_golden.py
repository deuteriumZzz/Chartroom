"""Сценарии агента согласованы с инструментами и корпусом: иначе eval мерил бы невозможное."""

import pathlib

from chartroom.agent.domain import DATA_TOOL_SPECS
from chartroom.evaluation.adapters.files import load_agent_golden
from chartroom.shared.schema import validate
from tests.unit.evaluation.test_golden_set import corpus_sections

ROOT = pathlib.Path(__file__).resolve().parents[3]
CASES = load_agent_golden(ROOT / "eval" / "agent_golden.yaml")


def test_agent_golden_set_covers_tools_refusals_and_injections() -> None:
    assert len(CASES) >= 10 and len({c.id for c in CASES}) == len(CASES)
    assert {t for c in CASES for t in c.expected_tools} == set(DATA_TOOL_SPECS)
    assert sum(c.id.startswith("ag-inj") and c.expect_refusal is True for c in CASES) >= 2


def test_expected_calls_are_valid_for_the_tool_schemas() -> None:
    for case in CASES:
        assert set(case.expected_tools) | set(case.forbidden_tools) <= set(DATA_TOOL_SPECS), case.id
        if case.expected_args:
            spec = DATA_TOOL_SPECS[case.expected_tools[0]]
            assert validate(spec.parameters, dict(case.expected_args)) == (), case.id


def test_expected_citations_exist_in_the_corpus() -> None:
    sections = corpus_sections()
    for case in CASES:
        if case.section is None:
            continue
        assert case.document in sections, case.id
        assert any(case.section in path for path in sections[case.document]), case.id
