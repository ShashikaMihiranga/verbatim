import dotenv
import pytest

# Tests must not read the developer's local .env (dev mode, Clerk URLs): it made auth/docs tests pass or
# fail depending on whose machine ran them. Both readers are switched off here, before any `app` import -
# app/main.py's load_dotenv() and pydantic-settings' env_file in app/config.py.
dotenv.load_dotenv = lambda *args, **kwargs: False

from app.config import Settings  # noqa: E402

Settings.model_config["env_file"] = None


@pytest.fixture(autouse=True)
def dev_user(monkeypatch):
    """Tests use the shared dev user (only honoured when ENV=dev). Tests can delete the variables to check fail-closed."""
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("ALLOW_DEV_USER", "true")


@pytest.fixture(autouse=True)
def no_global_rate_limit(monkeypatch):
    """The shared app is hit hundreds of times a minute by the suite; rate-limit tests build their own app."""
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
