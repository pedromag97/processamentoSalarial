"""Ponto de entrada do executável (PyInstaller). Ver scripts/empacotar.cmd."""

import sys

from lsc_presencas.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
