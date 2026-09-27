"""Shared test support for the async build-jobs stream (used by tests/test_api_themes.py and
tests/test_api_report.py). Not a test module itself - no `test_` prefix, so pytest does not collect it.
"""
from __future__ import annotations

import time
from threading import Event
from typing import Any


def wait_for_job(client, dataset_id: int, job_id: int, *, timeout: float = 5.0, poll: float = 0.02) -> dict:
    """Polls `GET .../jobs/{job_id}` until `status` is no longer "running", returning the final body.

    Fails loudly, not silently, if the job never finishes in time - in these tests every fake client
    returns instantly (or blocks only until a test releases it), so a job stuck "running" past the
    timeout means a real bug in the job runner, not a slow fixture.
    """
    deadline = time.monotonic() + timeout
    body: dict | None = None
    while time.monotonic() < deadline:
        r = client.get(f"/api/datasets/{dataset_id}/jobs/{job_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] != "running":
            return body
        time.sleep(poll)
    raise AssertionError(f"job {job_id} still 'running' after {timeout}s (last seen: {body})")


class BlockingClient:
    """Wraps one method of a real (in tests, Fake) client so a test can pause the background pipeline
    mid-flight and observe an intermediate `job.step` before releasing it.

    `method_name` is the single method this pipeline phase calls (`"embed"` for an embedding client,
    `"complete"` for a Claude client). The wrapped call sets `reached` right before it blocks (a test waits
    on this to know the pipeline has truly reached this phase, not just that the job was created) and waits
    on `released` (a `threading.Event` the test sets once it has finished asserting on the paused state)
    before calling through to the real fake underneath.
    """

    def __init__(self, inner: Any, method_name: str, wait_timeout: float = 10.0) -> None:
        self.reached = Event()
        self.released = Event()

        def _blocking(*args: Any, **kwargs: Any) -> Any:
            self.reached.set()
            ok = self.released.wait(timeout=wait_timeout)
            if not ok:
                raise AssertionError(f"BlockingClient.{method_name} was never released by the test")
            return getattr(inner, method_name)(*args, **kwargs)

        setattr(self, method_name, _blocking)
