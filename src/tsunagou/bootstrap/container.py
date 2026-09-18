"""Application assembly; domain services are added by their owning tasks."""

from fastapi import FastAPI

from tsunagou.api.app import create_app


def build_application() -> FastAPI:
    return create_app()
