"""Strict clients for the private Knowledge model-serving plane."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from functools import partial
import ipaddress
import json
import math
from threading import Condition, Event, Lock
from time import monotonic
from typing import Annotated, Generic, Literal, Protocol, TypeVar, cast
from urllib.parse import urlsplit

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from proof_agent.contracts._base import FrozenModel


WorkPriority = Literal["online", "offline"]
WorkKind = Literal["docling", "ocr", "embedding", "rerank"]
NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=32_768),
]
CandidateId = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
PinnedModelRevision = Annotated[
    StrictStr,
    StringConstraints(
        strip_whitespace=True,
        min_length=10,
        max_length=512,
        pattern=r"^.+@sha256:[A-Za-z0-9._-]+$",
    ),
]
InstructionStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=8192),
]
Vector = Annotated[tuple[StrictFloat, ...], Field(min_length=1, max_length=4096)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
T = TypeVar("T")
MAX_MODEL_TIMEOUT_SECONDS = 600.0
MAX_EMBEDDING_BATCH_CHARACTERS = 1_000_000
MAX_RERANK_BATCH_CHARACTERS = 2_000_000
MAX_MODEL_JSON_DEPTH = 32
MAX_MODEL_JSON_NODES = 1_000_000
MAX_MODEL_JSON_COLLECTION_ITEMS = 100_000
MAX_MODEL_JSON_STRING_CHARACTERS = 1_000_000


@dataclass(frozen=True)
class PrivateHostPolicy:
    """Explicit exact-host and suffix allowlist for private service origins."""

    exact_hosts: frozenset[str]
    suffixes: tuple[str, ...]

    @classmethod
    def from_entries(cls, entries: tuple[str, ...]) -> "PrivateHostPolicy":
        exact: set[str] = set()
        suffixes: set[str] = set()
        if not entries:
            raise ValueError("private Knowledge model allowed hosts must be configured")
        for raw_entry in entries:
            entry = raw_entry.strip().lower().rstrip(".")
            if not entry or any(character.isspace() for character in entry):
                raise ValueError("private Knowledge model allowed host is invalid")
            is_suffix = entry.startswith(".")
            host = entry[1:] if is_suffix else entry
            _validate_private_hostname(host, field="allowed host")
            if is_suffix:
                suffixes.add(f".{host}")
            else:
                exact.add(host)
        return cls(
            exact_hosts=frozenset(exact),
            suffixes=tuple(sorted(suffixes)),
        )

    def allows(self, hostname: str) -> bool:
        host = hostname.lower().rstrip(".")
        _validate_private_hostname(host, field="service host")
        return host in self.exact_hosts or any(host.endswith(suffix) for suffix in self.suffixes)


def _validate_private_hostname(host: str, *, field: str) -> None:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(f"{field} cannot be an IP literal")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"{field} cannot be localhost")
    labels = host.split(".")
    if len(labels) < 2 or any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or any(
            not (character.isascii() and (character.isalnum() or character == "-"))
            for character in label
        )
        for label in labels
    ):
        raise ValueError(f"{field} must be a bounded DNS hostname")


class KnowledgeModelWorkCancelled(RuntimeError):
    """Raised when scheduled private-model work is cooperatively cancelled."""


class KnowledgeModelCancellation:
    """Thread-safe cancellation signal shared with a scheduler wait handle."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_callback_id = 0

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = tuple(self._callbacks.values())
        for callback in callbacks:
            try:
                callback()
            except Exception:
                continue

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            if self._event.is_set():
                invoke_now = True
                callback_id = -1
            else:
                invoke_now = False
                self._next_callback_id += 1
                callback_id = self._next_callback_id
                self._callbacks[callback_id] = callback
        if invoke_now:
            callback()

        def unregister() -> None:
            with self._lock:
                self._callbacks.pop(callback_id, None)

        return unregister

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled():
            raise KnowledgeModelWorkCancelled("private Knowledge model work was cancelled")


class _PrivateModel(FrozenModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class EmbeddingRequest(_PrivateModel):
    texts: tuple[NonBlankStr, ...] = Field(min_length=1, max_length=128)
    model_revision: PinnedModelRevision
    instruction: InstructionStr
    dimension: PositiveInt = Field(le=4096)
    normalized: StrictBool

    @model_validator(mode="after")
    def validate_batch_size(self) -> "EmbeddingRequest":
        if sum(len(text) for text in self.texts) > MAX_EMBEDDING_BATCH_CHARACTERS:
            raise ValueError("embedding batch exceeds the aggregate character limit")
        return self


class EmbeddingTransportResponse(_PrivateModel):
    model_revision: PinnedModelRevision
    vectors: tuple[Vector, ...] = Field(min_length=1, max_length=128)


class EmbeddingResult(_PrivateModel):
    model_revision: PinnedModelRevision
    vectors: tuple[Vector, ...] = Field(min_length=1, max_length=128)
    queue_time_ms: StrictFloat = Field(ge=0)
    service_time_ms: StrictFloat = Field(ge=0)


class RerankCandidate(_PrivateModel):
    candidate_id: CandidateId
    text: NonBlankStr


class RerankerRequest(_PrivateModel):
    query: NonBlankStr
    candidates: tuple[RerankCandidate, ...] = Field(min_length=1, max_length=128)
    model_revision: PinnedModelRevision
    max_input_tokens: PositiveInt = Field(le=131_072)

    @model_validator(mode="after")
    def validate_candidates(self) -> "RerankerRequest":
        identities = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(identities) != len(set(identities)):
            raise ValueError("reranker candidate identities must be unique")
        if (
            len(self.query) + sum(len(candidate.text) for candidate in self.candidates)
            > MAX_RERANK_BATCH_CHARACTERS
        ):
            raise ValueError("reranker batch exceeds the aggregate character limit")
        return self


class RerankerTransportResponse(_PrivateModel):
    model_revision: PinnedModelRevision
    scores: tuple[tuple[CandidateId, StrictFloat], ...] = Field(min_length=1, max_length=128)


class RerankerResult(_PrivateModel):
    model_revision: PinnedModelRevision
    scores: tuple[tuple[CandidateId, StrictFloat], ...] = Field(min_length=1, max_length=128)
    queue_time_ms: StrictFloat = Field(ge=0)
    service_time_ms: StrictFloat = Field(ge=0)


class SchedulerLease(_PrivateModel):
    work_id: Annotated[
        StrictStr,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
    ]
    lease_token: Annotated[
        StrictStr,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
    ]
    queue_time_ms: StrictFloat = Field(ge=0)


class GuardedEmbeddingTransport(Protocol):
    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> EmbeddingTransportResponse: ...


class GuardedRerankerTransport(Protocol):
    def rerank(
        self,
        request: RerankerRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> RerankerTransportResponse: ...


class GuardedKnowledgeModelSchedulerTransport(Protocol):
    def acquire(
        self,
        *,
        endpoint: str,
        namespace: str,
        kind: WorkKind,
        priority: WorkPriority,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> SchedulerLease: ...

    def complete(
        self,
        endpoint: str,
        namespace: str,
        lease: SchedulerLease,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
    ) -> None: ...

    def cancel(
        self,
        endpoint: str,
        namespace: str,
        lease: SchedulerLease,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
    ) -> None: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ScheduledWorkResult(Generic[T]):
    value: T
    queue_time_ms: float
    service_time_ms: float


class KnowledgeModelWorkScheduler(Protocol):
    def submit_and_wait(
        self,
        *,
        kind: WorkKind,
        priority: WorkPriority,
        timeout_seconds: float,
        operation: Callable[[float, KnowledgeModelCancellation], T],
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> ScheduledWorkResult[T]: ...

    def close(self) -> None: ...


class ImmediateKnowledgeModelWorkScheduler:
    """Test-only scheduler that admits work synchronously."""

    def submit_and_wait(
        self,
        *,
        kind: WorkKind,
        priority: WorkPriority,
        timeout_seconds: float,
        operation: Callable[[float, KnowledgeModelCancellation], T],
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> ScheduledWorkResult[T]:
        del kind, priority
        _validate_timeout(timeout_seconds)
        token = cancellation or KnowledgeModelCancellation()
        token.raise_if_cancelled()
        started = monotonic()
        value = operation(timeout_seconds, token)
        token.raise_if_cancelled()
        elapsed = monotonic() - started
        if elapsed > timeout_seconds:
            raise TimeoutError("private Knowledge model service exceeded its timeout")
        return ScheduledWorkResult(
            value=value,
            queue_time_ms=0.0,
            service_time_ms=elapsed * 1000,
        )

    def close(self) -> None:
        return None


@dataclass
class InMemoryScheduledWork:
    """Mutable ticket exposed only by the test scheduler."""

    work_id: str
    kind: WorkKind
    priority: WorkPriority
    sequence: int
    state: Literal["queued", "claimed"] = "queued"


class InMemoryKnowledgeModelWorkScheduler(ImmediateKnowledgeModelWorkScheduler):
    """Test-only deterministic queue used to prove cross-kind priority policy."""

    def __init__(self) -> None:
        self._queue_lock = Lock()
        self._sequence = 0
        self._queued: list[InMemoryScheduledWork] = []
        self._closed = False

    def submit(self, *, kind: WorkKind, priority: WorkPriority) -> InMemoryScheduledWork:
        with self._queue_lock:
            if self._closed:
                raise RuntimeError("in-memory test scheduler is closed")
            self._sequence += 1
            work = InMemoryScheduledWork(
                work_id=f"test-work-{self._sequence}",
                kind=kind,
                priority=priority,
                sequence=self._sequence,
            )
            self._queued.append(work)
            return work

    def claim_next(self) -> InMemoryScheduledWork | None:
        with self._queue_lock:
            candidates = [work for work in self._queued if work.state == "queued"]
            if not candidates:
                return None
            work = min(
                candidates,
                key=lambda candidate: (
                    candidate.priority != "online",
                    candidate.sequence,
                ),
            )
            work.state = "claimed"
            return work

    def close(self) -> None:
        with self._queue_lock:
            self._closed = True


class PrivateKnowledgeModelWorkSchedulerClient:
    """Remote scheduler lease client shared by every private-model adapter."""

    def __init__(
        self,
        *,
        endpoint: str,
        namespace: str,
        allowed_hosts: PrivateHostPolicy,
        transport: GuardedKnowledgeModelSchedulerTransport,
    ) -> None:
        self.endpoint = _private_https_endpoint(
            endpoint,
            field="scheduler endpoint",
            allowed_hosts=allowed_hosts,
        )
        normalized_namespace = namespace.strip()
        if not normalized_namespace or len(normalized_namespace) > 128:
            raise ValueError("scheduler namespace must be non-empty and bounded")
        if any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for character in normalized_namespace
        ):
            raise ValueError("scheduler namespace contains unsupported characters")
        self.namespace = normalized_namespace
        self._transport = transport
        self._state = Condition()
        self._active_tokens: set[KnowledgeModelCancellation] = set()
        self._closing = False
        self._closed = False

    def submit_and_wait(
        self,
        *,
        kind: WorkKind,
        priority: WorkPriority,
        timeout_seconds: float,
        operation: Callable[[float, KnowledgeModelCancellation], T],
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> ScheduledWorkResult[T]:
        _validate_timeout(timeout_seconds)
        token = KnowledgeModelCancellation()
        with self._state:
            if self._closing or self._closed:
                raise RuntimeError("private Knowledge model scheduler client is closing")
            self._active_tokens.add(token)
        unregister = cancellation.register(token.cancel) if cancellation is not None else None
        try:
            token.raise_if_cancelled()
            deadline = monotonic() + timeout_seconds
            queue_started = monotonic()
            lease = self._acquire_cancellable(
                kind=kind,
                priority=priority,
                deadline=deadline,
                token=token,
            )
            measured_queue_time_ms = (monotonic() - queue_started) * 1000
            effective_queue_time_ms = max(lease.queue_time_ms, measured_queue_time_ms)
            remaining = min(
                deadline - monotonic(),
                timeout_seconds - effective_queue_time_ms / 1000,
            )
            if remaining <= 0:
                primary = TimeoutError(
                    "private Knowledge model scheduler queue exceeded its timeout"
                )
                self._cancel_lease_best_effort(
                    lease,
                    timeout_seconds=timeout_seconds,
                    primary=primary,
                )
                raise primary
            started = monotonic()
            try:
                value = self._run_service_cancellable(
                    operation=operation,
                    remaining=remaining,
                    token=token,
                )
            except BaseException as primary:
                self._cancel_lease_best_effort(
                    lease,
                    timeout_seconds=max(deadline - monotonic(), 0.001),
                    primary=primary,
                )
                raise
            service_time_ms = (monotonic() - started) * 1000
            try:
                token.raise_if_cancelled()
            except BaseException as primary:
                self._cancel_lease_best_effort(
                    lease,
                    timeout_seconds=max(deadline - monotonic(), 0.001),
                    primary=primary,
                )
                raise
            if service_time_ms / 1000 > remaining:
                timeout_error = TimeoutError("private Knowledge model service exceeded its timeout")
                self._cancel_lease_best_effort(
                    lease,
                    timeout_seconds=max(deadline - monotonic(), 0.001),
                    primary=timeout_error,
                )
                raise timeout_error
            try:
                self._transport.complete(
                    self.endpoint,
                    self.namespace,
                    lease,
                    timeout_seconds=max(deadline - monotonic(), 0.001),
                    follow_redirects=False,
                )
            except BaseException as primary:
                self._cancel_lease_best_effort(
                    lease,
                    timeout_seconds=max(deadline - monotonic(), 0.001),
                    primary=primary,
                )
                raise
            return ScheduledWorkResult(
                value=value,
                queue_time_ms=effective_queue_time_ms,
                service_time_ms=service_time_ms,
            )
        finally:
            if unregister is not None:
                unregister()
            with self._state:
                self._active_tokens.discard(token)
                self._state.notify_all()

    def _acquire_cancellable(
        self,
        *,
        kind: WorkKind,
        priority: WorkPriority,
        deadline: float,
        token: KnowledgeModelCancellation,
    ) -> SchedulerLease:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-scheduler")
        future = executor.submit(
            self._transport.acquire,
            endpoint=self.endpoint,
            namespace=self.namespace,
            kind=kind,
            priority=priority,
            timeout_seconds=max(deadline - monotonic(), 0.001),
            follow_redirects=False,
            cancellation=token,
        )
        try:
            lease = _await_cancellable_future(future, token=token, deadline=deadline)
            token.raise_if_cancelled()
            return lease
        except BaseException as primary:
            try:
                late_lease = future.result(timeout=0.25)
            except FutureTimeoutError:
                future.add_done_callback(
                    partial(
                        self._cancel_late_acquire,
                        primary=primary,
                    )
                )
            except BaseException:
                pass
            else:
                self._cancel_lease_best_effort(
                    late_lease,
                    timeout_seconds=1.0,
                    primary=primary,
                )
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_service_cancellable(
        self,
        *,
        operation: Callable[[float, KnowledgeModelCancellation], T],
        remaining: float,
        token: KnowledgeModelCancellation,
    ) -> T:
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="knowledge-model")
        future = executor.submit(operation, remaining, token)
        try:
            return _await_cancellable_future(
                future,
                token=token,
                deadline=monotonic() + remaining,
            )
        except BaseException as primary:
            future.cancel()
            try:
                future.result(timeout=0.25)
            except FutureTimeoutError:
                primary.add_note("cancelled model transport did not stop within 250 ms")
            except BaseException:
                pass
            raise
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _cancel_late_acquire(
        self,
        completed: Future[SchedulerLease],
        *,
        primary: BaseException,
    ) -> None:
        if completed.cancelled() or completed.exception() is not None:
            return
        self._cancel_lease_best_effort(
            completed.result(),
            timeout_seconds=1.0,
            primary=primary,
        )

    def _cancel_lease_best_effort(
        self,
        lease: SchedulerLease,
        *,
        timeout_seconds: float,
        primary: BaseException,
    ) -> None:
        try:
            self._transport.cancel(
                self.endpoint,
                self.namespace,
                lease,
                timeout_seconds=min(max(timeout_seconds, 0.001), 5.0),
                follow_redirects=False,
            )
        except Exception as cleanup_error:
            primary.add_note(f"scheduler lease cleanup also failed: {type(cleanup_error).__name__}")

    def close(self) -> None:
        with self._state:
            while self._closing and not self._closed:
                self._state.wait()
            if self._closed:
                return
            self._closing = True
            active = tuple(self._active_tokens)
        for token in active:
            token.cancel()
        deadline = monotonic() + 5.0
        with self._state:
            while self._active_tokens and monotonic() < deadline:
                self._state.wait(timeout=min(0.05, deadline - monotonic()))
        try:
            self._transport.close()
        except Exception:
            with self._state:
                self._closing = False
                self._state.notify_all()
            raise
        with self._state:
            self._closed = True
            self._closing = False
            self._state.notify_all()


def _await_cancellable_future(
    future: Future[T],
    *,
    token: KnowledgeModelCancellation,
    deadline: float,
) -> T:
    while True:
        token.raise_if_cancelled()
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("private Knowledge model work exceeded its timeout")
        try:
            return future.result(timeout=min(0.02, remaining))
        except FutureTimeoutError:
            continue


def _private_https_endpoint(
    value: str,
    *,
    field: str,
    allowed_hosts: PrivateHostPolicy,
) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlsplit(normalized)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{field} must use a valid HTTPS port") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field} must be a secret-free HTTPS service origin")
    if not allowed_hosts.allows(parsed.hostname):
        raise ValueError(f"{field} host is not in the private service allowlist")
    return normalized


def _validate_timeout(timeout_seconds: float) -> None:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= MAX_MODEL_TIMEOUT_SECONDS
    ):
        raise ValueError(f"timeout_seconds must be between 0 and {MAX_MODEL_TIMEOUT_SECONDS:g}")


def _raise_mapped_httpx_failure(exc: Exception) -> None:
    """Map optional-httpx failures onto worker-safe built-in error classes."""

    if not type(exc).__module__.startswith("httpx"):
        return
    if "timeout" in type(exc).__name__.lower():
        raise TimeoutError("private Knowledge service timed out") from exc
    raise ConnectionError("private Knowledge service connection failed") from exc


def decode_bounded_json_bytes(content: bytes | bytearray) -> JsonValue:
    """Decode strict JSON and reject structurally abusive or non-finite payloads."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is forbidden: {value}")

    try:
        value = cast(JsonValue, json.loads(content, parse_constant=reject_constant))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError("private Knowledge service returned invalid bounded JSON") from exc
    validate_bounded_json(value)
    return value


def validate_bounded_json(value: JsonValue) -> None:
    pending: list[tuple[JsonValue, int]] = [(value, 1)]
    visited = 0
    while pending:
        current, depth = pending.pop()
        visited += 1
        if visited > MAX_MODEL_JSON_NODES:
            raise ValueError("private Knowledge JSON exceeds the node limit")
        if depth > MAX_MODEL_JSON_DEPTH:
            raise ValueError("private Knowledge JSON exceeds the nesting-depth limit")
        if isinstance(current, str):
            if len(current) > MAX_MODEL_JSON_STRING_CHARACTERS:
                raise ValueError("private Knowledge JSON string exceeds the character limit")
        elif isinstance(current, list):
            if len(current) > MAX_MODEL_JSON_COLLECTION_ITEMS:
                raise ValueError("private Knowledge JSON array exceeds the item limit")
            pending.extend((item, depth + 1) for item in current)
        elif isinstance(current, dict):
            if len(current) > MAX_MODEL_JSON_COLLECTION_ITEMS:
                raise ValueError("private Knowledge JSON object exceeds the item limit")
            for key, item in current.items():
                if len(key) > MAX_MODEL_JSON_STRING_CHARACTERS:
                    raise ValueError("private Knowledge JSON key exceeds the character limit")
                pending.append((item, depth + 1))
        elif isinstance(current, float) and not math.isfinite(current):
            raise ValueError("private Knowledge JSON numbers must be finite")


class _HttpJsonTransport:
    """Small guarded HTTP boundary: HTTPS only, no redirects, proxies, or retries."""

    def __init__(self, *, max_response_bytes: int) -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - optional production dependency
            raise ImportError("Hybrid private-model HTTP support requires httpx") from exc
        self._httpx = httpx
        self._max_response_bytes = max_response_bytes
        self._state = Condition()
        self._active_clients: set[object] = set()
        self._closing = False
        self._closed = False

    def _post(
        self,
        url: str,
        payload: object,
        *,
        timeout_seconds: float,
        expect_json: bool = True,
        cancellation: KnowledgeModelCancellation,
    ) -> object:
        client = self._httpx.Client(follow_redirects=False, trust_env=False)
        with self._state:
            if self._closing or self._closed:
                client.close()
                raise RuntimeError("private Knowledge HTTP transport is closing")
            self._active_clients.add(client)
        unregister = cancellation.register(client.close)
        try:
            with client.stream("POST", url, json=payload, timeout=timeout_seconds) as response:
                if 300 <= response.status_code < 400:
                    raise ValueError("private Knowledge service redirects are forbidden")
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    raise ConnectionError("private Knowledge service is temporarily unavailable")
                if response.status_code >= 400:
                    raise ValueError("private Knowledge service rejected the typed request")
                declared_length = response.headers.get("content-length")
                if declared_length is not None:
                    try:
                        parsed_length = int(declared_length)
                    except ValueError as exc:
                        raise ValueError(
                            "private Knowledge service returned invalid Content-Length"
                        ) from exc
                    if not 0 <= parsed_length <= self._max_response_bytes:
                        raise ValueError(
                            "private Knowledge service response exceeds its byte limit"
                        )
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > self._max_response_bytes:
                        raise ValueError(
                            "private Knowledge service response exceeds its byte limit"
                        )
        except Exception as exc:
            _raise_mapped_httpx_failure(exc)
            raise
        finally:
            unregister()
            client.close()
            with self._state:
                self._active_clients.discard(client)
                self._state.notify_all()
        if not expect_json:
            return None
        return decode_bounded_json_bytes(content)

    def close(self) -> None:
        with self._state:
            if self._closed:
                return
            self._closing = True
            active = tuple(self._active_clients)
        for client in active:
            close = getattr(client, "close", None)
            if close is not None:
                close()
        deadline = monotonic() + 5.0
        with self._state:
            while self._active_clients and monotonic() < deadline:
                self._state.wait(timeout=min(0.05, deadline - monotonic()))
            self._closed = True


class HttpKnowledgeModelSchedulerTransport(_HttpJsonTransport):
    """Guarded HTTP implementation of the remote scheduler lease protocol."""

    def __init__(self) -> None:
        super().__init__(max_response_bytes=64 * 1024)

    def acquire(
        self,
        *,
        endpoint: str,
        namespace: str,
        kind: WorkKind,
        priority: WorkPriority,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> SchedulerLease:
        if follow_redirects is not False:
            raise ValueError("scheduler redirects are forbidden")
        payload = self._post(
            f"{endpoint}/v1/work/acquire",
            {
                "namespace": namespace,
                "kind": kind,
                "priority": priority,
                "timeout_seconds": timeout_seconds,
            },
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )
        return SchedulerLease.model_validate(payload)

    def complete(
        self,
        endpoint: str,
        namespace: str,
        lease: SchedulerLease,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
    ) -> None:
        if follow_redirects is not False:
            raise ValueError("scheduler redirects are forbidden")
        self._post(
            f"{endpoint}/v1/work/complete",
            {
                "namespace": namespace,
                "work_id": lease.work_id,
                "lease_token": lease.lease_token,
            },
            timeout_seconds=timeout_seconds,
            expect_json=False,
            cancellation=KnowledgeModelCancellation(),
        )

    def cancel(
        self,
        endpoint: str,
        namespace: str,
        lease: SchedulerLease,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
    ) -> None:
        if follow_redirects is not False:
            raise ValueError("scheduler redirects are forbidden")
        self._post(
            f"{endpoint}/v1/work/cancel",
            {
                "namespace": namespace,
                "work_id": lease.work_id,
                "lease_token": lease.lease_token,
            },
            timeout_seconds=timeout_seconds,
            expect_json=False,
            cancellation=KnowledgeModelCancellation(),
        )


class HttpEmbeddingTransport(_HttpJsonTransport):
    """Guarded transport for one pinned private embedding service."""

    def __init__(self, *, endpoint: str, allowed_hosts: PrivateHostPolicy) -> None:
        super().__init__(max_response_bytes=64 * 1024 * 1024)
        self._endpoint = _private_https_endpoint(
            endpoint,
            field="embedding endpoint",
            allowed_hosts=allowed_hosts,
        )

    def embed(
        self,
        request: EmbeddingRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> EmbeddingTransportResponse:
        if follow_redirects is not False or allow_runtime_downloads is not False:
            raise ValueError("embedding redirects and runtime downloads are forbidden")
        payload = request.model_dump(mode="json")
        payload["allow_runtime_downloads"] = False
        response = self._post(
            f"{self._endpoint}/v1/embeddings",
            payload,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )
        return EmbeddingTransportResponse.model_validate(response)


class HttpRerankerTransport(_HttpJsonTransport):
    """Guarded transport for one pinned private reranker service."""

    def __init__(self, *, endpoint: str, allowed_hosts: PrivateHostPolicy) -> None:
        super().__init__(max_response_bytes=16 * 1024 * 1024)
        self._endpoint = _private_https_endpoint(
            endpoint,
            field="reranker endpoint",
            allowed_hosts=allowed_hosts,
        )

    def rerank(
        self,
        request: RerankerRequest,
        *,
        timeout_seconds: float,
        follow_redirects: Literal[False],
        allow_runtime_downloads: Literal[False],
        cancellation: KnowledgeModelCancellation,
    ) -> RerankerTransportResponse:
        if follow_redirects is not False or allow_runtime_downloads is not False:
            raise ValueError("reranker redirects and runtime downloads are forbidden")
        payload = request.model_dump(mode="json")
        payload["allow_runtime_downloads"] = False
        response = self._post(
            f"{self._endpoint}/v1/rerank",
            payload,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
        )
        return RerankerTransportResponse.model_validate(response)


class PrivateEmbeddingClient:
    """Transport-only embedding client admitted through one scheduler port."""

    def __init__(
        self,
        *,
        transport: GuardedEmbeddingTransport,
        scheduler: KnowledgeModelWorkScheduler,
    ) -> None:
        self._transport = transport
        self.scheduler = scheduler

    def embed(
        self,
        *,
        texts: tuple[str, ...],
        model_revision: str,
        instruction: str,
        dimension: int,
        normalized: bool,
        priority: WorkPriority,
        timeout_seconds: float,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> EmbeddingResult:
        request = EmbeddingRequest(
            texts=texts,
            model_revision=model_revision,
            instruction=instruction,
            dimension=dimension,
            normalized=normalized,
        )
        scheduled = self.scheduler.submit_and_wait(
            kind="embedding",
            priority=priority,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
            operation=lambda remaining, scheduled_cancellation: self._transport.embed(
                request,
                timeout_seconds=remaining,
                follow_redirects=False,
                allow_runtime_downloads=False,
                cancellation=scheduled_cancellation,
            ),
        )
        response = scheduled.value
        if response.model_revision != request.model_revision:
            raise ValueError("embedding response model_revision must match the exact request")
        if len(response.vectors) != len(request.texts):
            raise ValueError("embedding response vector count must match the request")
        for vector in response.vectors:
            if len(vector) != request.dimension:
                raise ValueError("embedding response vector dimension must match the request")
            if any(not math.isfinite(value) for value in vector):
                raise ValueError("embedding response vectors must contain finite numbers")
        return EmbeddingResult(
            model_revision=response.model_revision,
            vectors=response.vectors,
            queue_time_ms=scheduled.queue_time_ms,
            service_time_ms=scheduled.service_time_ms,
        )


class PrivateRerankerClient:
    """Transport-only reranker admitted through the shared scheduler."""

    def __init__(
        self,
        *,
        transport: GuardedRerankerTransport,
        scheduler: KnowledgeModelWorkScheduler,
    ) -> None:
        self._transport = transport
        self.scheduler = scheduler

    def rerank(
        self,
        *,
        query: str,
        candidates: tuple[RerankCandidate, ...],
        model_revision: str,
        max_input_tokens: int,
        priority: WorkPriority,
        timeout_seconds: float,
        cancellation: KnowledgeModelCancellation | None = None,
    ) -> RerankerResult:
        request = RerankerRequest(
            query=query,
            candidates=candidates,
            model_revision=model_revision,
            max_input_tokens=max_input_tokens,
        )
        scheduled = self.scheduler.submit_and_wait(
            kind="rerank",
            priority=priority,
            timeout_seconds=timeout_seconds,
            cancellation=cancellation,
            operation=lambda remaining, scheduled_cancellation: self._transport.rerank(
                request,
                timeout_seconds=remaining,
                follow_redirects=False,
                allow_runtime_downloads=False,
                cancellation=scheduled_cancellation,
            ),
        )
        response = scheduled.value
        if response.model_revision != request.model_revision:
            raise ValueError("reranker response model_revision must match the exact request")
        requested_ids = tuple(candidate.candidate_id for candidate in request.candidates)
        response_ids = tuple(candidate_id for candidate_id, _score in response.scores)
        if response_ids != requested_ids:
            raise ValueError("reranker response candidates must exactly echo request order")
        if any(not math.isfinite(score) for _candidate_id, score in response.scores):
            raise ValueError("reranker response scores must be finite")
        return RerankerResult(
            model_revision=response.model_revision,
            scores=response.scores,
            queue_time_ms=scheduled.queue_time_ms,
            service_time_ms=scheduled.service_time_ms,
        )
