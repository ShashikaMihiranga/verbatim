import pytest


@pytest.fixture(autouse=True)
def dev_user(monkeypatch):
    """Tests use the shared dev user. Individual tests can delete the variable to check fail-closed."""
    monkeypatch.setenv("ALLOW_DEV_USER", "true")
