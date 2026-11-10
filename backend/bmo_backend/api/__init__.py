"""Rotas HTTP adicionais do backend do BMO."""

from .music_routes import build_music_routers

__all__ = ["build_music_routers"]
