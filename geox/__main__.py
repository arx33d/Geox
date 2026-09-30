"""Main module execution entry point for Geox (`python -m geox`)."""

import sys
from .cli import main

if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main(sys.argv[1:]))
    else:
        # Default with no arguments: start CLI help or web server
        sys.exit(main(["--help"]))
