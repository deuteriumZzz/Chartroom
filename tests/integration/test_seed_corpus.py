import json
import pathlib

import pytest

from chartroom import cli
from chartroom.bootstrap import Container, build_container
from chartroom.shared.config import Settings
from tests.fakes import RecordingQueue


@pytest.mark.usefixtures("engine")  # БД с применёнными миграциями
def test_seed_corpus_uploads_once_and_then_skips(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    queue = RecordingQueue()

    def container_with_fake_queue(settings: Settings) -> Container:
        return build_container(settings, queue=queue)

    monkeypatch.setattr(cli, "build_container", container_with_fake_queue)
    (tmp_path / "en").mkdir()
    (tmp_path / "en" / "seed.md").write_text("# Seed Test Procedure\n## 1. Purpose\nText.\n")
    manifest = tmp_path / "manifest.json"
    entry = {
        "path": "en/seed.md",
        "title": "Seed Test Procedure",
        "version": "1",
        "language": "en",
        "issued_on": "2026-01-01",
    }
    manifest.write_text(json.dumps([entry]))

    cli.main(["seed-corpus", "--manifest", str(manifest)])
    cli.main(["seed-corpus", "--manifest", str(manifest)])
    out = capsys.readouterr().out
    assert "queued   en/seed.md  (version 1" in out
    assert "skipped  en/seed.md  (already uploaded)" in out
    assert len(queue.enqueued) == 1
