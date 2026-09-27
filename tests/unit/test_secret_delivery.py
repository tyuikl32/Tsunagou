import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tsunagou.platform import private_files
from tsunagou.platform.delivery import SecretDeliveryStore
from tsunagou.platform.private_files import protect_bytes, unprotect_bytes, write_private_bytes

BINDING = {"project_id": "project-1", "principal_id": "agent-1", "command_kind": "session.reconnect",
           "command_id": "command-1", "input_hash": "sha256:fixture"}
SECRET = {"secret_token": "test-secret-sentinel-private", "reconnect_nonce": "test-nonce-private"}


def test_delivery_replay_restart_ack_and_actual_local_protection(tmp_path: Path) -> None:
    store = SecretDeliveryStore(tmp_path / "vault", clock=lambda: 1000)
    receipt = store.put(SECRET, binding=BINDING)
    ref = receipt["delivery_ref"]
    assert receipt["delivery_status"] == "pending"
    assert "secret" not in json.dumps(receipt)
    assert store.read(ref, binding=BINDING) == SECRET
    restarted = SecretDeliveryStore(store.root, clock=lambda: 1001)
    assert restarted.read(ref, binding=BINDING) == SECRET
    path = next(store.root.glob("*.bin"))
    if os.name == "nt":
        assert b"test-secret-sentinel-private" not in path.read_bytes()
        assert path.read_bytes().startswith(b"DPAPI1\0")
        acl = subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True).stdout
        assert "Authenticated Users" not in acl and r"\Users:" not in acl
    else:
        assert path.stat().st_mode & 0o777 == 0o600
        assert store.root.stat().st_mode & 0o777 == 0o700
    confirmed = restarted.acknowledge(ref, binding=BINDING)
    assert confirmed["consumed_at"] == 1001 and confirmed["delivery_status"] == "consumed"
    assert restarted.acknowledge(ref, binding=BINDING) == confirmed
    assert b"test-secret-sentinel-private" not in unprotect_bytes(path.read_bytes())
    with pytest.raises(RuntimeError, match="secret_delivery_consumed"):
        restarted.read(ref, binding=BINDING)


def test_delivery_exact_scope_ttl_recovery_window_and_revocation(tmp_path: Path) -> None:
    current = 1000
    store = SecretDeliveryStore(tmp_path / "vault", clock=lambda: current)
    ref = store.put(SECRET, binding=BINDING)["delivery_ref"]
    for key in BINDING:
        for operation in (store.read, store.metadata, store.acknowledge, store.revoke):
            with pytest.raises(PermissionError, match="secret_delivery_scope_denied"):
                operation(ref, binding={**BINDING, key: "other"})
    with pytest.raises(RuntimeError, match="secret_delivery_not_delivered"):
        store.acknowledge(ref, binding=BINDING)
    current += 599_999
    assert store.read(ref, binding=BINDING) == SECRET
    current += 1
    with pytest.raises(RuntimeError, match="secret_delivery_expired"):
        store.read(ref, binding=BINDING)
    assert store.metadata(ref, binding=BINDING)["delivery_status"] == "expired"
    ref = store.put(SECRET, binding=BINDING)["delivery_ref"]
    store.read(ref, binding=BINDING)
    current += 120_000
    with pytest.raises(RuntimeError, match="secret_delivery_expired"):
        store.read(ref, binding=BINDING)
    ref = store.put(SECRET, binding=BINDING)["delivery_ref"]
    assert store.revoke(ref, binding=BINDING)["revoked_at"] == current
    with pytest.raises(RuntimeError, match="secret_delivery_revoked"):
        store.read(ref, binding=BINDING)


@pytest.mark.parametrize("ref", ["delivery:../outside", "delivery:/root", "delivery:..\\outside",
                                "delivery:" + "A" * 3000, "delivery:C:\\outside", "not-a-delivery"])
def test_delivery_ref_rejects_path_traversal(tmp_path: Path, ref: str) -> None:
    store = SecretDeliveryStore(tmp_path / "vault")
    with pytest.raises(ValueError, match="invalid_delivery_ref"):
        store.read(ref, binding=BINDING)


def test_acl_failure_never_writes_secret_or_replaces_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "private.bin"
    write_private_bytes(target, b"old safe bytes")

    def reject(_: Path, **kwargs: object) -> None:
        raise RuntimeError("private_file_acl_failed")

    monkeypatch.setattr(private_files, "restrict_access", reject)
    with pytest.raises(RuntimeError, match="private_file_acl_failed"):
        write_private_bytes(target, b"new secret bytes")
    assert list(tmp_path.iterdir()) == [target]
    assert target.read_bytes() == b"old safe bytes"


def test_private_blob_wrong_format_and_windows_tampering_fail_closed() -> None:
    protected = protect_bytes(b"private fixture")
    assert unprotect_bytes(protected) == b"private fixture"
    with pytest.raises(RuntimeError, match="private_blob_protection_mismatch"):
        unprotect_bytes(b"plaintext is not accepted")
    if os.name == "nt":
        damaged = bytearray(protected)
        damaged[-1] ^= 1
        with pytest.raises(RuntimeError, match="private_blob_decryption_failed"):
            unprotect_bytes(bytes(damaged))


@pytest.mark.skipif(os.name != "nt", reason="Windows DACL regression")
def test_existing_vault_explicit_everyone_grant_is_removed(tmp_path: Path) -> None:
    vault = tmp_path / "existing-vault"
    vault.mkdir()
    subprocess.run(["icacls", str(vault), "/grant", "*S-1-1-0:(OI)(CI)(R)"], capture_output=True, check=True)
    SecretDeliveryStore(vault)
    saved_acl = tmp_path / "acl.txt"
    subprocess.run(["icacls", str(vault), "/save", str(saved_acl)], capture_output=True, check=True)
    acl = saved_acl.read_text(encoding="utf-16-le")
    assert re.findall(r"\(A;[^)]*\)", acl) == [f"(A;OICI;FA;;;{private_files._current_user_sid()})"]
