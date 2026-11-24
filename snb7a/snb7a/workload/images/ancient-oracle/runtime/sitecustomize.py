"""
Runtime shims for the slim (Alpine) Python image, imported automatically
at start-up.

- stdout/stderr in UTF-8 and line-buffered, so logs show up in
  `kubectl logs` at once.
"""

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", line_buffering=True)
    except (AttributeError, ValueError):
        pass
