import urllib.request
import json

endpoints = [
    '/api/mission-control',
    '/api/projects',
    '/api/growth/actions',
    '/api/naver/quota',
    '/api/naver/schedule',
    '/api/cf/pipeline',
    '/api/threads/overview',
    '/api/kin/overview',
    '/api/memory/graph'
]

for ep in endpoints:
    try:
        req = urllib.request.Request(f'http://127.0.0.1:8790{ep}')
        with urllib.request.urlopen(req) as res:
            data = res.read()
            print(f"{ep}: {res.status} (bytes: {len(data)})")
    except Exception as e:
        print(f"{ep}: ERROR -> {e}")
