"""Compatibility entry point for dashboard.collectors.traffic."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if __name__ == "__main__":
    import runpy
    runpy.run_module("dashboard.collectors.traffic", run_name="__main__")
else:
    from dashboard.collectors import traffic
    sys.modules[__name__] = traffic
