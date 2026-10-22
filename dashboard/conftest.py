"""Provider mocks must never append calls to the live model usage ledger."""
import pytest


@pytest.fixture(autouse=True)
def isolate_model_usage(monkeypatch, tmp_path):
    from common import llm_usage, crew_chat_bridge, ego_telemetry
    monkeypatch.setattr(llm_usage, 'ROOT', tmp_path)
    monkeypatch.setattr(crew_chat_bridge, 'OUTBOX_DIR', tmp_path/'crew-outbox')
    monkeypatch.setattr(crew_chat_bridge, 'ROOM_MAIN_FILE', tmp_path/'room-main.json')
    monkeypatch.setattr(ego_telemetry, 'DIRECTORY', tmp_path/'ego-telemetry')
