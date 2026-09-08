"""Single source of truth for the installed package version.

Kept separate from ``__init__.py`` so ``client.py`` can import it without a
circular partial-initialization import (``client.py`` needs the version
string for the MCP ``clientInfo`` handshake; ``__init__.py`` needs
``Client`` from ``client.py``).
"""

from __future__ import annotations

__version__ = "0.1.0"
