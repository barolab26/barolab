"""Compatibility entry point for dashboard.collectors.revenue."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if __name__ == "__main__":
    import runpy
    runpy.run_module("dashboard.collectors.revenue", run_name="__main__")
else:
    from dashboard.collectors import revenue
    sys.modules[__name__] = revenue
