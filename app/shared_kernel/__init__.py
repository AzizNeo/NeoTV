"""Shared kernel — the *only* code every module may import from each other.

Pure Python only: frozen dataclasses (events, value objects) and enums. No
Flask, SQLAlchemy, Redis or Celery imports (enforced by import-linter).
"""
