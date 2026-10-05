"""The wildcard rule lives in one place, and everyone who dials uses it."""


def test_a_wildcard_bind_address_is_not_something_a_client_can_dial() -> None:
    from tsunagou.platform.endpoints import connectable_url

    assert connectable_url("http://0.0.0.0:2810") == "http://127.0.0.1:2810"
    assert connectable_url("http://[::]:2810") == "http://[::1]:2810"
    assert connectable_url("http://:2810") == "http://127.0.0.1:2810"
    assert connectable_url("http://192.168.32.1:2810") == "http://192.168.32.1:2810"
    assert connectable_url("https://box.example.com:8443") == "https://box.example.com:8443"
    assert connectable_url("") == ""
    # No host at all counts as a wildcard too (that is what "http://:2810" is); callers onlyever pass addresses out of a manifest or an invitation, so this branch is about not throwing.


def test_the_cli_and_the_console_use_the_same_rule() -> None:
    from tsunagou.cli.app import _probe_url
    from tsunagou.console.projects import connectable_url
    from tsunagou.platform.endpoints import connectable_url as shared

    for value in ("http://0.0.0.0:2810", "http://[::]:2810", "http://192.168.32.1:2810"):
        assert _probe_url(value) == shared(value)
        assert connectable_url(value) == shared(value)
