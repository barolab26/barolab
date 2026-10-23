/* Publication slots are server evidence, never browser-local quota counters. */
(function (root) {
  const slots = {
    acc1: ['11:00'],
    acc2: ['20:00'],
    acc3: ['20:30'],
    acc4: ['11:00', '19:00'],
    acc5: ['11:00', '19:00']
  };
  const legacySingleSlots = {acc1:['19:30','11:30','08:00','10:00','11:00'], acc2:['20:00','12:00','08:30','12:30'], acc3:['20:30','12:30','09:00','14:00']};
  const legacySlotMap = {
    acc1: { '11:00': ['11:00','19:30','11:30','08:00','10:00'], '19:30': ['19:30', '11:30', '08:00', '10:00', '11:00'] },
    acc2: { '20:00': ['20:00', '12:00', '08:30', '12:30'] },
    acc3: { '20:30': ['20:30', '12:30', '09:00', '14:00'] },
    acc4: { '11:00': ['11:00', '12:30', '15:30'], '19:00': ['19:00', '18:30', '19:30'] },
    acc5: { '11:00': ['11:00', '11:15', '14:30', '16:30'], '19:00': ['19:00', '20:30'] }
  };
  const slotMatches = (accId, candidateSlot, targetSlot) => {
    if (!candidateSlot || !targetSlot) return false;
    if (candidateSlot === targetSlot) return true;
    const mapped = legacySlotMap[accId]?.[targetSlot];
    if (mapped && mapped.includes(candidateSlot)) return true;
    if ((slots[accId] || []).length === 1 && (legacySingleSlots[accId] || []).includes(candidateSlot)) return true;
    return false;
  };
  const slotMeta = {
    acc1: {
      '19:30': { prepTime: '08:30', track: '카테고리 전문성·체류 트랙', desc: '5060 연금·복지 심층 간접체험 가이드 (일 1포 집중)' }
    },
    acc2: {
      '20:00': { prepTime: '09:00', track: '카테고리 전문성·체류 트랙', desc: '5060 건기식·혈압혈당 심층 간접체험 가이드 (일 1포 집중)' }
    },
    acc3: {
      '20:30': { prepTime: '09:30', track: '트렌드·롱테일 유입 트랙', desc: '5060 데일리룩·리빙 심층 간접체험 가이드 (일 1포 집중)' }
    },
    acc4: {
      '11:00': { prepTime: '08:00', track: 'CF 고단가 브리지 1차', desc: '지원금·금융·세무 핵심 요약 + CF 상세표 브리지' },
      '19:00': { prepTime: '13:00', track: 'CF 고단가 브리지 2차', desc: '연말정산·IT·실무서식 핵심 요약 + CF 계산기 브리지' }
    },
    acc5: {
      '11:00': { prepTime: '08:15', track: 'CF 고단가 브리지 1차', desc: '소상공인·지자체 정책자금 요약 + CF 자격표 브리지' },
      '19:00': { prepTime: '13:30', track: 'CF 고단가 브리지 2차', desc: '마감속보·생활세무·핫플 요약 + CF 상세가이드 브리지' }
    }
  };
  const names = {acc1:'soultin', acc2:'soul5373', acc3:'yoon_master', acc4:'adinfo0905', acc5:'stone0747'};
  const blogs = {acc1:'mustpickinfo',acc2:'mustinfo',acc3:'yoonviews',acc4:'adinfo0905',acc5:'stone0747'};
  let publicEvidence=null, evidencePending=null, evidenceFetched=0;
  async function loadPublicEvidence(force = false) {
    if(evidencePending)return evidencePending;
    if(!force && Date.now()-evidenceFetched<30000 && publicEvidence)return publicEvidence;
    evidencePending=(async()=>{
      try {
        const response=await fetch('./naver_public_verification.json?t='+Date.now(),{cache:'no-store',signal:AbortSignal.timeout(12000)});
        if(!response.ok)throw Error('Public evidence unavailable');const value=await response.json();
        if(value.schema!=='naver-public-verification-v1' || !Array.isArray(value.evidence))throw Error('Invalid public evidence');
        publicEvidence=value;
      } catch(error) { console.warn('[NaverSchedule] Public evidence refresh unavailable'); }
      evidenceFetched=Date.now();return publicEvidence;
    })();
    try{return await evidencePending;}finally{evidencePending=null;}
  }
  const day = value => /^\d{4}-\d{2}-\d{2}/.test(value || '') ? value.slice(0,10) : null;
  const publicationDay = item => day(item?.publicationDate) || day(item?.reserveTime) || day(item?.date);
  const kstDay = stamp => Number.isFinite(Date.parse(stamp || '')) ? new Date(Date.parse(stamp)+9*3600000).toISOString().slice(0,10) : null;
  const kstTime = stamp => Number.isFinite(Date.parse(stamp || '')) ? new Date(Date.parse(stamp)+9*3600000).toISOString().slice(11,16) : null;
  const nextDay = today => new Date(Date.parse(today+'T00:00:00Z')+86400000).toISOString().slice(0,10);
  const viewDate = (today, offset = 0) => offset === 1 ? nextDay(today) : today;
  function publicKey(value) {
    try { const u=new URL(value);if(u.protocol!=='https:' || !['blog.naver.com','m.blog.naver.com'].includes(u.hostname) || u.username || u.password)return null;
      const path=u.pathname.match(/^\/([A-Za-z0-9_-]+)\/(\d+)\/?$/);
      const blog=path?.[1] || u.searchParams.get('blogId'), post=path?.[2] || u.searchParams.get('logNo');
      return blog && /^\d+$/.test(post || '') ? blog.toLowerCase()+'/'+post : null;
    } catch { return null; }
  }
  const publicVerified = item => item?.status==='done' && item.publicPublicationVerified===true && !!publicKey(item.publicUrl);
  const reserved = item => !!item?.topic && !!item?.reserveTime && !!(item.reservationVerificationSource || /naver-reservation-list/i.test(item.verificationSource || '') || (item.phase === 'verified' && item.verificationSource));
  const freshSnapshot = (stamp, now) => {
    const age = now - Date.parse(stamp || '');
    return Number.isFinite(age) && age >= -60000 && age <= 300000;
  };
  const attemptTime = item => Date.parse(item?.startedAt || '');
  function latestAttempt(journal, account, date, slot) {
    const accId = Object.keys(names).find(k => names[k] === account);
    const allForDay = (journal?.attempts || []).filter(a => a.account === account && publicationDay(a) === date);
    const exact = allForDay.filter(a => (a.scheduledSlot || a.reserveTime?.slice(-5)) === slot);
    const pool = exact.length > 0 ? exact : allForDay.filter(a => slotMatches(accId, a.scheduledSlot || a.reserveTime?.slice(-5), slot));
    return pool.reduce((a,b) => !a || attemptTime(b) > attemptTime(a) || (attemptTime(b) === attemptTime(a)
        && Date.parse(b.updatedAt || b.startedAt) >= Date.parse(a.updatedAt || a.startedAt)) ? b : a, null);
  }
  function workflowSnapshot(runtime, journal) {
    const allKnownSlots = [
      ...(slots[runtime?.accId] || []),
      ...(legacySingleSlots[runtime?.accId] || []),
      ...Object.values(legacySlotMap[runtime?.accId] || {}).flat()
    ];
    if (runtime?.schema !== 'naver-active-workflow-v1' || names[runtime.accId] !== runtime.account
      || !allKnownSlots.includes(runtime.scheduledSlot) || !/^\d{4}-\d{2}-\d{2}$/.test(runtime.publicationDate || '')
      || runtime.reserveTime !== runtime.publicationDate + ' ' + runtime.scheduledSlot || !runtime.workerId
      || !['running','finished','failed'].includes(runtime.status)) return null;
    const latest = (journal?.attempts || []).filter(a => a.account === runtime.account && publicationDay(a) === runtime.publicationDate
      && (a.scheduledSlot || a.reserveTime?.slice(-5)) === runtime.scheduledSlot)
      .reduce((a,b) => !a || attemptTime(b) > attemptTime(a) || (attemptTime(b) === attemptTime(a)
        && Date.parse(b.updatedAt || b.startedAt) >= Date.parse(a.updatedAt || a.startedAt)) ? b : a, null);
    if (!latest || latest.workerId !== runtime.workerId || !Number.isFinite(attemptTime(latest))) return null;
    const started = Date.parse(runtime.startedAt), observed = Date.parse(runtime.observedAt);
    if (!Number.isFinite(started) || !Number.isFinite(observed) || started > observed || attemptTime(latest) < started-1000) return null;
    return {...runtime, attempt:latest, eventKey:[runtime.workerId,runtime.account,runtime.publicationDate,runtime.scheduledSlot].join('|')};
  }
  function activeWorkflow(runtime, journal, monitor, now = Date.now()) {
    const value = workflowSnapshot(runtime, journal);
    if (runtime != null) {
      if (!value || value.status !== 'running' || !Number.isInteger(value.pid) || value.pid <= 0
        || now-Date.parse(value.observedAt) < -1000 || now-Date.parse(value.observedAt) > 20000
        || !['started','generated','submitting','submitted'].includes(value.attempt.phase)) return null;
      return value;
    }
    const runner = monitor?.runner;
    const accId = Object.keys(names).find(id => names[id] === runner?.activeAccount);
    const validSlots = [
      ...(slots[accId] || []),
      ...(legacySingleSlots[accId] || []),
      ...Object.values(legacySlotMap[accId] || {}).flat()
    ];
    if (!accId || runner.running !== true || now-Date.parse(runner.observedAt || '') < -1000 || now-Date.parse(runner.observedAt) > 120000
      || !validSlots.includes(runner.activeScheduledSlot)) return null;
    const attempt = (journal?.attempts || []).filter(a => a.account === runner.activeAccount && publicationDay(a) === runner.activePublicationDate
      && (a.scheduledSlot || a.reserveTime?.slice(-5)) === runner.activeScheduledSlot)
      .reduce((a,b) => !a || attemptTime(b) > attemptTime(a) || (attemptTime(b) === attemptTime(a)
        && Date.parse(b.updatedAt || b.startedAt) >= Date.parse(a.updatedAt || a.startedAt)) ? b : a, null);
    if (!attempt || !attempt.workerId || !['started','generated','submitting','submitted'].includes(attempt.phase)
      || !Number.isFinite(attemptTime(attempt)) || Date.parse(runner.observedAt) < attemptTime(attempt)) return null;
    return {workerId:attempt.workerId,account:runner.activeAccount,accId,publicationDate:runner.activePublicationDate,
      scheduledSlot:runner.activeScheduledSlot,startedAt:attempt.startedAt,observedAt:runner.observedAt,
      eventKey:[attempt.workerId,runner.activeAccount,runner.activePublicationDate,runner.activeScheduledSlot].join('|'),legacy:true};
  }
  function consumeStart(candidate, previous, today) {
    if (!candidate || candidate.eventKey === previous?.eventKey
      || (previous && Date.parse(candidate.startedAt) <= Date.parse(previous.startedAt))) return null;
    const dateOffset = candidate.publicationDate === today ? 0 : candidate.publicationDate === nextDay(today) ? 1 : -1;
    return dateOffset < 0 ? null : {eventKey:candidate.eventKey,startedAt:candidate.startedAt,
      accId:candidate.accId,scheduledSlot:candidate.scheduledSlot,dateOffset};
  }
  function workflowMonitor(runtime, journal, monitor, now = Date.now()) {
    const active = activeWorkflow(runtime,journal,monitor,now);
    if (runtime == null) return monitor;
    return {...monitor,runner:{running:!!active,observedAt:runtime.observedAt,
      activeAccount:active?.account,activePublicationDate:active?.publicationDate,activeScheduledSlot:active?.scheduledSlot}};
  }
  const recoveryStates = {
    verified:['wait','예약 근거 확인 필요'], unknown:['wait','예약 결과 확인 필요'],
    material_required:['wait','자료 확보 대기 · 예약 전'], retry_wait:['wait','재시도 대기 · 예약 전'],
    eligible:['wait','복구 대기 · 예약 전'], missed:['failed','발행 시각 경과 · 미예약'],
    deadline_close:['failed','예약 마감 임박 · 확인 필요'], waiting_preparation:['wait','작업 예정 · 예약 전'],
    retry_exhausted:['failed','재시도 한도 도달 · 확인 필요']
  };
  function resolve(ps, accId, publicationDate, journal, monitor, now = Date.now(), ledger = publicEvidence, runtime = null) {
    monitor = workflowMonitor(runtime,journal,monitor,now);
    const records = [ps?.completedByDate?.[publicationDate]?.[accId], ps?.completedAccounts?.[accId], ps?.accId === accId ? ps : null]
      .filter(item => item && (!item.accId || item.accId === accId) && publicationDay(item) === publicationDate);
    const attempts = (journal?.attempts || []).filter(item => (item.account === names[accId] || item.accId === accId) && publicationDay(item) === publicationDate);
    const approved = monitor?.schedulePolicy;
    const times = approved && publicationDate >= approved.effectiveDate ? approved.naver?.[names[accId]]?.slots : null;
    return (times || slots[accId] || []).map(time => {
      let receipt = null;
      for (const record of records) {
        let child = record.completedSlots?.[time];
        if (!child && record.completedSlots) {
          const fallbackKey = Object.keys(record.completedSlots).find(k => slotMatches(accId, k, time));
          if (fallbackKey) child = record.completedSlots[fallbackKey];
        }
        if (child && publicationDay(child) === publicationDate) {
          const same = child.reserveTime === record.reserveTime && child.topic === record.topic;
          const candidate = {...child, status:child.status || record.status};
          if (same && !publicVerified(candidate)) Object.assign(candidate, {verifiedAt:record.verifiedAt || child.verifiedAt, reservedAt:record.reservedAt || child.reservedAt, publicPublicationVerified:record.publicPublicationVerified ?? child.publicPublicationVerified, publicationStatus:record.publicationStatus || child.publicationStatus, state:record.state || child.state, publicUrl:record.publicUrl || child.publicUrl});
          if (!publicVerified(receipt) || publicVerified(candidate)) receipt=candidate;
        } else if (slotMatches(accId, record.scheduledSlot || record.reserveTime?.slice(-5), time) && record.status === 'done' && !publicVerified(receipt)) {
          receipt = record;
        }
      }
      const exactRelevant = attempts.filter(item => (item.scheduledSlot || item.reserveTime?.slice(-5)) === time);
      const relevant = exactRelevant.length > 0 ? exactRelevant : attempts.filter(item => slotMatches(accId, item.scheduledSlot || item.reserveTime?.slice(-5), time));
      const latest = latestAttempt(journal,names[accId],publicationDate,time);
      const verified = relevant.filter(item => item.phase === 'verified' && reserved(item)).pop();
      if (verified && !publicVerified(receipt)) receipt = {...receipt, ...verified};
      if(ledger?.schema==='naver-public-verification-v1' && Array.isArray(ledger.evidence)) {
        const normalize=value=>typeof value==='string'?value.normalize('NFC').trim().replace(/\s+/g,' '):'';
        const normAlnum=value=>normalize(value).replace(/[^0-9A-Za-z가-힣]+/g,'').toLowerCase();
        const titleEq=(a,b)=>{
          const na=normalize(a), nb=normalize(b);
          if(!na || !nb)return false;
          if(na===nb)return true;
          const ca=normAlnum(na), cb=normAlnum(nb);
          return !!ca && (ca===cb || (ca.length>=10 && cb.length>=10 && (ca.includes(cb) || cb.includes(ca))));
        };
        const proofs=ledger.evidence.filter(row=>{
          const key=publicKey(row.publicUrl);
          if (!(row.verified===true && row.publicPublicationVerified===true && !!key
            && row.account===names[accId] && row.blogId===blogs[accId] && key.split('/')[0]===blogs[accId]
            && (!row.publicationDate || row.publicationDate===publicationDate))) return false;
          if (receipt?.topic) return titleEq(row.title, receipt.topic);
          return (row.reserveTime || '').slice(-5) === time || slotMatches(accId, (row.reserveTime || '').slice(-5), time);
        });
        const proof=proofs.length>=1 ? proofs[proofs.length-1] : null;
        if(proof)receipt={...(receipt || {}),topic:receipt?.topic || proof.title,reserveTime:receipt?.reserveTime || proof.reserveTime || (publicationDate+' '+time),
          status:'done',publicPublicationVerified:true,publicationStatus:'verified_public',state:'verified_public',publicUrl:proof.publicUrl,publishedAt:proof.publishedAt,
          publicVerifiedAt:proof.checkedAt || null,publicVerificationReportedAt:proof.reportReceivedAt || ledger.reportReceivedAt || null,
          publicVerificationSource:proof.verificationSource,publicBodyMatched:true,bodyParagraphsMatch:true,matchedParagraphs:proof.matchedParagraphs || 10,
          substantiveParagraphs:proof.substantiveParagraphs || 10,publicBodySha256:proof.publicBodySha256 || null,tagsVerified:proof.tagsVerified===true};
      }
      const runtimeState = workflowSnapshot(runtime,journal);
      const runtimeInfo = runtimeState?.accId === accId && runtimeState.publicationDate === publicationDate
        && slotMatches(accId, runtimeState.scheduledSlot, time) && runtimeState.progress?.workerId === runtimeState.workerId ? runtimeState.progress : null;
      const active = runtimeInfo || records.find(item => item === ps && (!item.scheduledSlot ? slots[accId].length === 1 : slotMatches(accId, item.scheduledSlot, time))
        && (!latest?.workerId || item.workerId === latest.workerId || (!item.workerId && Date.parse((item.workDate || publicationDate)+'T'+item.updatedAt+'+09:00') >= attemptTime(latest))));
      const monitored = monitor?.publicationDate === publicationDate ? monitor.accounts?.find(item => item.accId === accId)?.slots?.find(item => slotMatches(accId, item.scheduledSlot, time) && item.publicationDate === publicationDate) : null;
      const activeStamp = active?.updatedAt?.includes('T') ? active.updatedAt : (active?.workDate || publicationDate)+'T'+(active?.updatedAt || '00:00:00')+'+09:00';
      const newerAttempt = latest && (!active || Date.parse(latest.updatedAt || latest.startedAt) >= Date.parse(activeStamp));
      const runner = monitor?.runner;
      const runnerFresh = freshSnapshot(runner?.observedAt, now);
      const live = (runnerFresh && runner.running === true && runner.activeAccount === names[accId]
        && runner.activePublicationDate === publicationDate && slotMatches(accId, runner.activeScheduledSlot, time))
        || (!!runtimeInfo && !!activeWorkflow(runtime,journal,monitor,now));
      const recoveryPlan = monitor?.recovery;
      const recoveryStamp = Date.parse(recoveryPlan?.checkedAt || '');
      const latestStamp = Date.parse(latest?.updatedAt || latest?.startedAt || '');
      const recovery = recoveryPlan?.schema === 'naver-recovery-plan-v1' && recoveryPlan.timezone === 'Asia/Seoul'
        && freshSnapshot(recoveryPlan.checkedAt, now) && (!Number.isFinite(latestStamp) || recoveryStamp >= latestStamp)
        && Array.isArray(recoveryPlan.items) ? recoveryPlan.items.find(item => item.account === names[accId]
          && item.accId === accId && item.publicationDate === publicationDate && slotMatches(accId, item.scheduledSlot, time)
          && item.reserveTime === publicationDate + ' ' + item.scheduledSlot
          && Object.hasOwn(recoveryStates, item.status)) || null : null;
      const inProgress = newerAttempt && ['started','generated','submitted','submitting'].includes(latest.phase);
      const submitting = newerAttempt ? ['submitted','submitting'].includes(latest.phase) : Number(active?.currentStage) >= 6;
      let state = 'wait', label = '예약 미확인', info = {...active, ...latest};
      if (active && latest?.workerId && active.workerId === latest.workerId) info.stageEvidence = true;
      const folderSlug = info?.artifactFolder
        ? String(info.artifactFolder).split(/[\\/]/).pop().replace(/-\d{8}-[0-9a-f]{6,}$/i, '').replace(/-/g, ' ').trim()
        : null;
      const fallbackTopic = active?.topic || receipt?.topic || receipt?.title
        || [...relevant].reverse().find(item => item.topic || item.title)?.topic
        || (ps?.accId === accId && ps?.publicationDate === publicationDate && slotMatches(accId, ps?.scheduledSlot, time) ? ps.topic : null)
        || (folderSlug ? `${folderSlug} (실시간 원고 집필·검수 진행 중)` : null);
      if (publicVerified(receipt)) { state='public'; label='공개 확인'; info={...info, ...receipt}; }
      else if (reserved(receipt) && latest?.runMode === 'revision' && latest.phase !== 'verified') {
        state='reserved';
        label=live ? '예약 유지 · 수정 작업 중' : ['submitting','unknown'].includes(latest.phase) ? '예약 수정 결과 확인 필요' : '예약 유지 · 수정 보완 대기';
        info.existingReservation=receipt;
      }
      else if (reserved(receipt)) { state='reserved'; label=Date.parse(receipt.reserveTime.replace(' ','T')+':00+09:00') > now ? '예약 완료 · 공개 예정' : '예약 확인 · 공개 대기'; info={...info, ...receipt}; }
      else if (live && (inProgress || (!newerAttempt && active?.status === 'processing'))) { state='processing'; label=submitting ? '예약 확인 중' : '초안 작업 중 · 예약 전'; }
      else if (recovery) {
        [state,label]=recoveryStates[recovery.status];
        if (recovery.failureCategory === 'planning_required' && ['eligible','retry_wait','retry_exhausted'].includes(recovery.status)) {
          label = recovery.status === 'retry_exhausted' ? '기획 보완 필요 · 재시도 한도 도달' : '기획 보완 대기 · 예약 전';
        }
      }
      else if (newerAttempt && latest.phase === 'failed') {
        state='failed';
        const failure = latest.failureCategory === 'planning_required' ? '기획 보완 필요' : '실패';
        label=failure+(latest.preSubmissionFailure === true ? ' · 예약 전' : ' · 예약 미확인');
      }
      else if (inProgress || active?.status === 'processing') { label=submitting ? '예약 제출 · 결과 확인 필요' : runnerFresh && runner.running === false ? '작업 중단 · 복구 대기' : '실행 확인 필요 · 예약 전'; }
      else if (['failed','error'].includes(active?.status)) { state='failed'; label='실패 · 예약 미확인'; }
      else if (monitored) { label=({waiting:'작업 예정 · 예약 전', blocked:'앞 계정 대기 · 예약 전', overdue:'작업 미시작 · 예약 전', retry_wait:'재시도 대기 · 예약 전', failed:'실패 · 예약 미확인', unknown:'결과 미확인', verified:'감시 완료 · 예약 근거 미확인'})[monitored.status] || '예약 미확인'; }
      if (!info.topic && fallbackTopic) info.topic = fallbackTopic;
      const revisionPending = !!info.existingReservation;
      const actionStamp = info.reservedAt || info.verifiedAt || info.existingReservation?.verifiedAt || (info.phase === 'verified' ? info.updatedAt : null) || info.startedAt;
      const actionDay = kstDay(actionStamp) || info.workDate || null;
      const reservedAtKst = kstTime(actionStamp) || (typeof info.updatedAt === 'string' && /^\d{2}:\d{2}/.test(info.updatedAt) ? info.updatedAt.slice(0,5) : null);
      const actualTime = (['public', 'reserved'].includes(state) && info.reserveTime?.slice(-5)) ? info.reserveTime.slice(-5) : time;
      const metaCfg = slotMeta[accId]?.[time] || { prepTime: '08:30', track: '정규 트랙', desc: '' };
      const scheduleTransition = state === 'public'
        ? `예약등록 ${reservedAtKst || metaCfg.prepTime} ➔ 공개 ${actualTime}`
        : state === 'reserved'
          ? `예약등록 ${reservedAtKst || metaCfg.prepTime} ➔ 공개 ${actualTime}`
          : state === 'processing'
            ? `실시간집필 ${reservedAtKst || '진행중'} ➔ 공개 ${actualTime} 예정`
            : `당일집필 ${metaCfg.prepTime} ➔ 공개 ${actualTime} 예정`;
      return {time, publicationDate, state, label, info, recovery, actionDay, reservedAtKst, scheduleTransition,
        track: metaCfg.track, trackDesc: metaCfg.desc, prepTime: metaCfg.prepTime,
        revisionPending, revisionActive:revisionPending && live,
        actualTime, period:Number(time.slice(0,2)) < 13 ? '오전분' : '오후분'};
    });
  }
  function resolveUnifiedToday(ps, today, journal, monitor, now = Date.now(), ledger = publicEvidence, runtime = null) {
    // Strictly return ONLY the 7 slots for 'today' (never mix tomorrow rollover rows into Today tab!)
    const out = [];
    for (const accId of Object.keys(slots)) {
      const todaySlots = resolve(ps, accId, today, journal, monitor, now, ledger, runtime);
      todaySlots.forEach(tSlot => {
        out.push({ ...tSlot, accId, account: names[accId], blogId: blogs[accId], isRollover: false });
      });
    }
    return out;
  }
  function publications(ps,date,ledger=publicEvidence,journal=null) {
    const seen=new Set(), items=[];
    for(const accId of Object.keys(slots))for(const slot of resolve(ps,accId,date,journal,null,Date.now(),ledger)) {
      if(slot.state!=='public')continue;const key=publicKey(slot.info.publicUrl);if(seen.has(key))continue;seen.add(key);
      const record=ps?.completedByDate?.[date]?.[accId] || {};
      items.push({...slot.info,accId,accountNo:Number(accId.slice(3)),name:record.blogId || names[accId],siteTitle:record.account || '',schedule:date+' '+slot.time,displayStatus:'공개 확인',scheduledSlot:slot.time,publicationDate:date,id:accId+'_'+slot.time,url:slot.info.publicUrl,title:slot.info.topic,source:'server-public-verification'});
    }
    return items;
  }
  root.NaverSchedule = {slots, slotMeta, slotMatches, resolve, resolveUnifiedToday, publications, loadPublicEvidence, publicKey, nextDay, viewDate, publicationDay, publicVerified,
    activeWorkflow,consumeStart,workflowMonitor,workflowSnapshot};
})(typeof window === 'undefined' ? globalThis : window);
