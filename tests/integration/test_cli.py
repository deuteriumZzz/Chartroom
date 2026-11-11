import pytest

from chartroom.cli import main


@pytest.mark.usefixtures(
    "engine"
)  # БД с применёнными миграциями должна существовать до запуска CLI
def test_create_user_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CHARTROOM_PASSWORD", "s3cret-pass")
    main(["create-user", "cli-admin@ship.test", "--role", "admin"])
    assert "email=cli-admin@ship.test role=admin" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="error: Email is already registered"):
        main(["create-user", "CLI-ADMIN@ship.test", "--role", "officer"])
