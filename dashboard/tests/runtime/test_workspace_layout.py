from unittest.mock import patch
from dashboard.server import workspace_layout as layout


def test_dashboard_monitor_and_account_order_and_overlap():
    classes = ['BaroLab-Dashboard', 'xfce4-terminal', 'BaroLab-soultin',
               'BaroLab-soul5373', 'BaroLab-yoon_master', 'BaroLab-adinfo0905',
               'BaroLab-stone0747', 'BaroLab-CF-Flow', 'BaroLab-Threads']
    rows = [layout.window_identity('EGO LITE', cls) for cls in classes]
    assert rows == list(layout.WINDOW_ORDER)
    assert rows[0][2][0] < rows[1][2][0] < rows[2][2][0]
    assert len({row[2] for row in rows[2:]}) == 1
    assert [row[1][:2] for row in rows] == [f'{n:02}' for n in range(1, 10)]


def test_navigation_restores_account_label_without_resizing_existing_editor():
    with patch.object(layout, 'get_window_props', return_value=('BaroLab-soultin', 'browser')), \
         patch.object(layout.subprocess, 'run') as run, patch.object(layout, 'snap_exact') as snap:
        assert layout.classify_and_position('0x123', 'Article editor', {}, position=False) == 'soultin'
    run.assert_called_once()
    assert run.call_args.args[0][-1] == '03 soultin · 개인 1'
    snap.assert_not_called()


def test_unrelated_window_is_untouched():
    assert layout.window_identity('Terminal', 'xfce4-terminal') is None
    assert layout.window_identity('Dashboard docs', 'mousepad') is None
