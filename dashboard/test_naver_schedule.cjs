// Offline regression: node dashboard/test_naver_schedule.cjs
// Exercise the production adapter with explicit server snapshots and an injected clock.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const context = vm.createContext({URL, Date, console});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'naver_schedule.js'), 'utf8'), context);
const schedule = context.NaverSchedule;
const publicationDate = '2026-10-16';
const now = Date.parse('2026-10-16T06:15:00+09:00');
const stamp = (offset = 0) => new Date(now + offset).toISOString();
const attempt = (extra = {}) => ({account:'adinfo0905', publicationDate, scheduledSlot:'11:00',
  reserveTime:publicationDate+' 11:00', phase:'started', startedAt:'2026-10-15T23:50:08+09:00',
  updatedAt:'2026-10-15T23:50:08+09:00', topic:'Test reader question', ...extra});
const runner = (extra = {}) => ({running:true, observedAt:stamp(), activeAccount:'adinfo0905',
  activePublicationDate:publicationDate, activeScheduledSlot:'11:00', ...extra});
const recovery = (status = 'eligible', extra = {}) => ({schema:'naver-recovery-plan-v1',
  timezone:'Asia/Seoul', checkedAt:stamp(), items:[{account:'adinfo0905', accId:'acc4',
    publicationDate, scheduledSlot:'11:00', reserveTime:publicationDate+' 11:00', status,
    reason:'test reason', nextAction:'test next action'}], eligible:[], ...extra});
const resolve = ({ps = null, attempts = [attempt()], monitor = null, time = '11:00', accId = 'acc4'} = {}) =>
  schedule.resolve(ps, accId, publicationDate, {attempts}, monitor, now, null).find(item => item.time === time || schedule.slotMatches(accId, time, item.time));
let checks = 0;
function test(name, run) { run(); checks++; console.log('PASS '+name); }

test('old started is not live without a server observation', () => {
  const slot=resolve();
  assert.equal(slot.state,'wait');
  assert.equal(slot.label,'실행 확인 필요 · 예약 전');
  assert.equal(slot.info.topic,'Test reader question');
});
test('fresh stopped runner identifies interrupted preparation', () => {
  assert.equal(resolve({monitor:{runner:runner({running:false})}}).label,'작업 중단 · 복구 대기');
});
test('live runner requires exact account, date and slot', () => {
  assert.equal(resolve({monitor:{runner:runner()}}).state,'processing');
  for(const mismatch of [{activeAccount:'stone0747'}, {activePublicationDate:'2026-10-17'},
    {activeScheduledSlot:'19:00'}, {activeAccount:null}, {running:'true'}]) {
    assert.notEqual(resolve({monitor:{runner:runner(mismatch)}}).state,'processing');
  }
});
test('live evidence expires and rejects malformed or implausible future timestamps', () => {
  for(const observedAt of [stamp(-300001), stamp(60001), 'invalid', null]) {
    assert.notEqual(resolve({monitor:{runner:runner({observedAt})}}).state,'processing');
  }
  assert.equal(resolve({monitor:{runner:runner({observedAt:stamp(-300000)})}}).state,'processing');
});
test('two slots in one account do not share active execution', () => {
  const attempts=[attempt(),attempt({scheduledSlot:'19:00',reserveTime:publicationDate+' 19:00'})];
  const monitor={runner:runner()};
  assert.equal(resolve({attempts,monitor}).state,'processing');
  assert.notEqual(resolve({attempts,monitor,time:'19:00'}).state,'processing');
});
test('old processing pipeline state also needs live evidence', () => {
  const ps={accId:'acc4',publicationDate,scheduledSlot:'11:00',status:'processing',
    currentStage:3,updatedAt:'2026-10-16T06:00:00+09:00'};
  assert.equal(resolve({ps,attempts:[]}).label,'실행 확인 필요 · 예약 전');
  assert.equal(resolve({ps,attempts:[],monitor:{runner:runner()}}).state,'processing');
});
test('submitted work stays uncertain without a live runner', () => {
  for(const phase of ['submitted','submitting']) {
    const attempts=[attempt({phase})];
    assert.equal(resolve({attempts}).label,'예약 제출 · 결과 확인 필요');
    assert.equal(resolve({attempts,monitor:{runner:runner()}}).label,'예약 확인 중');
  }
  const ps={accId:'acc4',publicationDate,scheduledSlot:'11:00',status:'processing',currentStage:6};
  assert.equal(resolve({ps,attempts:[]}).label,'예약 제출 · 결과 확인 필요');
});
test('all recovery states are explicit and retain original failure detail', () => {
  const expected={verified:['wait','예약 근거 확인 필요'],unknown:['wait','예약 결과 확인 필요'],
    material_required:['wait','자료 확보 대기 · 예약 전'],retry_wait:['wait','재시도 대기 · 예약 전'],
    eligible:['wait','복구 대기 · 예약 전'],missed:['failed','발행 시각 경과 · 미예약'],
    deadline_close:['failed','예약 마감 임박 · 확인 필요'],waiting_preparation:['wait','작업 예정 · 예약 전'],
    retry_exhausted:['failed','재시도 한도 도달 · 확인 필요']};
  for(const [status,[state,label]] of Object.entries(expected)) {
    const slot=resolve({attempts:[attempt({phase:'failed',failureReason:'model timeout'})],
      monitor:{recovery:recovery(status)}});
    assert.equal(slot.state,state);assert.equal(slot.label,label);
    assert.equal(slot.info.failureReason,'model timeout');
    assert.equal(slot.recovery.reason,'test reason');
  }
});
test('stale or malformed recovery plans cannot overwrite the current failure', () => {
  for(const changes of [{checkedAt:stamp(-300001)},{checkedAt:stamp(60001)},
    {checkedAt:'invalid'},{schema:'wrong'},{timezone:'UTC'},{items:null}]) {
    const slot=resolve({attempts:[attempt({phase:'failed',preSubmissionFailure:true})],
      monitor:{recovery:recovery('eligible',changes)}});
    assert.equal(slot.state,'failed');assert.equal(slot.recovery,null);
  }
});

test('planning failure is distinct from missing materials and preserves retry limits', () => {
  const attempts=[attempt({phase:'failed',preSubmissionFailure:true,failureCategory:'planning_required'})];
  assert.equal(resolve({attempts}).label,'기획 보완 필요 · 예약 전');
  for(const status of ['eligible','retry_wait','retry_exhausted']) {
    const plan=recovery(status);plan.items[0].failureCategory='planning_required';
    const slot=resolve({attempts,monitor:{recovery:plan}});
    assert.equal(slot.label,status==='retry_exhausted' ? '기획 보완 필요 · 재시도 한도 도달' : '기획 보완 대기 · 예약 전');
    assert.equal(slot.info.failureCategory,'planning_required');
  }
  assert.equal(resolve({attempts,monitor:{recovery:recovery('material_required')}}).label,'자료 확보 대기 · 예약 전');
});

test('planning label does not hide unknown submission or another slot', () => {
  const attempts=[attempt({phase:'failed',failureCategory:'planning_required'})];
  assert.equal(resolve({attempts}).label,'기획 보완 필요 · 예약 미확인');
  assert.notEqual(resolve({attempts,time:'19:00'}).label,'기획 보완 필요 · 예약 미확인');
  const plan=recovery('unknown');plan.items[0].failureCategory='planning_required';
  assert.equal(resolve({attempts,monitor:{recovery:plan}}).label,'예약 결과 확인 필요');
});
test('recovery must match the account and complete slot identity', () => {
  for(const changes of [{account:'stone0747'},{accId:'acc5'},{publicationDate:'2026-10-17'},
    {scheduledSlot:'19:00'},{reserveTime:publicationDate+' 19:00'},{status:'toString'}]) {
    const plan=recovery();Object.assign(plan.items[0],changes);
    assert.equal(resolve({monitor:{recovery:plan}}).recovery,null);
  }
});
test('an attempt newer than the recovery snapshot wins', () => {
  const slot=resolve({attempts:[attempt({phase:'failed',updatedAt:stamp(-5000)})],
    monitor:{recovery:recovery('eligible',{checkedAt:stamp(-10000)})}});
  assert.equal(slot.state,'failed');assert.equal(slot.recovery,null);
});
test('live matching work wins over a recovery plan awaiting it', () => {
  const slot=resolve({monitor:{runner:runner(),recovery:recovery()}});
  assert.equal(slot.state,'processing');
});
test('a newer completed failure is not revived by a still-held runner lock', () => {
  const slot=resolve({attempts:[attempt({phase:'failed',updatedAt:stamp(-1000)})],
    monitor:{runner:runner()}});
  assert.equal(slot.state,'failed');
});
test('real reservation evidence wins over failures and recovery states', () => {
  const reserved=attempt({phase:'verified',verificationSource:'naver-reservation-list: exact title/time',
    verifiedAt:'2026-10-15T23:55:00+09:00',updatedAt:'2026-10-15T23:55:00+09:00'});
  const slot=resolve({attempts:[reserved,attempt({phase:'failed',updatedAt:stamp()})],
    monitor:{runner:runner(),recovery:recovery('missed')}});
  assert.equal(slot.state,'reserved');assert.equal(slot.label,'예약 완료 · 공개 예정');
  assert.equal(slot.info.verifiedAt,reserved.verifiedAt);
});
test('recovery verified alone is never reservation or public evidence', () => {
  const slot=resolve({attempts:[],monitor:{recovery:recovery('verified')}});
  assert.equal(slot.state,'wait');assert.equal(slot.label,'예약 근거 확인 필요');
});
test('verified public evidence keeps highest precedence', () => {
  const receipt={accId:'acc4',publicationDate,scheduledSlot:'11:00',reserveTime:publicationDate+' 11:00',
    topic:'Published reader answer',status:'done',publicPublicationVerified:true,
    publicUrl:'https://blog.naver.com/adinfo0905/123456789'};
  const ps={completedByDate:{[publicationDate]:{acc4:receipt}}};
  const slot=resolve({ps,monitor:{runner:runner(),recovery:recovery('missed')}});
  assert.equal(slot.state,'public');assert.equal(slot.info.publicUrl,receipt.publicUrl);
});
test('source snapshots remain unchanged', () => {
  const input={attempts:[attempt()],monitor:{runner:runner(),recovery:recovery()}};
  const before=JSON.stringify(input);resolve(input);
  assert.equal(JSON.stringify(input),before);
});
const runtime = (extra={}) => ({schema:'naver-active-workflow-v1',workerId:'worker-one',account:'adinfo0905',accId:'acc4',
  publicationDate,scheduledSlot:'11:00',reserveTime:publicationDate+' 11:00',startedAt:stamp(-10000),observedAt:stamp(),
  status:'running',pid:1234,...extra});
const runningJournal = (extra={}) => ({attempts:[attempt({workerId:'worker-one',startedAt:stamp(-9000),updatedAt:stamp(-9000),...extra})]});
test('initial live workflow correlates the exact latest attempt',()=>{
  const value=schedule.activeWorkflow(runtime(),runningJournal(),null,now);
  assert.equal(value.accId,'acc4');assert.equal(value.scheduledSlot,'11:00');
  const action=schedule.consumeStart(value,null,publicationDate);
  assert.equal(action.dateOffset,0);assert.equal(action.accId,'acc4');
  assert.equal(schedule.consumeStart(value,action,publicationDate),null);
});
test('runtime rejects stale future terminal malformed and mismatched identities',()=>{
  for(const extra of [{observedAt:stamp(-20001)},{observedAt:stamp(1001)},{status:'finished'},{status:'failed'},
    {pid:0},{pid:'1234'},{account:'stone0747'},{accId:'acc5'},{scheduledSlot:'19:00'},
    {reserveTime:publicationDate+' 19:00'},{workerId:'old'},{startedAt:stamp(1)}]) {
    assert.equal(schedule.activeWorkflow(runtime(extra),runningJournal(),{runner:runner()},now),null);
  }
  for(const phase of ['failed','verified','unknown'])
    assert.equal(schedule.activeWorkflow(runtime(),runningJournal({phase}),null,now),null);
});
test('new retry follows once but a late older start never steals selection',()=>{
  const first=schedule.activeWorkflow(runtime(),runningJournal(),null,now);
  const previous=schedule.consumeStart(first,null,publicationDate);
  const next={...first,workerId:'worker-two',eventKey:'worker-two|adinfo0905|2026-10-16|11:00',startedAt:stamp(-1000)};
  assert.ok(schedule.consumeStart(next,previous,publicationDate));
  assert.equal(schedule.consumeStart(first,schedule.consumeStart(next,previous,publicationDate),publicationDate),null);
  assert.equal(schedule.consumeStart({...next,publicationDate:'2026-10-17'},previous,publicationDate).dateOffset,1);
  assert.equal(schedule.consumeStart({...next,publicationDate:'2026-10-18'},previous,publicationDate),null);
});
test('legacy running child can be selected only from fresh exact monitor and journal',()=>{
  assert.equal(schedule.activeWorkflow(null,runningJournal(),{runner:runner()},now).legacy,true);
  assert.equal(schedule.activeWorkflow(null,runningJournal(),{runner:runner({observedAt:stamp(-10001)})},now),null);
  assert.equal(schedule.activeWorkflow(null,runningJournal({phase:'failed'}),{runner:runner()},now),null);
});
test('terminal runtime stops an old live monitor immediately and retains real failed stage',()=>{
  const work=runtime({status:'failed',progress:{workerId:'worker-one',currentStage:1,stageName:'keyword-selector',
    status:'failed',workDate:publicationDate,updatedAt:'06:15:00',detailMessage:'No eligible source'}});
  const journal=runningJournal({phase:'failed',updatedAt:stamp(),failureReason:'No eligible source'});
  const slot=schedule.resolve(null,'acc4',publicationDate,journal,{runner:runner()},now,null,work)[0];
  assert.equal(slot.state,'failed');assert.equal(slot.info.currentStage,1);assert.equal(slot.info.stageEvidence,true);
  assert.notEqual(schedule.resolve(null,'acc4',publicationDate,journal,{runner:runner()},now,null,work)[1].state,'processing');
  assert.equal(schedule.resolve(null,'acc4',publicationDate,journal,{runner:runner()},now,null,work)[1].info.currentStage,undefined);
});
test('late old journal update cannot replace a later retry or its progress',()=>{
  const newer=attempt({workerId:'worker-one',startedAt:stamp(-9000),updatedAt:stamp(-9000)});
  const older=attempt({workerId:'older',phase:'failed',startedAt:stamp(-60000),updatedAt:stamp()});
  const journal={attempts:[newer,older]};
  assert.equal(schedule.activeWorkflow(runtime(),journal,null,now).workerId,'worker-one');
  assert.equal(schedule.resolve(null,'acc4',publicationDate,journal,null,now,null,runtime())[0].info.workerId,'worker-one');
});
test('runtime never imports another worker stage into the selected attempt',()=>{
  const work=runtime({progress:{workerId:'another-worker',currentStage:6,status:'processing'}});
  const slot=schedule.resolve(null,'acc4',publicationDate,runningJournal(),null,now,null,work)[0];
  assert.equal(slot.info.currentStage,undefined);assert.notEqual(slot.info.stageEvidence,true);
});
test('production timeline keeps a failed keyword at stage one and later stages waiting',()=>{
  const html=fs.readFileSync(path.join(__dirname,'naver.html'),'utf8');
  const source=html.slice(html.indexOf('  function syncNaverPreparation()'),html.indexOf('  // Cross-tab and window sync'));
  const account={accId:'acc4',stages:[1,2,3,4,5,6].map(num=>({num}))};
  const ui=vm.createContext({NAVER_ACCOUNTS:[account],selectedNaverSlots:{},naverScheduleError:'',
    getNaverPublicationDate:()=>publicationDate,getNaverDay:()=>publicationDate,naverRelativeDate:()=> '오늘',
    naverSlotSummary:()=> '실패 · 예약 전',escapeNaverText:String,
    naverSlots:()=>[{time:'11:00',actualTime:'11:00',state:'failed',period:'오전분',label:'실패 · 예약 전',
      info:{currentStage:1,stageEvidence:true,failureReason:'No eligible source'}}]});
  vm.runInContext(source+'syncNaverPreparation();',ui);
  assert.equal(account.stages[0].status,'stopped');assert.ok(account.stages.slice(1).every(s=>s.status==='wait'));
  assert.equal(account.stages[0].detail,'No eligible source');
});
test('production UI follows start once and preserves subsequent manual selection',()=>{
  const html=fs.readFileSync(path.join(__dirname,'naver.html'),'utf8');
  const source=html.slice(html.indexOf('  function followStartedNaverWorkflow()'),html.indexOf('  function renderWorkflowTimeline()'));
  const elements=new Map();let scrolls=0;
  const ui=vm.createContext({NaverSchedule:schedule,requestAnimationFrame:fn=>fn(),document:{getElementById:id=>{
    if(!elements.has(id))elements.set(id,{classList:{toggle(){}},scrollIntoView(){scrolls++;}});return elements.get(id);}}});
  vm.runInContext(`let naverWorkflowSource=null,naverJournalSource=null,naverMonitorSource=null,naverFollowedStart=null;
    let selectedAccountIndex=0,selectedNaverDateOffset=0,currentGroupFilter='REAL';const selectedNaverSlots={};
    const NAVER_ACCOUNTS=[{accId:'acc1'},{accId:'acc4'},{accId:'acc5'}];const getNaverDay=()=> '${publicationDate}';`+source,ui);
  // Inject explicit candidate only for the pure clock boundary; execute the actual HTML selection function.
  ui.NaverSchedule={...schedule,activeWorkflow:()=>({accId:'acc4',scheduledSlot:'11:00',publicationDate,startedAt:stamp(-10000),eventKey:'one'})};
  assert.equal(vm.runInContext('followStartedNaverWorkflow()',ui),true);assert.equal(scrolls,1);
  assert.equal(vm.runInContext('selectedAccountIndex',ui),1);assert.equal(vm.runInContext("selectedNaverSlots.acc4",ui),'11:00');
  vm.runInContext('selectedAccountIndex=0;selectedNaverDateOffset=1;',ui);
  assert.equal(vm.runInContext('followStartedNaverWorkflow()',ui),false);assert.equal(scrolls,1);
  assert.equal(vm.runInContext('selectedAccountIndex',ui),0);assert.equal(vm.runInContext('selectedNaverDateOffset',ui),1);
  ui.NaverSchedule.activeWorkflow=()=>({accId:'acc5',scheduledSlot:'19:00',publicationDate,startedAt:stamp(-1000),eventKey:'two'});
  assert.equal(vm.runInContext('followStartedNaverWorkflow()',ui),true);assert.equal(scrolls,2);
  assert.equal(vm.runInContext('selectedAccountIndex',ui),2);assert.equal(vm.runInContext('selectedNaverDateOffset',ui),0);
  assert.match(html,/fetch\('\/api\/mission-control', \{cache:'no-store'/);
  assert.doesNotMatch(html,/fetch\('[^']*(?:active-workflow|automation-journal)\.json/);
});
test('same reservation revision keeps reserved count and displays exact live stage',()=>{
  const original=attempt({phase:'verified',workerId:'original',topic:'Old verified title',verificationSource:'actual list',startedAt:stamp(-60000),verifiedAt:stamp(-50000)});
  const current=attempt({runMode:'revision',workerId:'worker-one',startedAt:stamp(-9000),updatedAt:stamp(-5000)});
  const work=runtime({progress:{workerId:'worker-one',currentStage:3,status:'processing',workDate:publicationDate,updatedAt:'06:15:00',topic:'Revised draft'}});
  const slot=schedule.resolve(null,'acc4',publicationDate,{attempts:[original,current]},null,now,null,work)[0];
  assert.equal(slot.state,'reserved');assert.equal(slot.revisionPending,true);assert.equal(slot.revisionActive,true);
  assert.equal(slot.info.currentStage,3);assert.equal(slot.info.existingReservation.topic,'Old verified title');
  assert.equal(slot.label,'예약 유지 · 수정 작업 중');
  const stopped=schedule.resolve(null,'acc4',publicationDate,{attempts:[original,{...current,phase:'failed'}]},null,now,null,{...work,status:'failed'})[0];
  assert.equal(stopped.state,'reserved');assert.equal(stopped.revisionActive,false);assert.equal(stopped.revisionPending,true);
});

test('revision timeline never paints all six stages done from the old receipt',()=>{
  const html=fs.readFileSync(path.join(__dirname,'naver.html'),'utf8');
  const source=html.slice(html.indexOf('  function syncNaverPreparation()'),html.indexOf('  // Cross-tab and window sync'));
  const account={accId:'acc5',stages:[1,2,3,4,5,6].map(num=>({num}))};
  const ui=vm.createContext({NAVER_ACCOUNTS:[account],selectedNaverSlots:{},naverScheduleError:'',getNaverPublicationDate:()=>publicationDate,
    getNaverDay:()=>publicationDate,naverRelativeDate:()=> '오늘',naverSlotSummary:()=> '예약 유지',escapeNaverText:String,
    naverSlots:()=>[{time:'19:00',actualTime:'19:00',state:'reserved',revisionPending:true,revisionActive:true,
      period:'오후분',label:'예약 유지 · 수정 작업 중',info:{currentStage:3,stageEvidence:true,progressPct:42}}]});
  vm.runInContext(source+'syncNaverPreparation();',ui);
  assert.equal(account.status,'processing');assert.equal(account.stages[2].status,'active');
  assert.ok(account.stages.slice(3).every(s=>s.status==='wait'));
});
test('canonical schedule has seven daily slots and keeps historical reservation times',()=>{
  assert.deepEqual(JSON.parse(JSON.stringify(schedule.slots)), {
    acc1: ['11:00'],
    acc2: ['20:00'],
    acc3: ['20:30'],
    acc4: ['11:00', '19:00'],
    acc5: ['11:00', '19:00']
  });
  const tomorrow = schedule.nextDay(publicationDate);
  const journal = {
    attempts: [
      attempt({account:'soultin', publicationDate, scheduledSlot:'19:30', reserveTime:publicationDate+' 19:30',
        phase:'verified', verificationSource:'naver-reservation-list: exact title/time', verifiedAt:'2026-10-16T13:52:00+09:00',
        topic:'국민연금 분할연금 조건'}),
      attempt({account:'adinfo0905', workDate:publicationDate, publicationDate:tomorrow, scheduledSlot:'11:00',
        reserveTime:tomorrow+' 11:00', phase:'verified', verificationSource:'naver-reservation-list: exact title/time',
        verifiedAt:'2026-10-16T21:53:00+09:00', topic:'근로소득공제와 근로소득 세액공제 차이'})
    ]
  };
  const unified = schedule.resolveUnifiedToday(null, publicationDate, journal, null, now, null, null);
  assert.equal(unified.length, 7);
  const soultinEve = unified.find(r => r.accId === 'acc1' && r.time === '11:00');
  assert.equal(soultinEve.state, 'reserved');
  assert.match(soultinEve.scheduleTransition, /예약등록 13:52 ➔ 공개 19:30/);
  const adinfoRollover = unified.find(r => r.accId === 'acc4' && r.time === '11:00');
  assert.equal(adinfoRollover.state, 'wait');
  assert.equal(adinfoRollover.isRollover, false);
  const tomorrowSlot=schedule.resolve(null,'acc4',tomorrow,journal,null,now,null).find(r=>r.time==='11:00');
  assert.equal(tomorrowSlot.state,'reserved');
  assert.equal(tomorrowSlot.publicationDate,tomorrow);
  assert.match(tomorrowSlot.scheduleTransition,/예약등록 21:53 ➔ 공개 11:00/);
});
console.log(`${checks} Naver schedule regressions passed`);
