"""Legacy import alias for dashboard.agents.agent_tools."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("dashboard.agents.agent_tools")
