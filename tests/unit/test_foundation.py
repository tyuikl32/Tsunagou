from tsunagou import __version__
from tsunagou.bootstrap.container import build_application
from tsunagou.cli.app import app


def test_health_route_and_version() -> None:
    application = build_application()
    health_route = next(route for route in application.routes if route.path == "/api/v1/health")
    response = health_route.endpoint()
    assert response.status == "ok"
    assert response.version == __version__


def test_cli_exists() -> None:
    assert app is not None
