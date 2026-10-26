"""WSL desktop entrypoint, also linked from /home/baro7/ego_monitor.py."""
import importlib.util
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
if importlib.util.find_spec('rich') is None:
    python=Path.home()/'.venvs/barolab/bin/python3'
    if not python.is_file():
        raise SystemExit('BaroLab 환경에 dashboard/server/requirements.txt를 설치해 주세요.')
    os.execv(str(python),[str(python),str(Path(__file__).resolve()),*sys.argv[1:]])
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT / 'dashboard'))

if __name__=='__main__':
    from server.mission_control import main
    raise SystemExit(main())
