"""Compatibility entry point for dashboard.collectors.metrics."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if __name__ == "__main__":
    import runpy
    runpy.run_module("dashboard.collectors.metrics", run_name="__main__")
else:
    from dashboard.collectors import metrics
    sys.modules[__name__] = metrics
