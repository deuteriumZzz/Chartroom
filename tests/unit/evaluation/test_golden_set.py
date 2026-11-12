"""Золотой набор согласован с корпусом: иначе eval мерил бы попадание в несуществующий раздел."""

import json
import pathlib
from collections import Counter

from chartroom.bootstrap import build_document_chunker
from chartroom.evaluation.adapters.files import load_golden
from chartroom.evaluation.domain import CaseKind

ROOT = pathlib.Path(__file__).resolve().parents[3]
CASES = load_golden(ROOT / "eval" / "golden.yaml")


def test_golden_set_has_the_specified_mix() -> None:
    assert Counter(case.kind for case in CASES) == {
        CaseKind.ANSWERABLE: 20,
        CaseKind.CROSS_LANGUAGE: 5,
        CaseKind.UNANSWERABLE: 5,
    }
    assert len({case.id for case in CASES}) == len(CASES)


def test_every_expected_section_exists_in_the_corpus() -> None:
    corpus = ROOT / "data" / "corpus"
    manifest = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))
    sections = {
        entry["title"]: [
            chunk.section_path
            for chunk in build_document_chunker().chunk(
                entry["path"], (corpus / entry["path"]).read_bytes()
            )
        ]
        for entry in manifest
    }
    for case in CASES:
        if case.kind is CaseKind.UNANSWERABLE:
            assert case.document is None and case.section is None, case.id
            continue
        assert case.document is not None and case.document in sections, case.id
        assert any(case.matches(case.document, path) for path in sections[case.document]), case.id
