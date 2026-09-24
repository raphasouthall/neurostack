# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Username and password login for `neurostack ui` (issue #251).

Users live in `ui-users.json` beside the index as scrypt hashes. A session is a
signed token with no server-side state. Its key mixes a per-install secret with
the user's stored hash, so changing or removing a user ends their sessions.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

SESSION_TTL = 30 * 24 * 3600
_N, _R, _P = 2**14, 8, 1


def _write_private(path: Path, data: bytes) -> None:
    """Replace `path` atomically with a file only its owner can read on POSIX."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _users_path(cfg) -> Path:
    return Path(cfg.db_dir) / "ui-users.json"


def _load(cfg) -> dict:
    try:
        return json.loads(_users_path(cfg).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


# ponytail: read-modify-write with no lock, so two `ui user add` runs at the
# same instant can drop one. Take a file lock if that ever happens.
def _save(cfg, users: dict) -> None:
    _write_private(_users_path(cfg), json.dumps(users, indent=2, sort_keys=True).encode())


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p)


def add_user(cfg, name: str, password: str) -> None:
    """Create the user, or replace their password."""
    if not name or any(c == "|" or c.isspace() for c in name):
        raise ValueError("a user name must be non-empty with no whitespace or |")
    if len(password) < 8:
        raise ValueError("a password needs at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _N, _R, _P)
    users = _load(cfg)
    users[name] = f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"
    _save(cfg, users)


def remove_user(cfg, name: str) -> bool:
    users = _load(cfg)
    if users.pop(name, None) is None:
        return False
    _save(cfg, users)
    return True


def list_users(cfg) -> list[str]:
    return sorted(_load(cfg))


def verify(cfg, name: str, password: str) -> bool:
    stored = _load(cfg).get(name)
    if stored is None:
        # Hash anyway, so a wrong name takes as long as a wrong password.
        _scrypt(password, bytes(16), _N, _R, _P)
        return False
    _, n, r, p, salt, want = stored.split("$")
    got = _scrypt(password, bytes.fromhex(salt), int(n), int(r), int(p))
    return hmac.compare_digest(got, bytes.fromhex(want))


def _secret(cfg) -> bytes:
    path = Path(cfg.db_dir) / "ui-secret"
    if not path.exists():
        _write_private(path, secrets.token_bytes(32))
    return path.read_bytes()


def _mac(cfg, stored: str, msg: str) -> bytes:
    key = hmac.new(_secret(cfg), stored.encode(), hashlib.sha256).digest()
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest().encode()


def make_session(cfg, name: str, now: float | None = None) -> str:
    """A cookie token for `name`, valid for SESSION_TTL seconds from `now`."""
    msg = f"{name}|{int((time.time() if now is None else now) + SESSION_TTL)}"
    token = f"{msg}|{_mac(cfg, _load(cfg)[name], msg).decode()}"
    return base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")


def check_session(cfg, token: str, now: float | None = None) -> str | None:
    """The user a token signs in, or None when it is bad, expired or revoked."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        name, expiry, mac = raw.split("|")
        expired = int(expiry) <= (time.time() if now is None else now)
    except ValueError:
        return None
    stored = _load(cfg).get(name)
    if expired or stored is None:
        return None
    ok = hmac.compare_digest(mac.encode(), _mac(cfg, stored, f"{name}|{expiry}"))
    return name if ok else None
