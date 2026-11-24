"""Compatibility entry point for the original periodic report."""
import sys
from src.services import periodic_report as _implementation

if __name__ == '__main__':
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
