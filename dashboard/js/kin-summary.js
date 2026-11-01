/* Shared read-only KnowledgeIn snapshot. One request per page, cached 60 seconds. */
(() => {
  'use strict';
  if (window.BaroLabKinSummary) return;
  const CACHE_MS = 60000, STALE_MS = 30 * 60000;
  const listeners = new Set();
  let current = {status:'loading',data:null,fetchedAt:null,stale:true,error:null};
  let pending = null, fetchedAtMs = 0;
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
  function getState() {
    const checked = current.data && Date.parse(current.data.checkedAt);
    return {...current, stale:current.status === 'error' || !Number.isFinite(checked) || Date.now()-checked > STALE_MS};
  }
  function notify() {
    const state=getState();
    listeners.forEach(listener => {try {listener(state);} catch (_) {/* Isolate consumers. */}});
    window.dispatchEvent(new CustomEvent('barolab-kin-updated',{detail:state}));
  }
  function subscribe(listener) {
    if (typeof listener !== 'function') throw new TypeError('Listener required');
    listeners.add(listener); listener(getState());
    return () => listeners.delete(listener);
  }
  async function refresh({force=false}={}) {
    if (pending) return pending;
    if (!force && Date.now()-fetchedAtMs < CACHE_MS) return getState();
    pending=(async()=>{
      try {
        const response=await fetch('data/kin.json',{cache:'no-store',signal:AbortSignal.timeout(15000)});
        if (!response.ok) throw new Error('Snapshot unavailable');
        const data=await response.json();
        if (!data || typeof data !== 'object' || Array.isArray(data) || data.schema !== 'naver-kin-pilot-v1') throw new Error('Snapshot invalid');
        fetchedAtMs=Date.now();
        current={status:'ready',data,fetchedAt:new Date(fetchedAtMs).toISOString(),stale:false,error:null};
      } catch (_) {
        fetchedAtMs=Date.now();
        current={...current,status:'error',error:'지식iN 운영 기록 조회 실패'};
      }
      notify(); return getState();
    })();
    try {return await pending;} finally {pending=null;}
  }
  function operationState(state=getState()) {
    const data=state.data || {}, auto=data.automation || {};
    const result=(status,label,detail)=>({status,label,detail,configEnabled:typeof auto.enabled === 'boolean' ? auto.enabled : null});
    if(state.status === 'loading') return result('loading','조회 중','운영 기록 확인 중');
    if(state.status === 'error') return result('unknown','조회 실패','운영 기록 최신 조회 실패 · 마지막 기록과 구분');
    if(state.stale) return result('unknown','갱신 필요','운영 기록이 오래됨 · 현재 작업 상태 미확인');
    if(auto.activeRunId) return result('running','작업 중','실제 작업 진행 중 · 종료 후 최소 60분 대기');
    if(auto.cadenceState === 'experiment_completed') return result('ended','시험 종료','게시 시험 종료 · 유입 측정 보완은 별도 진행');
    if(auto.enabled === false) return result('disabled','꺼짐','자동 운영 설정 꺼짐');
    const observed=auto.lastRun && auto.lastRun.registeredTasks || data.schedule && data.schedule.registeredTasks;
    const observedAt=Date.parse(observed && observed.checkedAt);
    const fresh=Number.isFinite(observedAt) && Date.now()-observedAt <= STALE_MS;
    const task=observed && observed.status === 'observed' && fresh && Array.isArray(observed.tasks) ? observed.tasks.find(item=>item.taskName === 'BaroLab-Kin-Seven-Day-Pilot') : null;
    if(task && (task.registered === false || task.enabled === false)) return result('task_issue','작업 확인','자동 실행 작업 등록·활성 상태 확인 필요');
    if(auto.enabled === true && task && task.registered === true && task.enabled === true) return result('waiting','대기','자동 실행 작업 등록·활성 확인 · 계정 교대 대기');
    return result('unknown','확인 필요',(auto.enabled === true ? '자동 운영 설정은 켜짐 · ' : '')+'실제 자동 실행 상태 미확인');
  }
  function summarize(state=getState()) {
    const data=state.data || {}, automation=data.automation || {}, measurement=data.measurement || {};
    const isTrial=measurement.periodKind === 'trial_to_yesterday' && measurement.trialCollectionPending !== true;
    const validTrial=isTrial && measurement.status === 'collected' && measurement.complete === true;
    const measuredAt=Date.parse(measurement.checkedAt);
    const today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Seoul'});
    const daily=data.daily && data.daily.date === today ? data.daily : {};
    return {today, dailyDate:data.daily && data.daily.date, todayAttempted:count(daily.attempted), todayPublished:count(daily.publishedVerified), operation:operationState(state),
      totalPublished:count(data.counts && data.counts.published_verified), automation, measurement,
      trialSessions:validTrial ? count(measurement.sessions) : null,
      trialEngagedSessions:validTrial ? count(measurement.engagedSessions) : null,
      trialPageViews:validTrial ? count(measurement.pageViews) : null,
      measurementKind:isTrial ? (validTrial ? 'trial' : 'trial_incomplete') : (measurement.periodKind === 'baseline' ? 'baseline' : 'unknown'),
      measurementStale:!Number.isFinite(measuredAt) || Date.now()-measuredAt > 48*60*60000,
      publisherRevenue:null, revenueStatus:measurement.revenueStatus || 'unmeasured'};
  }
  function element(tag,text,className) {
    const item=document.createElement(tag); if(text!==undefined)item.textContent=String(text); if(className)item.className=className; return item;
  }
  function render(mount,state) {
    const view=summarize(state), data=state.data;
    mount.replaceChildren(); mount.classList.add('kin-summary-card');
    const head=element('div',undefined,'kin-summary-head'); head.append(element('h2','네이버 지식iN'));
    const detail=element('a','운영 상세 →'); detail.href='kin.html'; head.append(detail); mount.append(head);
    if (!data) {mount.append(element('p',state.status === 'loading' ? '운영 기록 조회 중' : '운영 기록 미확인','kin-summary-note'));return;}
    const mode=mount.dataset.kinSummary;
    const metrics=element('div',undefined,'kin-summary-metrics');
    const add=(label,value)=>{const item=element('div');item.append(element('span',label),element('strong',value === null ? '미확인' : value));metrics.append(item);};
    if(mode !== 'traffic') {add('오늘 제출 시도',view.todayAttempted);add('오늘 공개 검증',view.todayPublished);}
    add('시험 기간 UTM 세션',view.trialSessions);
    mount.append(metrics);
    const auto=view.automation;
    const operating=view.operation.label+' · '+view.operation.detail;
    if(mode !== 'traffic') mount.append(element('p',operating,'kin-summary-note'));
    let measurementText='시험 유입 미확인';
    if(view.measurementKind === 'baseline') measurementText='기준 기간 '+view.measurement.startDate+' ~ '+view.measurement.endDate+' 집계 · 시험 유입은 아직 미집계';
    else if(view.measurementKind === 'trial') measurementText='시험 유입 '+view.measurement.startDate+' ~ '+view.measurement.endDate+' KST · 어제까지 · 잠정 집계';
    else if(view.measurementKind === 'trial_incomplete') measurementText='시험 유입 일부 수집 또는 미수집 · 전체 세션 합계 미확인';
    mount.append(element('p',measurementText + (view.measurementStale ? ' · 측정 기록이 오래되었거나 시각 미확인' : ''),'kin-summary-note'));
    if(mode === 'traffic') mount.append(element('p','Must-good · Must-pick / naver_kin · referral · cf_bridge. CF 전체 방문에 별도로 더하지 않습니다. 게시자 수익은 미검증입니다.','kin-summary-note'));
    else mount.append(element('p','오늘 '+view.today+' KST 기준 · 작업 처리와 답변 공개·방문·수익은 별도입니다.','kin-summary-note'));
    const updated=Date.parse(data.checkedAt);
    const stamp=Number.isFinite(updated) ? new Date(updated).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})+' KST' : '미확인';
    mount.append(element('p',(state.stale ? '오래되었거나 최신 조회 실패 · ' : '')+'운영 기록 '+stamp,'kin-summary-updated'));
  }
  window.BaroLabKinSummary={getState,refresh,subscribe,summarize,operationState};
  document.querySelectorAll('[data-kin-summary]').forEach(mount=>subscribe(state=>render(mount,state)));
  refresh();
  setInterval(()=>refresh(),CACHE_MS);
})();
