/* Read-only Threads source. One request per minute, shared by every mount. */
(() => {
  'use strict';
  let state={status:'loading',data:null,fetchedAt:null,stale:true,error:null}, pending=null, fetched=0;
  const listeners=new Set(), MAX_AGE=30*60000;
  const count=value=>typeof value==='number' && Number.isFinite(value) && value>=0 ? value : null;
  const number=value=>count(value)===null ? '미확인' : value.toLocaleString('ko-KR');
  const stamp=value=>{const d=new Date(value || '');return Number.isFinite(d.getTime()) ? d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})+' KST' : '시각 미확인';};
  const labels={needs_account:'계정 연결 준비',paused_token:'인증 갱신 필요',disabled:'운영 꺼짐',ready:'연결 준비 완료',queued:'대기',drafted:'초안',reviewed:'검수 완료',approved:'검수 통과',passed:'검수 통과',rejected:'검수 보류',review_rejected:'검수 보류',sending_intent:'전송 시작 기록',submitted_unknown:'전송 결과 미확인',api_submitted:'API 접수 · 공개 미확인',published_verified:'공개 확인',failed:'실패',blocked:'중단',not_collected:'미수집',partial:'부분 수집',collected:'수집 완료',not_due:'확인 시점 미도래',unmeasured:'미수집',pending:'검수 대기',insufficient_data:'비교 근거 부족',unchecked:'연결 미확인',connected:'연결 확인',needs_token:'인증 연결 필요',identity_mismatch:'계정 불일치',error:'조회 실패'};
  const label=value=>labels[value] || '상세 기록 확인';
  const ALLOWED_SOURCE_HOSTS=['must-good.com','www.must-good.com','baronote.kr','www.baronote.kr','justinfo.co.kr','www.justinfo.co.kr','topnote.kr','www.topnote.kr','meganote.kr','www.meganote.kr','smilenote.kr','www.smilenote.kr','healthcox.com','www.healthcox.com','maxnote.kr','www.maxnote.kr','must-joy.com','www.must-joy.com','tripmarvel.com','www.tripmarvel.com','must-pick.com','www.must-pick.com','woorinote.kr','www.woorinote.kr','daynote.kr','www.daynote.kr','nolplace.com','www.nolplace.com','soulnote.kr','www.soulnote.kr','joynote.kr','www.joynote.kr','toss.im','link.coupang.com','ohou.se','oliveyoung.co.kr','www.oliveyoung.co.kr','adpick.co.kr','www.adpick.co.kr'];
  const safeURL=(value,kind='source')=>{try{const u=new URL(value);if(u.protocol!=='https:' || u.username || u.password)return null;const h=u.hostname.toLowerCase();if(kind==='post' && !['threads.net','www.threads.net','threads.com','www.threads.com'].includes(h))return null;if(kind==='source' && !ALLOWED_SOURCE_HOSTS.includes(h))return null;return u.href;}catch{return null;}};
  const getState=()=>({...state});
  function operation(s=state){
    const c=s.data && s.data.configuration || {}, data=s.data || {};
    if(s.status==='loading')return {label:'운영 기록 확인 중',detail:'확인된 실행 기록을 기다리고 있습니다.',kind:'unknown'};
    if(!s.data)return {label:'연결 준비',detail:'@mustpickinfo 계정은 확정됐으며 API 연결과 운영 기록은 아직 확인되지 않았습니다.',kind:'unknown'};
    if(s.status==='error' || s.stale)return {label:'최신 기록 확인 필요',detail:'마지막 기록과 현재 실행 상태를 구분합니다.',kind:'unknown'};
    if(c.status==='paused_token')return {label:'인증 갱신 필요',detail:'인증 상태를 확인하기 전에는 게시 완료로 보지 않습니다.',kind:'issue'};
    if(c.status==='needs_account' || c.status==='needs_connection')return {label:'API 연결 준비',detail:'@mustpickinfo 사용자 지정 · 공식 API 연결 확인 필요',kind:'issue'};
    const connection=data.connection || c.connection || {};
    if(connection.connected===true && connection.publishReady!==true)return {label:'게시 준비 확인',detail:'계정 신원 확인됨 · 게시 권한·인증 만료·게시 한도 검증 필요',kind:'issue'};
    if(c.enabled===false || c.status==='disabled')return {label:'운영 꺼짐',detail:'운영 설정과 API 연결 상태는 별도입니다.',kind:'disabled'};
    if(data.activeRunId || data.automation && data.automation.activeRunId)return {label:'작업 진행 중',detail:'실행 기록 확인 · 공개 게시와 구분',kind:'active'};
    const auto=data.automation || {}, scheduler=auto.scheduler || {};
    if(auto.state==='ended')return {label:'시험 종료',detail:'게시 시험 종료 · 효과 측정은 별도 확인',kind:'ended'};
    const ran=Date.parse(auto.lastRunAt), activated=Date.parse(c.activatedAt), observed=Date.parse(scheduler.checkedAt);
    if(c.enabled===true && connection.publishReady===true && auto.state==='waiting' && auto.lastResult==='waiting'
      && Number.isFinite(ran) && Number.isFinite(activated) && ran>=activated && ran<=Date.now()+60000 && Date.now()-ran<=MAX_AGE
      && scheduler.registered===true && scheduler.enabled===true && Number.isFinite(observed) && Date.now()-observed<=MAX_AGE)
      return {label:'대기',detail:'활성화 후 실제 점검 완료 · 다음 게시 조건 대기',kind:'waiting'};
    return {label:'실행 상태 확인 필요',detail:(c.status==='ready' ? '연결 준비 기록 확인 · ' : '')+'설정 켜짐만으로 실제 자동 실행을 확정하지 않습니다.',kind:'unknown'};
  }
  function summarize(s=state){
    const data=s.data || {}, c=data.configuration || {}, counts=data.counts || {}, m=data.measurement || {};
    const total=key=>count(counts[key])===null && data.countsComplete===true && data.counts ? 0 : count(counts[key]);
    const today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Seoul'}), daily=data.today || {};
    const dailyCount=kind=>daily.date===today && Array.isArray(daily.counts) ? daily.counts.filter(row=>row.kind===kind && row.state==='published_verified').reduce((sum,row)=>sum+(count(row.n)||0),0) : null;
    return {configuration:c,counts,measurement:m,operation:operation(s),published:total('published_verified'),submitted:total('api_submitted'),uncertain:total('submitted_unknown'),todayMain:dailyCount('main'),todayFollowup:dailyCount('followup'),revenue:null};
  }
  function worker(s=state){
    const data=s.data || {}, schedule=data.automation && data.automation.scheduler || {};
    const at=Date.parse(schedule.checkedAt), fresh=s.status==='ready' && !s.stale && Number.isFinite(at) && Date.now()-at<=MAX_AGE && at<=Date.now()+60000;
    if(!fresh)return '5분 조건 점검 작업 · 현재 등록 상태 미확인';
    const status=schedule.registered===true ? schedule.enabled===true ? '등록·활성 확인' : schedule.enabled===false ? '등록됨 · 비활성' : '등록됨 · 활성 미확인' : schedule.registered===false ? '미등록' : '등록 미확인';
    return '5분 조건 점검 작업 '+status+' · 다음 확인 '+stamp(schedule.nextRunAt)+' · 게시 작업과 별도';
  }
  function readiness(s=state){
    const data=s.data || {}, connection=data.connection || data.configuration && data.configuration.connection || {};
    const scope=connection.scopesStatus==='verified'?'확인':connection.scopesStatus==='missing'?'보완 필요':'미확인';
    const expiry=connection.expiryStatus==='verified'?'유효':connection.expiryStatus==='expired'?'만료':'미확인';
    return '계정 신원 '+(connection.connected===true?'확인':'미확인')+' · 게시 준비 '+(connection.publishReady===true?'검증 완료':'미확인')+' · 권한 '+scope+' · 인증 만료 '+expiry+' · 게시 한도 '+(connection.quotaStatus==='verified'?'확인':'미확인');
  }
  function notify(){listeners.forEach(fn=>{try{fn(getState());}catch(e){console.error('Threads presentation failed',e);}});window.dispatchEvent(new CustomEvent('barolab-threads-updated',{detail:getState()}));}
  async function refresh({force=false}={}){
    if(pending)return pending;if(!force && Date.now()-fetched<60000)return getState();
    pending=(async()=>{try{const response=await fetch('data/threads.json',{cache:'no-store',signal:AbortSignal.timeout(12000)});if(!response.ok)throw Error('HTTP '+response.status);const data=await response.json();if(data.schema!=='threads-pilot-v1')throw Error('Unsupported snapshot');const t=Date.parse(data.checkedAt);state={status:'ready',data,fetchedAt:new Date().toISOString(),stale:!Number.isFinite(t)||Date.now()-t>MAX_AGE||t>Date.now()+60000,error:null};}catch(e){state={...state,status:'error',stale:true,error:'운영 원장 조회 실패'};}fetched=Date.now();notify();return getState();})();
    try{return await pending;}finally{pending=null;}
  }
  function subscribe(fn){listeners.add(fn);fn(getState());return()=>listeners.delete(fn);}
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
  function metric(title,value){const item=el('div');item.append(el('span',title),el('strong',value));return item;}
  function render(mount,s){
    const v=summarize(s),op=v.operation,mode=mount.dataset.threadsSummary;
    mount.replaceChildren();mount.classList.add('threads-summary-card');
    const head=el('div',undefined,'threads-summary-head'),link=el('a','Threads 상세 →');link.href='threads.html';head.append(el('h2','Threads · @mustpickinfo'),link);mount.append(head,el('p',op.label+' · '+op.detail,'threads-meta'));
    const metrics=el('div',undefined,'threads-metrics');metrics.append(metric('누적 공개 확인 · 본문+후속',number(v.published)),metric('누적 API 접수 · 공개 미확인',number(v.submitted)),metric('누적 전송 결과 미확인',number(v.uncertain)));mount.append(metrics);
    mount.append(el('p','오늘 KST 공개 확인 · 본문 '+number(v.todayMain)+'개 / 후속 '+number(v.todayFollowup)+'개 · 하루 본문 한도와 누적 게시물 수는 별도입니다.','threads-note'));
    if(mode==='traffic')mount.append(el('p','게시물 조회수와 CF 유입 세션은 별도 측정합니다. 24시간·72시간·7일은 게시 후 확인 시점이며, 누적 반응과 게시일~어제의 UTM 방문은 상세 화면에서 확인합니다. 기존 CF 합계에 더하지 않습니다.','threads-note'));
    else if(mode==='settings'){
      const connection=s.data && s.data.connection || v.configuration.connection || {};
      mount.append(el('p','공식 API 연결: '+label(connection.status)+' · 확인 '+stamp(connection.checkedAt),'threads-note'));
      mount.append(el('p',readiness(s),'threads-note'));
      mount.append(el('p',worker(s),'threads-note'));
      mount.append(el('p','전용 모델: '+(v.configuration.model || '미확인')+' · 시험 '+number(v.configuration.trialDays)+'일 · 본문 하루 최대 '+number(v.configuration.mainDailyCap)+'개','threads-note'));
      mount.append(el('p','이 화면은 읽기 전용입니다. 아래 블로그 공용 모델 설정은 Threads 전용 설정을 변경하지 않습니다. API 토큰은 이 화면에 입력하거나 표시하지 않습니다.','threads-note'));
      const guide=el('details'),summary=el('summary','계정 연결과 운영 확인');guide.append(summary,el('p','@mustpickinfo 계정의 공식 Threads API 연결·권한·토큰 유효성을 운영 호스트에서 확인한 뒤 연결 검증을 수행합니다. 현재 기록이 연결 준비이면 자동 게시가 시작됐다는 뜻이 아닙니다. 정확한 운영 명령은 프로젝트 Threads 운영 문서를 따릅니다.'));mount.append(guide);
    }else if(mode==='overview'){
      mount.append(el('p','오늘 할 일: '+(op.kind==='issue'||!s.data ? 'API 연결과 인증 상태 확인' : op.kind==='active' ? '현재 작업의 공개 확인 결과 점검' : '최근 작업·검수 결과와 유입 측정 확인'),'threads-note'));
      const auto=s.data && s.data.automation || {};
      mount.append(el('p','다음 작업: '+(auto.nextEligibleAt ? stamp(auto.nextEligibleAt) : '실제 실행 일정 미확인')+' · 다음 계정 '+(auto.nextAccount || '@mustpickinfo')+' · 수익 귀속 미확인','threads-note'));
    }
    mount.append(el('p','원장 '+stamp(s.data && s.data.checkedAt)+' · 블로그·지식인 실적과 별도 · 방문·수익 미수집은 0이 아닙니다.','threads-note'));
  }
  window.BaroLabThreadsSummary={getState,refresh,subscribe,summarize,operation,worker,readiness,number,stamp,label,safeURL};
  document.querySelectorAll('[data-threads-summary]').forEach(m=>subscribe(s=>render(m,s)));
  subscribe(s=>{const op=operation(s),badge=document.getElementById('threads-sidebar-status'),note=document.getElementById('threads-sidebar-note');const compact=op.kind==='waiting'?'대기':op.kind==='ended'?'시험 종료':op.kind==='active'?'작업 중':op.kind==='disabled'?'꺼짐':op.kind==='issue'?'연결 대기':'확인 필요';if(badge)badge.textContent=compact;if(note)note.textContent='@mustpickinfo · '+compact;const task=document.getElementById('threads-overview-task'),detail=document.getElementById('threads-overview-detail'),operating=document.getElementById('threads-overview-operation');if(task)task.textContent=op.kind==='active'?'진행 중 회차 확인':op.kind==='issue'||!s.data?'API 연결·인증 확인':'원고·공개 결과·유입 확인';if(detail)detail.textContent=op.detail;if(operating)operating.textContent=op.label+' · 공개 확인·유입은 별도';});
  refresh();setInterval(()=>refresh(),60000);
})();
