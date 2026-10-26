"""Frequent revenue-only refresh. No model generation, indexing, or publication."""
import argparse
import datetime as dt
import json
from pathlib import Path
import socket
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
KST=dt.timezone(dt.timedelta(hours=9))
API_SECONDS=300
BROWSER_SECONDS=600


def due(record,now,interval):
    try:return now>=float(record.get('nextAttemptAt',0))
    except (ValueError,TypeError):return True


def collect_once(root=ROOT,now=None,backend=None):
    root=Path(root);now=now or dt.datetime.now(KST);today=now.date();month=now.strftime('%Y-%m');start=today.replace(day=1)
    if backend is None:
        sys.path.insert(0,str(ROOT/'dashboard'))
        import revenue as backend
    from common.collection_observability import write
    data=root/'dashboard/data';data.mkdir(parents=True,exist_ok=True)
    with backend.collector_lock(data/'revenue.lock') as acquired:
        if not acquired:return {'status':'busy'}
        previous=backend.read_json(data/'revenue.json');config=backend.read_json(data/'metrics-config.json')
        state=backend.read_json(data/'revenue-refresh.json');state.update(schema='revenue-refresh-v1',startedAt=now.isoformat(),status='collecting',apiIntervalSeconds=API_SECONDS,browserIntervalSeconds=BROWSER_SECONDS)
        state.setdefault('sources',{});write(data/'revenue-refresh.json',state)
        cfg=backend.revenue_config();accounts=config.get('adsense_accounts',{})
        rows=previous.setdefault('months',{}).setdefault(month,{}).setdefault('sources',[])
        by_id={r['id']:r for r in rows};jobs=[]
        for account in ('sj','aaa10291028'):
            settings=accounts.get(account,{})
            prefix=settings.get('env_prefix','SJ_GOOGLE_ADSENSE' if account=='sj' else 'AAA10291028_GOOGLE_ADSENSE')
            key='adsense-'+account
            record=by_id.setdefault(key,backend.source(key,'adsense','CF 애드센스 '+account,'USD','등록 CF 도메인',domains=settings.get('sites',[])))
            def adsense_job(settings=settings,prefix=prefix):
                if not settings.get('sites') or not all(cfg.get(prefix+'_'+n) for n in ('ACCOUNT_ID','CLIENT_ID','CLIENT_SECRET','REFRESH_TOKEN')):
                    raise backend.RevenueSourceError('not_configured','애드센스 OAuth 연결 대기')
                return backend.adsense(cfg,start,today,settings['sites'],prefix)
            jobs.append((key,record,API_SECONDS,adsense_job))
        for account,port in backend.ADPOST_ACCOUNTS:
            key='adpost-'+account;record=by_id.setdefault(key,backend.source(key,'adpost','애드포스트 · 실명 3계정 통합','KRW','soul5373 통합 로그인 · 전체 등록 미디어',browserPort=port))
            record.update(browserPort=9333,collectionAccount='soul5373',declaredRealNameAccountCount=3)
            def adpost_job(account=account,port=port):
                # A refresh must never start a stopped browser or touch an active editor.
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.3):pass
                except OSError:raise backend.RevenueSourceError('browser_offline','전용 브라우저 대기') from None
                from naver_blog_posting.posting import pipeline_lock
                try:
                    with pipeline_lock():return backend.adpost(start,today,cfg,account,port)
                except RuntimeError as exc:
                    if 'already running' in str(exc):raise backend.RevenueSourceError('deferred','발행 작업 우선 · 수익 수집 다음 주기') from None
                    raise
            jobs.append((key,record,BROWSER_SECONDS,adpost_job))
        for key,label in (('coupang','쿠팡 파트너스'),('toss','토스 쉐어링크'),('trip','Trip.com'),('replyalba','제휴알바')):
            record=by_id.setdefault(key,backend.source(key,'affiliate',label,'KRW',label))
            def affiliate_job(key=key):
                if key=='coupang':return backend.coupang(cfg,start,today,now=now)
                config=backend.affiliate_configuration(cfg,key)
                if key=='toss' and config.get('reportCapability')=='api_report':return backend.toss(cfg,start,today)
                if key=='replyalba' and config.get('credentialPresence',{}).get('login'):return backend.replyalba(cfg,start,today,now=now)
                if key=='trip' and config.get('credentialPresence',{}).get('affiliateIds'):
                    raise backend.RevenueSourceError('report_unavailable','트립닷컴 추적 식별자 설정됨 · 수익 보고서 미연결')
                raise backend.RevenueSourceError('not_configured','수익 보고 API 연결 대기')
            jobs.append((key,record,API_SECONDS,affiliate_job))
        for key,record,interval,job in jobs:
            status=state['sources'].setdefault(key,{})
            if not due(status,now.timestamp(),interval):continue
            from common.crew_chat_bridge import emit_work_event
            task='revenue:'+key+':'+now.isoformat()
            emit_work_event(actor='trace',actor_label='트레이스',task_id=task,phase='progress',stage='revenue-collection',output_kind=key+' 수익 원천 수집 시작')
            attempted=dt.datetime.now(KST);status.update(attemptedAt=attempted.isoformat(),status='collecting')
            write(data/'revenue-refresh.json',state)
            try:
                result=job()
                if result.get('status')!='collected':raise backend.RevenueSourceError(result.get('status','partial'),'원천 보고서 집계 대기')
                for day,value in result.get('daily',{}).items():
                    if not start.isoformat()<=day<=today.isoformat():raise ValueError('out_of_range')
                    backend.money(value)
                completed=dt.datetime.now(KST).isoformat()
                record.update(result,checkedAt=completed,lastSuccessAt=completed,attemptedAt=attempted.isoformat(),reportStart=start.isoformat(),reportEnd=today.isoformat())
                status.update(status='collected',lastSuccessAt=completed,nextAttemptAt=time.time()+interval)
            except Exception as exc:
                code=getattr(exc,'status','error')
                reason=str(exc) if isinstance(exc,backend.RevenueSourceError) else '원천 연결 실패 · 이전 수익 유지'
                record.update(status=code,reason=reason,attemptedAt=attempted.isoformat())
                status.update(status=code,errorType=type(exc).__name__,reason=reason,
                              nextAttemptAt=time.time()+(1800 if code in ('not_configured','auth_required','not_enrolled') else 60 if code=='deferred' else interval))
            emit_work_event(actor='trace',actor_label='트레이스',task_id=task,phase='completed',stage='revenue-collection',output_kind=key+' 수집 결과: '+str(status.get('status')))
            previous['months'][month].update(sources=list(by_id.values()),checkedAt=dt.datetime.now(KST).isoformat())
            previous.update(schema='dashboard-revenue-v1',checkedAt=dt.datetime.now(KST).isoformat())
            backend.deduplicate_adpost_sources(previous['months'][month]['sources'])
            write(data/'revenue.json',previous)
            state.update(checkedAt=dt.datetime.now(KST).isoformat());write(data/'revenue-refresh.json',state)
        page_status = state.setdefault('pageRevenue', {})
        if due(page_status, now.timestamp(), 1800):
            try:
                previous['pagePerformance'] = backend.collect_page_revenue(cfg, accounts, now)
                page_status.update(status='collected' if previous['pagePerformance'].get('complete') else 'partial',
                                   checkedAt=now.isoformat(), nextAttemptAt=now.timestamp() + 1800)
                write(data/'revenue.json', previous)
            except Exception:
                page_status.update(status='error', reasonCode='page_revenue_collection_failed', nextAttemptAt=now.timestamp() + 1800)
        state.update(status='completed',finishedAt=dt.datetime.now(KST).isoformat())
        write(data/'revenue-refresh.json',state)
    from server.growth import refresh_performance_feedback
    feedback = refresh_performance_feedback()
    return {'status':'completed','sources':{k:v.get('status') for k,v in state['sources'].items()},
            'performanceFeedback': feedback.get('status')}


def install_user_timer():
    import subprocess
    units=Path.home()/'.config/systemd/user';units.mkdir(parents=True,exist_ok=True)
    service='[Unit]\nDescription=BaroLab frequent revenue-only refresh\nAfter=network-online.target\n\n[Service]\nType=oneshot\nWorkingDirectory='+str(ROOT)+'\nExecStart='+sys.executable+' -u -B -m common.revenue_refresh --once\nTimeoutStartSec=600\n'
    timer='[Unit]\nDescription=Refresh due revenue sources every minute\n\n[Timer]\nOnBootSec=30\nOnUnitInactiveSec=60\nAccuracySec=5\nRandomizedDelaySec=3\nUnit=barolab-revenue-refresh.service\n\n[Install]\nWantedBy=timers.target\n'
    (units/'barolab-revenue-refresh.service').write_text(service)
    (units/'barolab-revenue-refresh.timer').write_text(timer)
    subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    subprocess.run(['systemctl','--user','enable','--now','barolab-revenue-refresh.timer'],check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--once',action='store_true')
    parser.add_argument('--install-user-timer',action='store_true');args=parser.parse_args()
    if args.install_user_timer:return install_user_timer()
    print(json.dumps(collect_once(),ensure_ascii=False))

if __name__=='__main__':main()
