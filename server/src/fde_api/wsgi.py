"""Production WSGI entry point for Gunicorn."""

from fde_api.app import create_app


app = create_app()
