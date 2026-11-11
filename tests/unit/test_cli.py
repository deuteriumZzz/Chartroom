import pathlib

import pytest

from chartroom.cli import main


def test_chunk_command_prints_sections(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = tmp_path / "fire.md"
    doc.write_text("# Fire\n## 1. Purpose\nDefines actions.\n## 2. Scope\nAll ships.\n")
    main(["chunk", str(doc)])
    out = capsys.readouterr().out
    assert "2 chunks" in out
    assert "Fire / 1. Purpose" in out
    assert "Fire / 2. Scope" in out


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("setup.exe", b"MZ", "error: Supported formats"),
        ("empty.md", b"   ", "error: Document has no"),
    ],
)
def test_chunk_command_reports_domain_errors(
    tmp_path: pathlib.Path, name: str, content: bytes, message: str
) -> None:
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(SystemExit, match=message):
        main(["chunk", str(path)])


def test_chunk_command_reports_missing_file(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match="error: .*missing.md"):
        main(["chunk", str(tmp_path / "missing.md")])
