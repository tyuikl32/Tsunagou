import pytest

from tsunagou.platform.audit_cursor import AuditCursorCodec


def test_cursor_binds_snapshot_and_all_query_identity() -> None:
    codec = AuditCursorCodec(clock=lambda: 1000)
    context: dict[str, object] = {
        "project_id": "p1", "lineage_id": "l1", "viewer": "agent/a1/session/s1/epoch/2",
        "from": 100, "to": 1000, "actor": "agent/a2", "subject": None, "limit": 200, "sort": "event_seq",
    }
    token = codec.encode(context=context, after_seq=200, as_of_event_seq=501)
    assert len(token) < 2048
    assert codec.decode(token, context=context) == (200, 501)
    for key in context:
        with pytest.raises(ValueError, match="invalid_audit_cursor"):
            codec.decode(token, context={**context, key: "changed"})
    with pytest.raises(ValueError, match="invalid_audit_cursor"):
        AuditCursorCodec().decode(token, context=context)


def test_cursor_expires_and_rejects_tampering_and_unbounded_input() -> None:
    current = 1000
    codec = AuditCursorCodec(clock=lambda: current)
    token = codec.encode(context={}, after_seq=2, as_of_event_seq=3)
    current += 899_999
    assert codec.decode(token, context={}) == (2, 3)
    current += 1
    with pytest.raises(ValueError, match="expired_audit_cursor"):
        codec.decode(token, context={})
    for bad in ("", "x" * 2049, "!", "A" + token[1:], token[:-10]):
        with pytest.raises(ValueError, match="invalid_audit_cursor"):
            codec.decode(bad, context={})
    with pytest.raises(ValueError, match="invalid_audit_cursor_position"):
        codec.encode(context={}, after_seq=4, as_of_event_seq=3)
