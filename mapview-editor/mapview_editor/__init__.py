"""MapView Editor — local web editor for Acuity nLight SensorView .mvdb
floorplan archives, with an optional MCP server for AI-assisted drawing.

Entry points:
  mapview-editor      — start the web editor (http://localhost:5111)
  mapview-editor-mcp  — start the MCP server (talks to the running editor)
"""

from .server import __version__  # single source of truth

__all__ = ["__version__"]
