"""Turning masked text into vectors. `EmbeddingClient` is the interface the rest of the pipeline codes
against; `VoyageEmbeddingClient` is the real implementation (network, needs `VOYAGE_API_KEY`),
`FakeEmbeddingClient` is a deterministic stand-in for tests (no network, ever).

Caching is deliberately NOT done here (see SPEC.md section 2, "cache by file hash and column"): that is
the caller's job, once there is a place to cache to (a dataset's profile, a table, ...). This module only
turns texts into vectors, once, for whatever it is given.
"""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol, runtime_checkable

# Voyage's HTTP API accepts up to 1000 texts per request and caps total input tokens per request; staying
# well under both (and under most models' context limits per text) keeps a single retryable call cheap and
# fast without tuning per model. Callers needing a different batch size can still call `embed()` themselves
# with pre-chunked lists; `VoyageEmbeddingClient` chunks internally so callers never have to think about it.
DEFAULT_BATCH_SIZE = 128
DEFAULT_MODEL = "voyage-3.5"

# `_embed_batch`'s own measured latency is dominated by fixed per-call overhead, not by how many texts are
# in the batch (confirmed directly against the real API: batches of 32/128/500/1000 texts all took roughly
# the same wall-clock time) - so a strictly SEQUENTIAL loop over batches scales terribly with row count: a
# real 80,000-row build (~625 batches at the default size) was confirmed to blow well past
# `app.api_themes.THEMES_DEADLINE_SECONDS` (300s) this way, timing out every attempt even though nothing
# was actually broken - just one HTTP round-trip waiting on the next, serially, for an I/O-bound call that
# has nothing to do with the CPU. `DEFAULT_CONCURRENCY` batches now run at once via a thread pool (Python
# releases the GIL during network I/O, so this is real wall-clock parallelism, not fake); order is still
# preserved exactly (`embed()` maps each batch's result back to its own position, not completion order).
# Env-overridable (matches app.api_themes.THEMES_CONCURRENCY / app.api_report.REPORT_CONCURRENCY's own
# `os.environ.get("...", default)` convention) so a production deploy can tune it against Voyage's actual
# observed rate limits without a code change, the same way those other concurrency knobs already work.
DEFAULT_CONCURRENCY = max(1, int(os.environ.get("VOYAGE_EMBED_CONCURRENCY", "8") or 8))


class EmbeddingNotConfigured(RuntimeError):
    """Raised instead of ever making a network call with no API key."""


@runtime_checkable
class EmbeddingClient(Protocol):
    """Anything that can turn a list of texts into a same-length list of vectors, in order."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class VoyageEmbeddingClient:
    """Real embeddings via Voyage AI (https://www.voyageai.com/). Lazy-imports `voyageai` so nothing
    outside this module needs the package installed, and so importing `app.text_pipeline` never fails
    when the package (or its native deps) is missing in some environment.

    Reads `VOYAGE_API_KEY` from the environment; raises `EmbeddingNotConfigured` if it is unset, before
    ever touching the network. Model is `VOYAGE_MODEL` or `voyage-3.5`. Batches requests at
    `batch_size` texts each (default `DEFAULT_BATCH_SIZE`), running up to `concurrency` batches at once
    (default `DEFAULT_CONCURRENCY` - see that constant's own comment for why this is not just sequential),
    and retries a batch once on a transient error (anything that is not an auth/config problem), with a
    short pause between the two attempts.
    """

    def __init__(self, batch_size: int = DEFAULT_BATCH_SIZE, model: str | None = None,
                 concurrency: int = DEFAULT_CONCURRENCY) -> None:
        api_key = os.environ.get("VOYAGE_API_KEY")
        if not api_key:
            raise EmbeddingNotConfigured(
                "VOYAGE_API_KEY is not set. Embeddings need it; nothing was sent over the network."
            )
        try:
            import voyageai  # lazy import: only needed when this class is actually used
        except ImportError as e:  # pragma: no cover - exercised only when the package is missing
            raise EmbeddingNotConfigured(
                "The 'voyageai' package is not installed. Add it to the environment before embedding."
            ) from e
        self._client = voyageai.Client(api_key=api_key)
        self.batch_size = max(1, batch_size)
        self.concurrency = max(1, concurrency)
        self.model = model or os.environ.get("VOYAGE_MODEL", DEFAULT_MODEL)

    def embed(self, texts: list[str]) -> list[list[float]]:
        batches = [texts[start:start + self.batch_size] for start in range(0, len(texts), self.batch_size)]
        if len(batches) <= 1:
            return self._embed_batch(batches[0]) if batches else []
        # `results` is indexed by BATCH POSITION, not completion order - concurrency must never change
        # the order vectors come back in, since every downstream caller matches them 1:1 against
        # `row_indexes`/`texts` by position (see embed_and_cluster_with_vectors's own docstring).
        results: list[list[list[float]] | None] = [None] * len(batches)
        with ThreadPoolExecutor(max_workers=min(self.concurrency, len(batches))) as pool:
            futures = {pool.submit(self._embed_batch, b): i for i, b in enumerate(batches)}
            for future in futures:
                # `.result()` re-raises inside THIS thread if that batch's own retry-once already failed -
                # same "no silent partial result" guarantee the old sequential loop had.
                results[futures[future]] = future.result()
        vectors: list[list[float]] = []
        for batch_vectors in results:
            vectors.extend(batch_vectors)
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(2):  # one retry on a transient error
            try:
                result = self._client.embed(batch, model=self.model, input_type="document")
                return list(result.embeddings)
            except Exception as e:  # noqa: BLE001 - the SDK's exception types are not all public
                last_error = e
                if attempt == 0:
                    time.sleep(1.0)
        raise RuntimeError(f"Voyage embedding call failed after a retry: {last_error}") from last_error


class FakeEmbeddingClient:
    """Deterministic, network-free vectors for tests. Each text is hashed into a fixed-size vector so
    that identical texts always land on the same point and near-duplicate wording (same words, mostly
    the same characters) tends to land close together - close enough for clustering tests, but this is
    NOT a semantic embedding. See docs/DECISIONS.md for how this differs from a real model.
    """

    def __init__(self, dimensions: int = 32) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        # Bag-of-words hashing: each lowercased word nudges a fixed set of dimensions, so answers that
        # share words end up with similar vectors regardless of word order, and unrelated answers do not.
        vec = [0.0] * self.dimensions
        words = text.lower().split() or [""]
        for word in words:
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            for i in range(self.dimensions):
                # Two bytes per dimension (cycling through the digest) keep this independent of `dimensions`.
                b = digest[(2 * i) % len(digest)]
                vec[i] += (b / 255.0) * 2 - 1  # spread into [-1, 1] per word, then summed below
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]
