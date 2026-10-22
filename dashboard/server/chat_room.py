"""Legacy import alias for dashboard.agents.chat_room."""
import importlib
import sys
sys.modules[__name__] = importlib.import_module("dashboard.agents.chat_room")
