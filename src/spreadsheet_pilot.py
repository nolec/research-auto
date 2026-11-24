"""Compatibility entry point for the original spreadsheet pilot."""
import sys

if __package__ in (None, ''):  # Preserve direct script execution from any cwd.
    from services import spreadsheet as _implementation
else:
    from src.services import spreadsheet as _implementation

if __name__ == '__main__':
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
