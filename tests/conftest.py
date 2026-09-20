import pytest


@pytest.fixture(autouse=True)
def dev_user(monkeypatch):
    """Tests use the shared dev user (only honoured when ENV=dev). Tests can delete the variables to check fail-closed."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("ALLOW_DEV_USER", "true")
