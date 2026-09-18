from __future__ import annotations

try:
    import typer
except ImportError:  # pragma: no cover
    typer = None  # type: ignore[assignment]


if typer is not None:
    app = typer.Typer(add_completion=False, invoke_without_command=True)

    @app.callback()
    def callback(
        ctx: typer.Context,
        version: bool = typer.Option(False, "--version", is_eager=True),
    ) -> None:
        if version:
            print("0.1.0")
            raise typer.Exit()
        if ctx.invoked_subcommand is None:
            print("Tsunagou 0.1.0 — local coordination runtime")

    main = app
else:
    def main() -> None:
        print("Tsunagou 0.1.0 — local coordination runtime")
