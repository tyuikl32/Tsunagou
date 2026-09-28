"""Small local protection boundary for credential escrow and private backups."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _current_user_sid() -> str:
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, check=False)
    match = re.search(rb"S-1-\d+(?:-\d+)+", result.stdout)
    if result.returncode or match is None:
        raise RuntimeError("private_file_identity_unavailable")
    return match[0].decode("ascii")


def restrict_access(path: Path, *, directory: bool = False) -> None:
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    # Replace the complete DACL, not only this user's ACE. icacls /grant:r
    # retains explicit Everyone/Users grants on an existing vault directory.
    # Apply a protected owner-only DACL in one operation, avoiding a temporary
    # broad inherited ACL and leaving the previous ACL intact on failure.
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = ctypes.c_int
    get_dacl = advapi.GetSecurityDescriptorDacl
    get_dacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_int)]
    get_dacl.restype = ctypes.c_int
    set_security = advapi.SetNamedSecurityInfoW
    set_security.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_uint32,
                             ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    set_security.restype = ctypes.c_uint32
    descriptor = ctypes.c_void_p()
    inheritance = "OICI" if directory else ""
    sddl = f"D:P(A;{inheritance};FA;;;{_current_user_sid()})"
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise RuntimeError("private_file_acl_failed")
    try:
        present, defaulted, dacl = ctypes.c_int(), ctypes.c_int(), ctypes.c_void_p()
        if (not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted))
                or not present.value or not dacl.value):
            raise RuntimeError("private_file_acl_failed")
        # SE_FILE_OBJECT=1, DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION.
        if set_security(str(path), 1, 0x80000004, None, None, dacl, None):
            raise RuntimeError("private_file_acl_failed")
    finally:
        kernel.LocalFree(descriptor)


def write_private_bytes(path: Path, data: bytes) -> None:
    """Apply ACL before writing; flush and replace within the private directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("private_path_symlink_denied")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            restrict_access(temporary)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class _Blob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, decrypt: bool) -> bytes:
    # Current-user DPAPI; LOCAL_MACHINE would expose it to other local accounts.
    # The Win32-owned output buffer must be released even if conversion fails.
    loader = ctypes.WinDLL
    crypt32 = loader("crypt32", use_last_error=True)
    kernel32 = loader("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    source_buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError("private_blob_decryption_failed" if decrypt else "private_blob_encryption_failed")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def protect_bytes(value: bytes) -> bytes:
    return b"DPAPI1\0" + _dpapi(value, decrypt=False) if os.name == "nt" else b"PRIVATE1\0" + value


def unprotect_bytes(value: bytes) -> bytes:
    if os.name == "nt" and value.startswith(b"DPAPI1\0"):
        return _dpapi(value[7:], decrypt=True)
    if os.name != "nt" and value.startswith(b"PRIVATE1\0"):
        return value[9:]
    raise RuntimeError("private_blob_protection_mismatch")
