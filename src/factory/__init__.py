"""Product-agnostic AI software factory."""

from importlib import metadata

__version__ = metadata.version("software-factory")

# Pinned tool versions: change them only here (the runner images read them at build time).
SPECKIT_VERSION = "1.4.1"
CLAUDE_CODE_VERSION = "2.1.116"
GITLEAKS_VERSION = "8.30.1"
OSV_SCANNER_VERSION = "2.7.1"
SEMGREP_VERSION = "1.185.0"
PLAYWRIGHT_VERSION = "1.65.2"
NGROK_IMAGE = "ngrok/ngrok:3.39.13-alpine"
