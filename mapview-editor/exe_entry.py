"""PyInstaller entry point.

Build from a proper package import (not mapview_editor/server.py directly) so
`from . import dblabels` resolves — handing PyInstaller a file inside the
package makes it a top-level script with no parent package and the build
silently loses modules. See README "Build a standalone .exe".
"""

from mapview_editor.server import main

main()
