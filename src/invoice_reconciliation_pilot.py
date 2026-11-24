"""Compatibility import for the original invoice reconciliation pilot."""
import sys

if __package__ in (None, ''):  # Preserve direct script execution from any cwd.
    from services import invoice_reconciliation as _implementation
else:
    from src.services import invoice_reconciliation as _implementation

if __name__ != '__main__':
    sys.modules[__name__] = _implementation
