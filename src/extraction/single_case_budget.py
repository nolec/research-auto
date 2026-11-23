"""POSIX one-shot request custody; no model, network, CLI, or automatic initialization.

An explicitly approved initializer creates custody once. Execution only opens existing
custody, durably spends it, and invokes one injected sender. The sender must itself be
reviewed as one request with no retry/redirect/model callbacks; this layer cannot prove
provider-internal behavior. Deleting/restoring custody or minting another approval is
outside this cooperative local boundary and must never be used to reset an experiment.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Callable, Iterator, Mapping, TypeVar


class BudgetBlocked(RuntimeError):
    """Custody cannot authorize a send; never recreate or refund it automatically."""


_HASH_FIELDS = {"source_sha256", "prompt_sha256", "schema_sha256", "code_sha256",
                "request_sha256"}
_FIELDS = _HASH_FIELDS | {"approval_id", "document_id", "model", "max_requests"}
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_Result = TypeVar("_Result")


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _binding(value: Mapping[str, object]) -> dict[str, object]:
    frozen = dict(value)
    if set(frozen) != _FIELDS or type(frozen.get("max_requests")) is not int or frozen["max_requests"] != 1:
        raise BudgetBlocked("binding fields or request limit invalid")
    if any(not isinstance(frozen[key], str) or not re.fullmatch("[0-9a-f]{64}", frozen[key])
           for key in _HASH_FIELDS):
        raise BudgetBlocked("binding hash invalid")
    if any(not isinstance(frozen[key], str) or not frozen[key].strip() or len(frozen[key]) > 256
           for key in ("approval_id", "document_id", "model")):
        raise BudgetBlocked("binding identity invalid")
    return frozen


def _digest(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


@contextmanager
def _directory(path: Path) -> Iterator[int]:
    """Open every component without following directory links, including parents."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise BudgetBlocked("custody path must be absolute and contain no parent traversal")
    fd = os.open("/", _DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, _DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _sync_directory(fd: int) -> None:
    os.fsync(fd)


def _regular(fd: int) -> None:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_mode & 0o077:
        raise BudgetBlocked("custody must be a private, unlinked regular file")


def _write_record(fd: int, value: object) -> None:
    data = canonical_json(value)
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    while data:
        count = os.write(fd, data)
        if count <= 0:
            raise OSError("short custody write")
        data = data[count:]
    os.fsync(fd)


def _create(directory: int, name: str, value: object) -> None:
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                 dir_fd=directory)
    try:
        _write_record(fd, value)
    finally:
        os.close(fd)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise BudgetBlocked("duplicate custody key")
        result[key] = value
    return result


def _read(fd: int) -> object:
    _regular(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    raw = os.read(fd, 8193)
    if not raw or len(raw) > 8192:
        raise BudgetBlocked("empty or oversized custody")
    return json.loads(raw, object_pairs_hook=_unique_pairs)


def _read_named(directory: int, name: str) -> object:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        return _read(fd)
    finally:
        os.close(fd)


def initialize_budget(root: Path, binding: Mapping[str, object]) -> str:
    """Separate approval-only operation; existing/partial roots are never replaced.

    Parent must already exist. A failed initialization is intentionally left sealed
    off; execution requires all records including the last-published ready marker.
    Return the caller-held completion token only after all initialization and sync
    operations succeed. Custody stores its hash, never the token itself. The caller
    must explicitly hand this token to a later process; loss means stop, not recovery.
    No source text, API credentials, or model output is retained here.
    """
    root = Path(root)
    frozen = _binding(binding)
    digest = _digest(frozen)
    completion_token = secrets.token_hex(32)
    completion_sha256 = sha256(completion_token.encode("ascii")).hexdigest()
    try:
        with _directory(root.parent) as parent:
            os.mkdir(root.name, 0o700, dir_fd=parent)
            with _directory(root) as directory:
                _create(directory, "approval.json", frozen)
                _create(directory, "lock", {"binding_sha256": digest})
                lock = os.open("lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
                try:
                    _regular(lock)
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    try:
                        _create(directory, "state.json", {"binding_sha256": digest, "status": "UNUSED"})
                        _sync_directory(directory)
                        _create(directory, "ready.json", {"binding_sha256": digest,
                                                           "completion_sha256": completion_sha256})
                        _sync_directory(directory)
                        _sync_directory(parent)
                    except BaseException:
                        # A readable ready marker is not proof of successful sync.
                        # Keep the execution lock until it has been invalidated.
                        try:
                            os.rename("ready.json", "incomplete-ready.json",
                                      src_dir_fd=directory, dst_dir_fd=directory)
                        except FileNotFoundError:
                            pass  # No ready marker was ever published.
                        except OSError:
                            # If directory mutation is unavailable, poison the existing
                            # state in place. A partial write is invalid and fails closed.
                            state = os.open("state.json", os.O_WRONLY | os.O_NOFOLLOW,
                                            dir_fd=directory)
                            try:
                                _regular(state)
                                _write_record(state, {"binding_sha256": digest, "status": "FAILED"})
                            finally:
                                os.close(state)
                        _sync_directory(directory)
                        raise
                finally:
                    os.close(lock)
    except (OSError, ValueError, TypeError) as error:
        raise BudgetBlocked("initialization failed; preserve partial custody, do not retry") from error
    return completion_token


@contextmanager
def _spend(root: Path, frozen: dict[str, object], completion_sha256: str) -> Iterator[None]:
    digest = _digest(frozen)
    # O_NOFOLLOW and no O_CREAT: an executor cannot repair any missing artifact.
    try:
        with _directory(root) as directory:
            if os.fstat(directory).st_mode & 0o077:
                raise BudgetBlocked("custody directory must be private")
            lock = os.open("lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                _regular(lock)
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if (_read(lock) != {"binding_sha256": digest}
                    or _read_named(directory, "ready.json") != {"binding_sha256": digest,
                                                               "completion_sha256": completion_sha256}
                    or _read_named(directory, "approval.json") != frozen):
                    raise BudgetBlocked("approval binding mismatch")
                state = os.open("state.json", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                dir_fd=directory)
                try:
                    if _read(state) != {"binding_sha256": digest, "status": "UNUSED"}:
                        raise BudgetBlocked("budget already spent or state invalid")
                    # Exclusive marker survives a torn state update; never remove it.
                    _create(directory, "consumed.json", {"binding_sha256": digest, "status": "SPENT"})
                    _write_record(state, {"binding_sha256": digest, "status": "SPENT"})
                    _sync_directory(directory)
                finally:
                    os.close(state)
            except (OSError, ValueError, TypeError, UnicodeError) as error:
                raise BudgetBlocked("custody unavailable, consumed, corrupt, busy, or sync failed") from error
            else:
                # Sender exceptions are not converted, retried, repaired, or refunded.
                yield
            finally:
                os.close(lock)
    except OSError as error:
        # Only opening/closing custody belongs here; preserve sender exceptions below.
        raise BudgetBlocked("custody directory unavailable; do not initialize") from error


def send_once(root: Path, binding: Mapping[str, object], payload: Mapping[str, object],
              sender: Callable[[dict[str, object]], _Result], *,
              completion_token: str | None = None) -> _Result:
    """Require returned completion evidence, then spend before one sender invocation.

    Never derive completion evidence from ready.json or regenerate a missing token.
    This bounds sender invocations, not unobserved provider-internal calls.
    """
    if not isinstance(completion_token, str) or not re.fullmatch("[0-9a-f]{64}", completion_token):
        raise BudgetBlocked("returned initialization completion token required; do not recover")
    completion_sha256 = sha256(completion_token.encode("ascii")).hexdigest()
    frozen = _binding(binding)
    request = copy.deepcopy(dict(payload))
    if request.get("document_id") != frozen["document_id"] or _digest(request) != frozen["request_sha256"]:
        raise BudgetBlocked("request does not match approved payload")
    # Exit the custody context with no sender exception: these must propagate unchanged.
    result: _Result
    failure: BaseException | None = None
    with _spend(Path(root), frozen, completion_sha256):
        try:
            result = sender(request)
        except BaseException as error:
            failure = error
    if failure is not None:
        raise failure
    return result


def separate_assessments(model_output: Mapping[str, object], contract: Mapping[str, object],
                         content: Mapping[str, object], human_card: Mapping[str, object]) -> dict[str, object]:
    """Package supplied judgments without asserting schema or content validity.

    The canonical raw-output snapshot cannot be changed by edits to the human card.
    This performs no model evaluation or card generation and grants no PASS status.
    """
    return {"model_raw_json": canonical_json(model_output).decode("utf-8"),
            "model_contract": copy.deepcopy(dict(contract)),
            "model_content_quality": copy.deepcopy(dict(content)),
            "human_card": copy.deepcopy(dict(human_card))}
