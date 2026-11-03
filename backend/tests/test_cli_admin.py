from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.cli import main


@pytest.mark.parametrize(
    "arguments",
    [
        ["jobs", "run"],
        ["jobs", "run", "J-06", "J-07"],
        ["orders", "show", "P000001"],
        ["orders", "resume", "P000001"],
        ["orders", "cancel", "P000001", "--reason", "店舗都合"],
        ["payments", "reconcile", "P000001"],
        ["mails", "list", "--status", "FAILED"],
        ["mails", "resend", "notification-id"],
    ],
)
def test_admin_cli_routes_without_seed_password(arguments, settings, monkeypatch):
    import app.main
    from app import cli
    from app.services import administration

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    dispose = Mock()
    monkeypatch.setattr(
        app.main,
        "create_app",
        lambda *args: SimpleNamespace(
            state=SimpleNamespace(engine=SimpleNamespace(dispose=dispose))
        ),
    )
    command = Mock(return_value={"ok": True})
    monkeypatch.setattr(administration, "command", command)
    assert main(arguments) == 0
    command.assert_called_once()
    dispose.assert_called_once()
