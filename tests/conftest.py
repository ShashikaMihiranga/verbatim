import pytest


@pytest.fixture(autouse=True)
def dev_user(monkeypatch):
    """Tests use the shared dev user. Individual tests can delete the variable to check fail-closed."""
    monkeypatch.setenv("ALLOW_DEV_USER", "true")


@pytest.fixture(autouse=True)
def no_global_rate_limit(monkeypatch):
    """The shared app is hit hundreds of times a minute by the suite; rate-limit tests build their own app."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
