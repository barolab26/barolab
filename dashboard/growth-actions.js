/* Shared growth evidence and improvement records. No publishing actions. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('growth-action-center')) return;
  const statuses = {planned:'계획',in_progress:'진행 중',done:'수정 완료'};
  const number = (v, digits=0) => v == null || !Number.isFinite(Number(v)) ? '미수집' : Number(v).toLocaleString('ko-KR',{maximumFractionDigits:digits});
  const element = (parent,tag,value='',className='') => {const e=document.createElement(tag);e.textContent=value;if(className)e.className=className;parent.appendChild(e);return e;};
  const period = v => v?.start && v?.end ? `${v.start} ~ ${v.end}` : '기간 미확인';
  const cleanTitle = (url, title) => {
    const raw = title || url || '';
    try {
      if (raw.startsWith('https://')) {
        const u = new URL(raw);
        const path = decodeURIComponent(u.pathname).replace(/^\/+|\/+$/g, '');
        return path ? path.replace(/-/g, ' ') : raw;
      }
      return decodeURIComponent(raw);
    } catch (_) { return raw; }
  };
  const link = (parent,url,title) => {const label=cleanTitle(url,title);try{const u=new URL(url);if(u.protocol!=='https:')return element(parent,'span',label);const a=element(parent,'a',label);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch(_){return element(parent,'span',label);}};
  const pct = v => v == null ? '미수집' : `${number(Number(v)*100,2)}%`;
  const money = v => v?.amounts && Object.keys(v.amounts).length ? Object.entries(v.amounts).map(([c,a])=>`${c} ${number(a,2)}`).join(' · ')+(v.complete===false?' · 일부 수집':'') : '미수집';
  let data={}, busy=false;
  let maintenanceData={},maintenanceBusy=false,policyDirty=false;
  const issueLabels={title_intent_mismatch:'제목과 검색 의도 불일치',missing_direct_answer:'직접적인 답변 부족',unsupported_claim:'근거 없는 주장',outdated_claim:'오래된 정보',broken_link:'깨진 링크',missing_source:'출처 누락',duplicate_or_thin_answer:'중복·답변 부족',technical_canonical:'대표 주소 설정',access_or_noindex:'접근·색인 설정',readability_structure:'읽기 구조'};
  const maintenanceStatuses={running:'작업 진행 중',enabled:'자동 운영 사용',disabled:'자동 운영 꺼짐',idle:'다음 작업 대기',completed:'작업 완료',publishing_wait:'발행 우선 · 유지관리 대기',publishing_priority_wait:'발행 우선 · 유지관리 대기',cooldown:'재작업 간격 대기',retry_wait:'재시도 대기',backoff:'검사 제한 · 재시도 대기',excluded_unknown:'근거 부족 · 자동수정 제외',excluded:'자동수정 제외',review_failed:'독립 검수 실패 · 적용 차단',verification_failed:'공개 확인 실패 · 재확인 필요',failed:'작업 실패 · 재시도 확인',paused:'자동 운영 정지',blocked:'조건 확인 대기'};
  const stageLabels={investigation:'조사',investigate:'조사',research:'조사',draft:'수정안 작성',edit:'수정안 작성',review:'독립 검수',independent_review:'독립 검수',apply:'기존 글 수정',applying:'기존 글 수정',verify:'공개 확인',public_verification:'공개 확인',followup:'후속 성과 확인',queued:'대기'};
  Object.assign(maintenanceStatuses,{queued:'미평가 · 조사 대기',processing:'조사 진행 중',prepared:'수정안 준비 · 적용 전',ready:'검수된 수정안 · 적용 전',no_change:'원문 유지 · 변경 없음',rolled_back:'원문 복구',partial_failure:'일부 작업 실패 · 재시도 확인',waiting:'운영 간격·상한 대기'});
  Object.assign(stageLabels,{audit:'전체 글 기본 점검',monitor:'후속 성과 대기',rollback:'원문 복구',idle:'다음 회차 대기'});
  issueLabels.existing_content_unassessed='기존 글 · 아직 미평가';
  function maintenanceIssue(item) {const issue=item.issue;const kind=typeof issue==='string'?issue:issue?.kind;return issueLabels[kind]||item.issueLabel||'문제 근거 확인 중';}
  function maintenanceEvidence(parent,item) {
    const audit=item.evidence;
    if(audit&&!Array.isArray(audit)&&audit.checkedAt)element(parent,'small',`기본 구조 점검 ${timeLabel(audit.checkedAt)} · 공개 페이지 ${audit.coverage?.publicPage===true?'확인':'미확인'}`);
    const research=item.researchEvidence;
    if(!research){element(parent,'small','검색·외부 출처 조사 근거 미수집');return;}
    const c=research.coverage||{};
    element(parent,'p',`심층 조사 · 검색 결과 ${number(c.searches)}건 · 비교 글 ${number(c.competitors)}건 · 1차 출처 ${number(c.primarySources)}건`);
    for(const issue of research.issues||[]){element(parent,'p',`${issueLabels[issue.kind]||'문제 분류 확인 중'} · ${issue.confidence==='observed'?'원천 관측':'가설 · 자동수정 근거 제외'}`);for(const e of (issue.evidence||[]).slice(0,2))if(e.quote)element(parent,'blockquote',e.quote.slice(0,300));}
    for(const unknown of research.unknowns||[])element(parent,'small',`미확인: ${unknown}`);
  }
  function renderAutonomy(summary,p,r) {
    const growth=maintenanceData.growth||{},goal=growth.goal||{},ego=r.egoStatus||{},selection=r.jevSelection||{};
    const card=(title,value,detail)=>{const node=element(summary,'div','','growth-action-card');element(node,'span',title);element(node,'strong',value);element(node,'p',detail);return node;};
    const sourceLabels={success:'수집 확인',partial:'일부 수집',partial_failure:'일부 수집 실패',failed:'수집 실패',failure:'수집 실패',unknown:'수집 미확인'};
    const egoLabel=ego.status==='completed'?'최근 회차 처리 종료':ego.status==='already_running'?'기존 회차 실행 중':maintenanceStatuses[ego.status]||'실행 기록 미확인';
    const egoCard=card('EGO LITE · 최근 실행 결과',egoLabel,`최근 회차 ${timeLabel(r.egoLastCycleAt)} · 원천 자료 ${sourceLabels[ego.sourceStatus]||'수집 미확인'}`);
    if(ego.reason)element(egoCard,'small',ego.reason);
    if(ego.nextCycleAt)element(egoCard,'small',`다음 회차 ${timeLabel(ego.nextCycleAt)}`);
    const selectionLabels={ok:selection.selected?'후보 선별 완료':'통과 후보 대기',no_fresh_candidates:'새 원천 자료 대기',not_configured:'연결 설정 미확인',invalid_input:'입력 검증 실패',api_error:'API 오류 · 적용 차단',invalid_response:'응답 검증 실패 · 적용 차단'};
    const jevMode=p.jevEnabled===true?'사용':p.jevEnabled===false?'꺼짐':'설정 미확인';
    const reviewed=[...(maintenanceData.queue||[]),...(maintenanceData.recentActions||[])].filter(item=>item.jevReview).sort((a,b)=>(Date.parse(b.jevReview.checkedAt)||0)-(Date.parse(a.jevReview.checkedAt)||0))[0];
    const review=reviewed?.jevReview;
    const reviewLabel=review?.status==='ok'?({pass:'통과',review:reviewed?.jevEscalation?.status==='passed'?'독립 재검수 통과':'보류 · 독립 재검수 필요',reject:'반려 · 적용 차단'}[review.decision]||'미확인'):review?'검수 호출 실패 · 적용 차단':'검수 기록 미확인';
    const jevCard=card('JEV · 후보 선별·검수',`${jevMode} · ${selectionLabels[selection.status]||'선별 기록 미확인'}`,`최근 선별 ${timeLabel(selection.checkedAt)} · 최근 검수 ${reviewLabel}`);
    element(jevCard,'small','JEV 판단은 수익 예측이나 공개 수정 허가가 아닙니다.');
    const measured=goal.currency==='USD'&&['achieved','in_progress'].includes(goal.status)&&typeof goal.daily_average==='number'&&Number.isFinite(goal.daily_average);
    const target=typeof goal.daily_target==='number'&&Number.isFinite(goal.daily_target)?goal.daily_target:100;
    const goalCard=card('일수익 목표 · 30일 일평균',`현재 ${measured?`USD ${number(goal.daily_average,2)}`:'미확인'} / 목표 USD ${number(target,2)}`,`${period(goal)} · 전체 등록 CF 사이트`);
    element(goalCard,'small',measured?(goal.status==='achieved'?'30일 일평균 목표 기준 충족':'목표 진행 중'):(goal.reason||'동일 기준의 전체 사이트 30일 USD 수익 미수집'));
    const experiments=Array.isArray(growth.experiments)?growth.experiments:null;
    const observing=(experiments||[]).filter(item=>item.verification?.status==='observing').length;
    const experimentCard=card('개선 실험 · 후속 관측',experiments?experiments.length?`관측 중 ${number(observing)}건 · 전체 ${number(experiments.length)}건`:'등록 실험 없음':'실험 기록 미확인','공개 반영과 수익 달성은 별개 · 개선의 인과효과 미입증');
    for(const item of (experiments||[]).slice(0,3)){
      const experiment=item.experiment||{},observation=item.observation||experiment.measurement||{};
      const label={observing:'관측 중',awaiting_evidence:'관측 기간 종료 · 자료 대기',observed_change:'전후 관측값 확보 · 효과 미입증'}[item.verification?.status]||'관측 상태 미확인';
      link(element(experimentCard,'p'),item.url,item.domain||item.url);
      element(experimentCard,'small',`${label} · ${period(observation)} (${observation.sourceTimezone||'원천 시간대 미확인'})`);
      element(experimentCard,'small',`검증 예정 ${timeLabel(experiment.measurementDueAt)} · 페이지 수익 효과 미확인`);
    }
    if(experiments?.length>3)element(experimentCard,'small',`최근 3건 표시 · 전체 ${number(experiments.length)}건`);
  }
  function renderMaintenance() {
    const state=$('maintenance-status');if(!state)return;const p=maintenanceData.policy||{},r=maintenanceData.runtime||{},queue=maintenanceData.queue||[],c=maintenanceData.coverage||{};
    const runtimeLabel=r.status==='completed'?'최근 회차 처리 종료':maintenanceStatuses[r.status]||'실행 상태 미확인';
    const pendingTotal=c.byStatus?Object.entries(c.byStatus).filter(([key])=>!['completed','no_change'].includes(key)).reduce((total,[,value])=>total+value,0):null;
    const enabled=typeof p.enabled==='boolean'?(p.enabled?'자동 점검 운영 중':'자동 점검 꺼짐'):'운영 설정 미확인';
    const readiness=maintenanceData.writeReadiness||{};
    const readinessLabels={disabled:'자동수정 꺼짐',awaiting_canary:'검수된 첫 수정 후보 대기',first_canary:'검수된 첫 기존 글 자동 검증',ready:'자동수정 가능',daily_limit:'일일 수정 상한 대기',publishing_wait:'발행 우선 · 수정 대기',reconciliation_wait:'이전 수정 결과 확인 대기'};
    const writeLabel=readinessLabels[readiness.status]||(readiness.canApply===true?'자동수정 가능':readiness.canApply===false?'자동수정 대기':'자동수정 가능 여부 미확인');
    state.textContent=`${enabled} · ${writeLabel}${readiness.reason?` · ${readiness.reason}`:''} · ${runtimeLabel}${r.stage?` · 현재 단계 ${stageLabels[r.stage]||'단계 확인 중'}`:''}${r.reason?` · ${r.reason}`:''}`;
    const summary=$('maintenance-summary');if(summary){summary.replaceChildren();for(const [title,value,detail] of [['실제 작업 상태',runtimeLabel,`최근 시도 ${timeLabel(r.lastAttemptAt)} · 최근 점검 ${timeLabel(r.lastAuditAt)}`],['대기·검토 목록',pendingTotal==null?'범위 미확인':`${number(pendingTotal)}건`,`표시 ${queue.length}건${r.nextRetryAt?` · 재시도 ${timeLabel(r.nextRetryAt)}`:''}`],['운영 상한',p.maxPerCycle==null?'미확인':`회차당 ${number(p.maxPerCycle)}건`,`${p.maxUpdatesPerDay==null?'일일 상한 미확인':`일 ${number(p.maxUpdatesPerDay)}건`} · ${number(p.cooldownHours)}h 간격`]]){const card=element(summary,'div','','growth-action-card');element(card,'span',title);element(card,'strong',value);element(card,'p',detail);}renderAutonomy(summary,p,r);}
    const covEl=$('maintenance-coverage');if(covEl){covEl.textContent=Number.isSafeInteger(c.known)?`등록 ${number(c.known)}건 · 점검 ${number(c.basicAudited??c.audited)}건 · 미평가 ${number(c.neverAudited)}건 · 심층검토 ${number(c.deepReviewed)}건`:(c.reason||'근거 수집 범위 확인 중');}
    const form=$('maintenance-policy-form');if(form&&!policyDirty&&!form.contains(document.activeElement)){$('maintenance-enabled').checked=p.enabled===true;$('maintenance-enabled').disabled=typeof p.enabled!=='boolean';$('maintenance-max').value=p.maxPerCycle??'';$('maintenance-cooldown').value=p.cooldownHours??'';}
    const parent=$('maintenance-queue');if(parent){parent.replaceChildren();for(const item of queue){const card=element(parent,'article','','growth-record');element(card,'small',item.domain||'도메인 미확인');link(element(card,'h4'),item.url,maintenanceIssue(item));element(card,'p',`${maintenanceStatuses[item.status]||'상태 확인 중'}${item.stage?` · ${stageLabels[item.stage]||'단계 확인 중'}`:''} · ${item.reason||''}`);for(const e of (Array.isArray(item.evidence)?item.evidence:(item.evidence?.issues||[]).flatMap(issue=>issue.evidence||[]).concat(item.issue?.evidence||[])).slice(0,2)){if(e.quote)element(card,'blockquote',e.quote.slice(0,220));}maintenanceEvidence(card,item);if(item.nextRetryAt)element(card,'small',`재시도 ${timeLabel(item.nextRetryAt)}`);}if(!queue.length)element(parent,'p','현재 대기 목록이 없습니다.','growth-empty');}
    const receipts=$('maintenance-receipts');if(receipts){receipts.replaceChildren();for(const item of maintenanceData.recentActions||[]){const card=element(receipts,'article','','growth-record');element(card,'small',`${item.domain||'도메인 미확인'} · ${maintenanceStatuses[item.status]||'상태 확인 중'}`);link(element(card,'h4'),item.url,item.action||maintenanceIssue(item));element(card,'p',item.reason||'');maintenanceEvidence(card,item);element(card,'p',`독립 검수: ${{passed:'통과',changes_required:'보완 필요',rejected:'반려',failed:'실패',pending:'대기'}[item.review?.status]||'미확인'} · 공개 확인: ${{verified:'완료',passed:'완료',failed:'실패',pending:'대기'}[item.publicVerification?.status]||'미확인'} (${timeLabel(item.publicVerification?.checkedAt)})`);if(item.diffText){const details=element(card,'details');element(details,'summary','실제 변경 내용');element(details,'pre',item.diffText);}}if(!receipts.children.length)element(receipts,'p','아직 자동 변경 영수증이 없습니다.','growth-empty');}
    window.BaroLabTopKpi?.refresh();
  }
  async function loadMaintenance() {if(maintenanceBusy)return;maintenanceBusy=true;try{maintenanceData=await api('/api/growth/maintenance');renderMaintenance();}catch(e){const n=$('maintenance-status');if(n)n.textContent=`자동 운영 조회 실패 · ${e.message}`;}finally{maintenanceBusy=false;}}
  const timeLabel = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}) : '미확인';
  function openDiagnosis(domain) {
    window.BaroLabGrowthTabs?.activateTab('tab-revenue');
    const select=$('growth-diagnosis-domain');if(!select)return;
    if([...select.options].some(o=>o.value===domain))select.value=domain;
    renderDiagnosis();
    const details=select.closest('details');
    if(details)details.open=true;
    setTimeout(()=>{(details||select).scrollIntoView({behavior:'smooth',block:'nearest'});},40);
  }
  function preparePlan(domain,url,action) {
    window.BaroLabGrowthTabs?.activateTab('tab-remodel');
    const form=$('growth-action-form');if(!form)return;
    const drawer=form.closest('details');if(drawer)drawer.open=true;
    if($('growth-record-domain'))$('growth-record-domain').value=domain;
    if($('growth-record-url'))$('growth-record-url').value=url||'';
    if($('growth-record-action'))$('growth-record-action').value=action||'';
    setTimeout(()=>{form.scrollIntoView({behavior:'smooth',block:'center'});$('growth-record-action')?.focus();},50);
  }
  function renderCollection() {
    const parent=$('growth-collection-health');if(!parent)return;parent.replaceChildren();const c=data.diagnosis?.collection;
    if(!c){element(parent,'strong','지속 수집 실행 이력 확인 중');return;}
    const labels={running:'정기 수집 실행 중',completed:'최근 수집 실행 종료',collected:'최근 자료 갱신 완료',partial:'일부 자료 수집',partial_failure:'일부 수집 확인 필요',stalled:'수집 지연',collection_delayed:'수집 지연',on_schedule:'정기 실행 주기 유지',not_started:'첫 수집 대기',unknown:'수집 상태 미확인',backoff:'검사 제한 대기',browser_busy:'브라우저 작업 대기',error:'수집 오류',idle:'다음 수집 대기',not_collected:'수집 이력 미확인'};
    const comparable=(data.domains||[]).filter(d=>d.comparable===true).length;
    element(parent,'strong',`${labels[c.status]||'수집 상태 확인'} · 28일 비교 ${comparable}/${(data.domains||[]).length}개 도메인`);
    element(parent,'small',`최근 갱신 ${timeLabel(c.lastSuccessAt)} · 검사 대기 ${number(c.backlog)}건 · 오류 ${number(c.failures)}건`);
  }
  function contributorTable(parent,rows,page,domain) {
    element(parent,'h4',page?'클릭 변화 상위 페이지':'클릭 변화 상위 검색어');
    if(!rows?.length){element(parent,'p','두 기간 공통 관측 행 없음','growth-empty');return;}
    const wrap=element(parent,'div','','revenue-table-wrap');const table=element(wrap,'table','','traffic-table growth-contributor-table');const header=element(element(table,'thead'),'tr');for(const title of [page?'페이지':'검색어','클릭 현재 / 이전','클릭 변화','노출 변화'])element(header,'th',title);
    const body=element(table,'tbody'),limit=$('growth-domain-comparison')?8:3;
    for(const r of rows.slice(0,limit)){const tr=element(body,'tr'),name=element(tr,'td');if(page){link(name,r.url,r.title||r.url);if($('growth-action-form')){const button=element(name,'button','개선 계획','btn-quick');button.type='button';button.style.marginLeft='6px';button.addEventListener('click',()=>preparePlan(domain,r.url,'관측된 클릭 변화 원인 확인과 개선안 정리'));}}else{element(name,'span',r.query);if(r.scope==='page_query'&&r.url)link(element(name,'small'),r.url,'연결 페이지');}
      element(tr,'td',`${number(r.current?.clicks)} / ${number(r.previous?.clicks)}`);
      const matched=r.comparable===true&&r.status==='matched';element(tr,'td',matched?`${r.clickDelta>0?'+':''}${number(r.clickDelta)}`:'비교 미확인');element(tr,'td',matched?`${r.impressionDelta>0?'+':''}${number(r.impressionDelta)}`:'비교 미확인');
    }
  }
  function renderDiagnosis() {
    const parent=$('growth-diagnosis-content'),select=$('growth-diagnosis-domain');if(!parent||!select)return;parent.replaceChildren();
    const d=(data.diagnosis?.domains||[]).find(r=>r.domain===select.value);
    if(!d){element(parent,'p','해당 도메인의 진단 근거를 수집 중입니다.','growth-empty');return;}
    const grid=element(parent,'div','','growth-diagnosis-grid'),facts=element(grid,'section','','growth-diagnosis-block');element(facts,'h4','확인된 사실');const factList=element(facts,'ul');for(const fact of d.facts||[])element(factList,'li',fact);if(!factList.children.length)element(factList,'li','확정할 비교 근거가 없습니다.');
    const hypotheses=element(grid,'section','','growth-diagnosis-block');element(hypotheses,'h4','원인 가설 (참고용)');for(const h of d.hypotheses||[]){const item=element(hypotheses,'div','','growth-hypothesis');element(item,'strong',h.reason);element(item,'p',`근거 수준: ${{low:'낮음',medium:'중간',high:'높음'}[h.confidence]||h.confidence||'미확인'} · ${h.evidence||''}`);}if(!(d.hypotheses||[]).length)element(hypotheses,'p','추정 가설 없음','growth-evidence');
    const decomposition=d.decomposition;if(decomposition?.identityVerified===true)element(parent,'p',`클릭 변화 ${number(decomposition.clickDelta,2)} (노출 기여 ${number(decomposition.impressionEffect,2)} · CTR 기여 ${number(decomposition.ctrEffect,2)})`,'growth-evidence');
    contributorTable(parent,d.pageContributors,true,d.domain);contributorTable(parent,d.queryContributors,false,d.domain);
    const actions=element(parent,'div','','growth-diagnosis-actions');for(const action of d.actions||[]){const card=element(actions,'article','','growth-diagnosis-action');element(card,'strong',action.action);element(card,'p',action.reason);if($('growth-action-form')){const button=element(card,'button','개선 계획 등록','btn-quick');button.type='button';button.addEventListener('click',()=>preparePlan(d.domain,action.url||'',action.action));}}
  }
  function renderDiagnosisOptions() {
    const select=$('growth-diagnosis-domain');if(!select)return;const defaultDomain=[...(data.domains||[])].filter(r=>r.comparable===true).sort((a,b)=>Math.abs(b.current.clicks-b.previous.clicks)-Math.abs(a.current.clicks-a.previous.clicks))[0]?.domain;
    const old=select.value||new URLSearchParams(location.search).get('diagnosis')||defaultDomain;select.replaceChildren();for(const d of data.diagnosis?.domains||[])element(select,'option',d.domain).value=d.domain;if([...select.options].some(o=>o.value===old))select.value=old;renderDiagnosis();
  }
  function assessment(row) {
    if(row.comparable===true) return row.current.clicks>row.previous.clicks?'검색 클릭 성장':row.current.clicks<row.previous.clicks?'검색 클릭 감소':'검색 클릭 동일';
    return row.reason || '두 기간 보고서 미확인';
  }
  async function api(path,method='GET',body) {
    const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json','x-barolab-settings':'1'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
    const j=await r.json();if(!r.ok)throw new Error(typeof j.detail==='string'?j.detail:'공유 기록 서버 연결을 확인하세요.');return j;
  }
  function metric(td,current,previous,key,format=number,comparable=false) {
    td.className='growth-metric';element(td,'strong',format(current?.[key]));element(td,'small',`이전 ${format(previous?.[key])}`);
    const a=current?.[key],b=previous?.[key];if(!comparable||a==null||b==null||key==='revenue')return;
    if(key==='ctr')element(td,'em',`${number((a-b)*100,2)}%p 변화`);
    else if(key==='position')element(td,'em',a===b?'동일':`${number(Math.abs(a-b),1)}위 ${a<b?'상승':'하락'}`);
    else element(td,'em',b>0?`${a>=b?'+':''}${number((a-b)/b*100,1)}% 변화`:a>0?'이전 0 · 새 관측':'두 기간 0');
  }
  function renderDomains() {
    const domains=data.domains||[],body=$('growth-domain-comparison');
    if(body){body.replaceChildren();for(const r of domains){const tr=element(body,'tr');const first=element(tr,'td');element(first,'strong',r.domain);element(first,'small',r.reason||r.scope||'');for(const [key,format] of [['impressions',number],['clicks',number],['ctr',pct],['position',v=>v==null?'미수집':`${number(v,1)}위`],['revenue',money]])metric(element(tr,'td'),r.current,r.previous,key,format,r.comparable===true);const state=element(tr,'td',r.assessment||r.statusLabel||assessment(r));if(r.current?.revenue?.reason)element(state,'small',r.current.revenue.reason);}if(!domains.length){const td=element(element(body,'tr'),'td','비교 보고서 수집 전입니다.');td.colSpan=7;}}
    const select=$('growth-record-domain');if(select){const old=select.value;select.replaceChildren();for(const r of domains)element(select,'option',r.domain).value=r.domain;if(domains.some(r=>r.domain===old))select.value=old;}
    if(body)for(const [i,row] of domains.entries()){const cell=body.rows[i]?.cells[0];if(cell){const button=element(cell,'button','변화 근거','btn-quick');button.type='button';button.style.marginTop='4px';button.addEventListener('click',()=>openDiagnosis(row.domain));}}
    const summary=$('growth-action-summary');if(summary){summary.replaceChildren();
    const comparable=domains.filter(r=>r.current?.clicks!=null&&r.previous?.clicks!=null&&r.comparable===true);
    const up=comparable.filter(r=>r.current.clicks>r.previous.clicks),down=comparable.filter(r=>r.current.clicks<r.previous.clicks);
    for(const [title,value,description] of [['검색 클릭 성장',comparable.length?`${up.length}개 도메인`:'비교 미확인',up.map(r=>r.domain).join(' · ')||'동일 기간 비교 가능 도메인'],['성장 둔화 · 하락',comparable.length?`${down.length}개 도메인`:'비교 미확인',down.map(r=>r.domain).join(' · ')||'클릭 감소 도메인 없음'],['28일 비교 가능 범위',`${comparable.length}/${domains.length}개 도메인`,'GSC 28일 현재 vs 이전 28일']]){const card=element(summary,'div','','growth-action-card');element(card,'span',title);element(card,'strong',value);element(card,'p',description);}
    for(const [index,rows] of [[0,up],[1,down]])if(rows.length){const parent=summary.children[index].querySelector('p');parent.replaceChildren();for(const row of rows){const button=element(parent,'button',`${row.domain} · 근거`,'btn-quick');button.type='button';button.addEventListener('click',()=>openDiagnosis(row.domain));}}}
  }
  function renderPriorities() {
    const parent=$('growth-priorities');if(!parent)return;parent.replaceChildren();const items=(data.priorities||[]).slice(0,9);
    for(const r of items){const card=element(parent,'article','','growth-priority');element(card,'small',r.domain);link(element(card,'h4'),r.url,r.title||r.url);element(card,'p',r.reason||r.action||'근거 확인 필요');element(card,'div',`노출 ${number(r.impressions)} · 클릭 ${number(r.clicks)} · 평균 ${r.position==null?'미수집':number(r.position,1)+'위'}`,'growth-evidence');if($('growth-action-form')){const b=element(card,'button','이 글 개선 계획 기록','btn-quick');b.type='button';b.addEventListener('click',()=>preparePlan(r.domain,r.url,r.action||r.reason||''));}}
    if(!items.length)element(parent,'p','현재 근거로 선정할 개선 우선 글이 없습니다.','growth-empty');
    const groups=$('growth-index-reasons');if(groups){groups.replaceChildren();for(const r of data.indexReasons||[]){const c=element(groups,'div','','growth-reason');element(c,'span',r.reason||r.label);element(c,'strong',`${number(r.count)}개`);if(r.action)element(c,'small',r.action);}if(!groups.children.length)element(groups,'p','현재 확인된 미색인 원인 그룹이 없습니다.','growth-empty');}
  }
  function renderRecords() {
    const parent=$('growth-action-records');if(!parent)return;parent.replaceChildren();
    for(const r of data.records||[]){const card=element(parent,'article','','growth-record');element(card,'small',`${r.domain} · 기록 ${r.createdAt||'시각 미확인'}`);link(element(card,'h4'),r.url,r.action);if(r.note)element(card,'p',r.note);
      const controls=element(card,'div','','growth-record-controls');const select=element(controls,'select');select.setAttribute('aria-label',`${r.action} 진행 상태`);for(const [v,t]of Object.entries(statuses))element(select,'option',t).value=v;select.value=r.status;
      const label=element(controls,'label','완료일 ');const date=element(label,'input');date.type='date';date.max=new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Seoul'});date.value=r.completedAt?.slice(0,10)||'';const save=element(controls,'button','상태 저장','btn-quick');save.type='button';const feedback=element(controls,'span');feedback.setAttribute('role','status');
      if(r.status==='done'){select.disabled=true;date.disabled=true;save.disabled=true;save.textContent='완료 기록 보존';}
      save.addEventListener('click',async()=>{if(select.value==='done'&&(!date.value||date.value>date.max)){feedback.textContent='실제로 수정한 날짜를 입력하세요.';return;}save.disabled=true;try{await api(`/api/growth/actions/${encodeURIComponent(r.id)}`,'PATCH',{status:select.value,completedAt:select.value==='done'?date.value:null});await load();}catch(e){feedback.textContent=e.message;}finally{save.disabled=false;}});
      const baseline=r.baseline,follow=r.followup;if(baseline)element(card,'p',`수정 전 기준: ${period(baseline)} · 노출 ${number(baseline.impressions)} · 클릭 ${number(baseline.clicks)} · 평균 ${baseline.position==null?'미수집':number(baseline.position,1)+'위'}`,'growth-evidence');
      else if(r.planningBaseline)element(card,'p',`계획 당시 관측: ${period(r.planningBaseline)} · 노출 ${number(r.planningBaseline.impressions)} · 클릭 ${number(r.planningBaseline.clicks)}`,'growth-evidence');
      if(follow)element(card,'p',`후속 관측: ${period(follow)} · 노출 ${number(follow.impressions)} · 클릭 ${number(follow.clicks)}`,'growth-evidence');
    }if(!parent.children.length)element(parent,'p','아직 공유 개선 기록이 없습니다.','growth-empty');
  }
  function render() {
    if($('growth-comparison-period'))$('growth-comparison-period').textContent=`현재 ${period(data.periods?.current)} vs 이전 ${period(data.periods?.previous)} (${data.searchTimezone||data.periods?.searchTimezone||'PT'})`;
    const priorityTotal=(data.priorities||[]).length,priorityShown=Math.min(priorityTotal,9);
    const srcEl=$('growth-action-source');
    if(srcEl){
      srcEl.textContent=`개선 우선 후보 ${priorityTotal}개 중 상위 ${priorityShown}개 선별`;
      srcEl.title=data.note||'관측된 성과만 표시하며 미수집을 0으로 계산하지 않습니다.';
    }
    renderDomains();renderPriorities();renderRecords();renderCollection();renderDiagnosisOptions();
    window.BaroLabTopKpi?.refresh();
  }
  async function load() {if(busy)return;busy=true;try{data=await api('/api/growth/action-center');render();}catch(e){if($('growth-comparison-period'))$('growth-comparison-period').textContent=`성장 비교 조회 실패 · ${e.message}`;}finally{busy=false;}}
  $('growth-action-form')?.addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,button=form.querySelector('button[type="submit"]');button.disabled=true;try{await api('/api/growth/actions','POST',{domain:$('growth-record-domain').value,url:$('growth-record-url').value.trim(),action:$('growth-record-action').value.trim(),note:$('growth-record-note').value.trim()});$('growth-record-feedback').textContent='공유 개선 계획을 저장했습니다.';form.reset();await load();}catch(e){$('growth-record-feedback').textContent=e.message;}finally{button.disabled=false;}});
  $('growth-diagnosis-domain')?.addEventListener('change',renderDiagnosis);
  $('maintenance-policy-form')?.addEventListener('input',()=>{policyDirty=true;});
  $('maintenance-policy-form')?.addEventListener('submit',async event=>{event.preventDefault();const button=event.currentTarget.querySelector('button[type="submit"]');button.disabled=true;try{await api('/api/growth/maintenance','PATCH',{enabled:$('maintenance-enabled').checked,maxPerCycle:Number($('maintenance-max').value),cooldownHours:Number($('maintenance-cooldown').value)});policyDirty=false;$('maintenance-policy-feedback').textContent='운영 설정을 저장했습니다.';await loadMaintenance();}catch(e){$('maintenance-policy-feedback').textContent=e.message;}finally{button.disabled=false;}});
  $('maintenance-refresh')?.addEventListener('click',loadMaintenance);$('btn-manual-refresh')?.addEventListener('click',loadMaintenance);loadMaintenance();setInterval(loadMaintenance,30000);
  $('growth-action-refresh')?.addEventListener('click',load);$('btn-manual-refresh')?.addEventListener('click',load);load();setInterval(load,60000);
  window.BaroLabGrowthActions = { getData: () => data, getMaintenance: () => maintenanceData, openDiagnosis, preparePlan };
})();
