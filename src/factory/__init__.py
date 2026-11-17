"""Product-agnostic AI software factory."""

from importlib import metadata

__version__ = metadata.version("software-factory")

# Pinned tool versions: change them only here (the runner images read them at build time).
SPECKIT_VERSION = "1.4.1"
CLAUDE_CODE_VERSION = "2.1.116"
