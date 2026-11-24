"""Compatibility entry point for the scanned-table delivery workflow."""
import sys
from src.services.scanned_pdf import order as _implementation

if __name__ == '__main__':
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
