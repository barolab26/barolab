"""Explicit manual operations; never activates on import or initialization."""
import argparse,json
from datetime import datetime,timezone
from pathlib import Path
from common.dashboard_jobs import write
from . import config as settings,pipeline,authoring,adapter

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['init','snapshot','catalog','prepare','import','publish','reconcile','check-connection','activate','oauth-url','complete-oauth','receive-token','measure']);p.add_argument('--url');p.add_argument('--official-url',action='append',default=[]);p.add_argument('--day');p.add_argument('--slot',default='19:30');p.add_argument('--file');p.add_argument('--part-id');p.add_argument('--code');p.add_argument('--state');args=p.parse_args();config=settings.load()
    if args.command=='init':settings.save(config);result={'enabled':False,'account_key':config['account_key']}
    elif args.command=='snapshot':result=pipeline.snapshot(config)
    elif args.command=='catalog':result=authoring.catalog(config)
    elif args.command=='prepare':result=authoring.prepare(config,args.url,args.day or datetime.now(timezone.utc).astimezone(pipeline.KST).date().isoformat(),args.slot,args.official_url)
    elif args.command=='import':result={'attempt_id':pipeline.import_document(json.loads(Path(args.file).read_text(encoding='utf-8')),config)}
    elif args.command=='publish':result=pipeline.publish(args.part_id,config,config_loader=settings.load)
    elif args.command=='reconcile':result={'verified':pipeline.reconcile(config)}
    elif args.command=='check-connection':
        result=adapter.readiness_status(config);config['connection']=result;settings.save(config);pipeline.snapshot(config)
    elif args.command=='activate':
        config['connection']=adapter.readiness_status(config);config=settings.activate(config,approved=True);settings.save(config);result={'enabled':True,'activatedAt':config['activatedAt']}
    elif args.command=='oauth-url':
        import secrets
        state=secrets.token_urlsafe(32);url=adapter.build_authorization_url(config,state);write(settings.PRIVATE/'threads-oauth-state.json',{'state':state,'created_at':settings.stamp()});result={'authorization_url':url}
    elif args.command=='complete-oauth':
        import secrets
        state_path=settings.PRIVATE/'threads-oauth-state.json';pending=json.loads(state_path.read_text(encoding='utf-8'))
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(pending['created_at'])).total_seconds()
        if not args.state or not secrets.compare_digest(args.state,pending['state']) or not 0<=age<=600:raise RuntimeError('Invalid or expired OAuth state')
        state_path.unlink();tokens=adapter.exchange_authorization_code(config,args.code)
        token_path=settings.PRIVATE/'threads-token.json';write(token_path,tokens);config['api']['token_file']=str(token_path);config['connection']=adapter.connection_status(config);settings.save(config);result={'connected':config['connection'].get('connected') is True}
    elif args.command=='receive-token':
        from .auth import receive_token
        received=receive_token(config)
        if received.get('connected') is True and received.get('account_verified') is True:
            config['api']['token_file']=received.pop('token_file');config['connection']=received;settings.save(config);pipeline.snapshot(config)
        result={k:received.get(k) for k in ('connected','account_verified','account_key','reason')}
    elif args.command=='measure':
        from .measurement import collect
        with pipeline.connect() as db:publications=[dict(r) for r in db.execute("SELECT * FROM parts WHERE state='published_verified'")]
        measurement=collect(config,publications)
        with pipeline.connect() as db:db.execute('INSERT OR REPLACE INTO runtime VALUES(?,?)',('measurement',json.dumps(measurement)))
        pipeline.snapshot(config);result={'status':measurement.get('status'),'revenue':None}
    # Source snapshots are private; CLI never prints generated documents, credentials or paths from API responses.
    if args.command=='prepare':result={k:result[k] for k in ('path','approved','reason')}
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
