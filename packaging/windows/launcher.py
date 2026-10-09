"""Точка входа собранной программы (PyInstaller)."""
import sys

from muninhall.app import main

if __name__ == "__main__":
    sys.exit(main())
