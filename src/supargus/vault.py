"""Local identity vault helpers.

The first real backend is Windows DPAPI. It encrypts data for the current
Windows user account, so Supargus can protect identity files at rest without
asking users to manage another secret.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
from ctypes import wintypes
from pathlib import Path


VAULT_VERSION = 1
WINDOWS_DPAPI_BACKEND = "windows-dpapi-current-user"


class VaultUnavailableError(RuntimeError):
    """Raised when no secure local vault backend is available."""


class VaultFormatError(ValueError):
    """Raised when an encrypted vault file cannot be decoded."""


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def vault_available() -> bool:
    return _is_windows()


def _blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _bytes_from_blob(blob: DATA_BLOB) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _crypt_protect(data: bytes, label: str) -> bytes:
    if not _is_windows():
        raise VaultUnavailableError("Encrypted vaults currently require Windows DPAPI.")

    crypt32 = ctypes.windll.crypt32
    in_blob, in_buffer = _blob_from_bytes(data)
    entropy_blob, entropy_buffer = _blob_from_bytes(label.encode("utf-8"))
    out_blob = DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "Supargus identity vault",
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    # Keep buffers alive until the API call returns.
    _ = (in_buffer, entropy_buffer)
    if not ok:
        raise ctypes.WinError()
    return _bytes_from_blob(out_blob)


def _crypt_unprotect(data: bytes, label: str) -> bytes:
    if not _is_windows():
        raise VaultUnavailableError("Encrypted vaults currently require Windows DPAPI.")

    crypt32 = ctypes.windll.crypt32
    in_blob, in_buffer = _blob_from_bytes(data)
    entropy_blob, entropy_buffer = _blob_from_bytes(label.encode("utf-8"))
    out_blob = DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    _ = (in_buffer, entropy_buffer)
    if not ok:
        raise ctypes.WinError()
    return _bytes_from_blob(out_blob)


def seal_bytes(data: bytes, *, label: str = "identity") -> dict:
    encrypted = _crypt_protect(data, label)
    return {
        "supargus_vault": VAULT_VERSION,
        "backend": WINDOWS_DPAPI_BACKEND,
        "label": label,
        "ciphertext": base64.b64encode(encrypted).decode("ascii"),
    }


def open_bytes(payload: dict) -> bytes:
    if payload.get("supargus_vault") != VAULT_VERSION:
        raise VaultFormatError("Unsupported Supargus vault version.")
    if payload.get("backend") != WINDOWS_DPAPI_BACKEND:
        raise VaultFormatError(f"Unsupported vault backend: {payload.get('backend')}")
    try:
        ciphertext = base64.b64decode(str(payload["ciphertext"]))
    except Exception as exc:
        raise VaultFormatError("Vault ciphertext is not valid base64.") from exc
    return _crypt_unprotect(ciphertext, str(payload.get("label", "identity")))


def seal_file(input_path: str | Path, output_path: str | Path, *, force: bool = False, label: str = "identity") -> Path:
    src = Path(input_path)
    dest = Path(output_path)
    if dest.exists() and not force:
        raise FileExistsError(f"{dest} already exists; pass --force to overwrite")
    payload = seal_bytes(src.read_bytes(), label=label)
    payload["source_name"] = src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def open_file(input_path: str | Path, output_path: str | Path, *, force: bool = False) -> Path:
    src = Path(input_path)
    dest = Path(output_path)
    if dest.exists() and not force:
        raise FileExistsError(f"{dest} already exists; pass --force to overwrite")
    payload = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise VaultFormatError("Vault file must contain an object.")
    data = open_bytes(payload)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def load_vault_identity_text(path: str | Path) -> str:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise VaultFormatError("Vault file must contain an object.")
    return open_bytes(payload).decode("utf-8")


def secure_delete_plaintext(path: str | Path) -> None:
    """Best-effort overwrite before delete for small local identity files."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return
    size = p.stat().st_size
    with p.open("r+b") as fh:
        fh.write(os.urandom(size))
        fh.flush()
        os.fsync(fh.fileno())
    p.unlink()

