from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from ctypes import wintypes
from pathlib import Path
import urllib.error
import urllib.request

VALIDATE_URL = "https://api.nexusmods.com/v1/users/validate.json"
USER_AGENT = "MO2AgentToolkit/0.2"


class AuthError(Exception):
    def __init__(self, message: str, code: int = 2, category: str = "authentication_error"):
        super().__init__(message)
        self.code = code
        self.category = category


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    account_name: str | None = None


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[DATA_BLOB, object]:
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def dpapi_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise AuthError("DPAPI authentication is only supported on Windows", 3, "unsupported_platform")
    source, keepalive = _blob(data)
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), "MO2AgentToolkit", None, None, None, 0, ctypes.byref(output)
    ):
        raise AuthError("Windows could not protect the Nexus credential", 3, "dpapi_error")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def dpapi_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise AuthError("DPAPI authentication is only supported on Windows", 3, "unsupported_platform")
    source, keepalive = _blob(data)
    output = DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise AuthError("Unable to decrypt Nexus credential for this Windows user", 3, "dpapi_error")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def normalize_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise AuthError("Nexus API key cannot be empty", 2, "invalid_input")
    if any(ch.isspace() for ch in key) or len(key) < 16 or len(key) > 256:
        raise AuthError("Nexus API key format is invalid", 2, "invalid_input")
    return key


def validate_key(key: str, timeout: float = 15.0) -> ValidationResult:
    request = urllib.request.Request(
        VALIDATE_URL,
        headers={"apikey": key, "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise AuthError("Nexus rejected the API key", 2, "invalid_credential")
            return ValidationResult(True)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise AuthError("Nexus API key is invalid or unauthorized", 2, "invalid_credential") from None
        raise AuthError(f"Nexus validation service returned HTTP {exc.code}", 4, "network_error") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise AuthError("Could not reach Nexus to validate the API key; retry when the network is available", 4, "network_error") from None


def save_key(key: str, path: Path) -> None:
    normalized = normalize_key(key)
    encrypted = dpapi_protect(normalized.encode("utf-8"))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(encrypted)
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise AuthError("Could not save the protected Nexus credential", 5, "filesystem_error") from None


def validate_and_save(key: str, path: Path) -> None:
    normalized = normalize_key(key)
    validate_key(normalized)
    save_key(normalized, path)


def credential_status(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"configured": False, "provider": "windows_dpapi", "decryptable": False}
    try:
        value = dpapi_unprotect(path.read_bytes()).decode("utf-8")
        decryptable = bool(value)
    except (AuthError, OSError, UnicodeDecodeError):
        decryptable = False
    return {"configured": True, "provider": "windows_dpapi", "decryptable": decryptable}


def remove_key(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        raise AuthError("Could not remove the protected Nexus credential", 5, "filesystem_error") from None
