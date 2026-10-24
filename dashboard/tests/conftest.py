"""Unit tests must never claim or close the live meeting's business agenda."""
import pytest


@pytest.fixture(autouse=True)
def isolated_business_agendas(tmp_path, monkeypatch):
    from common import work_agenda as agendas
    monkeypatch.setattr(agendas, 'DATA', tmp_path/'agenda-data')
    monkeypatch.setattr(agendas, 'STATE', agendas.DATA/'active-agenda.json')
    monkeypatch.setattr(agendas, 'ROWS', agendas.DATA/'publication-conferences/operations')
    monkeypatch.delenv('BAROLAB_AGENDA_CONTEXT', raising=False)
    # Existing compatibility tests exercise the unactivated migration path.
    # test_work_agenda explicitly activates the production contract.
