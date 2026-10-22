"""Compatibility entry point; use cf_posting.posting for new calls."""
import sys
from pathlib import Path

if __name__ == "__main__":
    import runpy
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    runpy.run_module("cf_posting.posting", run_name="__main__")
else:
    from cf_posting import posting
    sys.modules[__name__] = posting
