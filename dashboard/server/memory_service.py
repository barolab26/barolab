"""Loopback-only memory API and dashboard, without publication schedulers."""
import argparse
import os
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'dashboard' / 'server'))


def create_app(port=None):
    port = int(port or os.environ.get("BAROLAB_MEMORY_SERVICE_PORT", "8792"))
    # Import the same router as production; never import main.py, whose import
    # starts a periodic project-health worker.
    from memory_graph import memory_router, reset_to_clean_slate, connect_db
    try:
        with connect_db() as db:
            if db.execute("SELECT COUNT(*) FROM docs").fetchone()[0] == 0:
                reset_to_clean_slate()
    except Exception:
        pass
    app = FastAPI(title='BaroLab local memory service')
    origins = [f'http://127.0.0.1:{port}', f'http://localhost:{port}',
               'http://127.0.0.1:8790', 'http://localhost:8790',
               'http://192.168.45.190:8790', 'http://otns:8790']
    app.add_middleware(CORSMiddleware, allow_origins=origins,
                       allow_methods=['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
                       allow_headers=['Content-Type', 'X-Barolab-Settings'])

    @app.middleware('http')
    async def require_loopback(request: Request, call_next):
        if (request.client.host not in ('127.0.0.1', '::1', 'testclient')
                or (request.headers.get('origin') and request.headers['origin'] not in origins)):
            return JSONResponse({'detail': 'Local memory service only'}, status_code=403)
        return await call_next(request)

    @app.get('/api/status')
    def status():
        return {'ok': True, 'mode': 'memory-only', 'schedulersStarted': False}

    app.include_router(memory_router)
    app.mount('/', StaticFiles(directory=str(ROOT / 'dashboard'), html=True), name='dashboard')
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8792)
    parser.add_argument('--reload', action='store_true', help='Opt-in local Python source reload; no schedulers')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('Choose an unprivileged TCP port from 1024 to 65535')
    import uvicorn
    os.environ['BAROLAB_MEMORY_SERVICE_PORT'] = str(args.port)
    uvicorn.run('server.memory_service:create_app', factory=True, host='127.0.0.1', port=args.port,
                reload=args.reload, reload_dirs=[str(ROOT / 'dashboard' / 'server'), str(ROOT / 'dashboard' / 'common')] if args.reload else None)


if __name__ == '__main__':
    main()
