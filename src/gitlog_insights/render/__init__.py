"""Output formats. Every renderer takes the same :class:`Report` structure."""

from .document import Column, Report, Section
from .formats import FORMATS, render

__all__ = ["Column", "FORMATS", "Report", "Section", "render"]
