/* Regression: browser-relative labels must use the current Korean calendar day.
 * Run: node server/test_dashboard_dates.js
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() { this.children=[];this.style={};this.dataset={};this.listeners={};this.value='';this._text=''; }
  set textContent(value) { this._text=String(value);this.children=[]; }
  get textContent() { return this._text+this.children.map(child=>child.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child);return child; }
  replaceChildren(...children) { this._text='';this.children=[...children]; }
  addEventListener(name,fn) { this.listeners[name]=fn; }
  setAttribute() {}
  after() {}
}

function fixture(day='2026-10-15',value=47) {
  const earlier=n=>new Date(Date.parse(day+'T00:00:00Z')-n*86400000).toISOString().slice(0,10);
  const report=(start,end,users)=>({start,end,users,amounts:{USD:String(users)},status:'partial'});
  const periods={today:report(day,day,value),day:report(earlier(1),earlier(1),12),week:report(earlier(7),earlier(1),70),month:report(earlier(30),earlier(1),300)};
  const totals={today:report(day,day,value),yesterday:report(earlier(1),earlier(1),12),throughYesterday:report(day.slice(0,7)+'-01',earlier(1),42),month:report(day.slice(0,7)+'-01',day,89)};
  const source={label:'Partial account',scope:'CF only',status:'collected',complete:false,checkedAt:day+'T13:00:00Z',daily:{[day]:String(value)},periods:totals};
  return {checkedAt:day+'T13:00:00Z',collectionObservability:{},sites:[],trafficAnalysis:{today:day,checkedAt:day+'T13:00:00Z',naverCheckedAt:day+'T13:00:00Z',expectedDomains:16,expectedNaverBlogs:5,
    sites:[{site:{site_id:'test.example'},ga4:{status:'collected',stale:false,timezone:'Asia/Seoul',periods}}],
    naverBlogs:[{site:{site_id:'naver:test',url:'https://blog.naver.com/test'},status:'collected',stale:false,timezone:'Asia/Seoul',date:day,days:Object.fromEntries(Array.from({length:5},(_,i)=>[earlier(i),i ? 12 : value]))}]},
    revenue:{today:day,yesterday:earlier(1),month:day.slice(0,7),status:'partial',checkedAt:day+'T13:00:00Z',totals,categories:[{id:'ads',label:'AdSense',sources:[source],periods:totals}],daily:[{date:day,categories:{ads:totals.today}}]}};
}

async function harness(payload,now,platform='naver',healthFallback=null) {
  let clock=Date.parse(now),fail=false;
  const ids=['summary-visitors-value','summary-visitors-coverage','summary-visitors-updated','summary-stat-day','summary-stat-recent','summary-stat-week','summary-stat-month','metrics-refresh-status','metric-revenue-value','metric-revenue-badge','metric-traffic-summary','revenue-period','revenue-overview','revenue-sources','revenue-daily','rank-overview','rank-highlights','overview-today-cf','overview-today-naver','overview-visitors-coverage','growth-naver-counters','collection-health'];
  const elements=Object.fromEntries(ids.map(id=>[id,new Element()])),listeners={},intervals=[];
  const NativeDate=Date;
  class FakeDate extends NativeDate { constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;} }
  const document={body:{dataset:{summaryPlatform:platform}},getElementById:id=>elements[id]||null,createElement:()=>new Element(),querySelectorAll:()=>[],addEventListener:(event,fn)=>{listeners[event]=fn;}};
  const window={addEventListener:(event,fn)=>{listeners[event]=fn;}};
  const context=vm.createContext({document,window,Date:FakeDate,Intl,URLSearchParams,location:{search:'',hash:''},console,setInterval:(fn,ms)=>intervals.push({fn,ms}),fetch:async(url)=>{if(fail)throw Error('offline');return {ok:true,json:async()=>url==='/data/collection-health.json'?healthFallback:payload};}});
  for(const file of ['traffic.js','metrics.js']) vm.runInContext(fs.readFileSync(path.join(__dirname,'../dashboard',file),'utf8'),context,{filename:file});
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  await settle();await settle();
  assert.doesNotMatch(elements['metrics-refresh-status'].textContent,/조회 실패/,'the harness must finish the real render path');
  return {elements,window,listeners,intervals,settle,setTime:value=>{clock=Date.parse(value);},failFetch:()=>{fail=true;}};
}

async function historyRollover() {
  let clock=Date.parse('2026-10-15T14:59:59Z'),writes=0,fetches=0;
  const previous={date:'2026-10-15',cf:{target:16,completed:13,items:[{url:'https://test.example/verified'}],sourceStatus:'current'},naver:{target:7,completed:7,items:[],sourceStatus:'current'}};
  const saved=new Map([['BAROLAB_TODAY_DATE','2026-10-15'],['BAROLAB_POSTING_HISTORY_V1',JSON.stringify({'2026-10-15':previous})],['naver_quota_2026-10-11','{"_patchOct11Acc4V2":true}']]);
  const localStorage={getItem:key=>saved.get(key)??null,setItem:(key,value)=>{writes++;saved.set(key,String(value));},removeItem:key=>saved.delete(key)};
  const intervals=[],listeners={},events=[];
  const NativeDate=Date;
  class FakeDate extends NativeDate {constructor(...args){super(...(args.length?args:[clock]));}static now(){return clock;}}
  const window={addEventListener:(event,fn)=>{listeners[event]=fn;},dispatchEvent:event=>{events.push({type:event.type,stats:window.BaroLabHistory.getTodayStats()});}};
  const context=vm.createContext({window,localStorage,Date:FakeDate,Event:class{constructor(type){this.type=type;}},document:{addEventListener:(event,fn)=>{listeners[event]=fn;}},console:{log(){},warn(){},error(){}},setInterval:(fn,ms)=>intervals.push({fn,ms}),fetch:async()=>{fetches++;throw Error('offline');}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../dashboard/history_manager.js'),'utf8'),context);
  await new Promise(resolve=>setImmediate(resolve));
  const previousBefore=JSON.stringify(window.BaroLabHistory.loadHistoryStore()['2026-10-15']);
  const fetchesBefore=fetches,eventCount=events.length;
  clock=Date.parse('2026-10-15T15:00:01Z');
  intervals.find(timer=>timer.ms===1000).fn();
  const current=window.BaroLabHistory.loadHistoryStore()['2026-10-16'];
  assert.equal(JSON.stringify(window.BaroLabHistory.loadHistoryStore()['2026-10-15']),previousBefore,'midnight preserves historical records');
  assert.equal(current.cf.completed,0);assert.equal(current.naver.completed,0);
  assert.equal(current.cf.sourceStatus,'unknown');assert.equal(current.naver.sourceStatus,'unknown');
  assert.equal(current.cf.items.length+current.naver.items.length,0,'rollover never fabricates publication evidence');
  assert.equal(events.length,eventCount+1);
  assert.equal(events.at(-1).type,'barolab-publications-updated');
  assert.equal(events.at(-1).stats.date,'2026-10-16');
  assert.equal(events.at(-1).stats.totalCompleted,0);
  assert.equal(events.at(-1).stats.naverSourceStatus,'unknown');
  assert.equal(fetches,fetchesBefore,'rollover does not trigger collection or fetch');
  const writesAfter=writes,eventsAfter=events.length;
  for(let i=0;i<5;i++)intervals.find(timer=>timer.ms===1000).fn();
  listeners.focus();listeners.pageshow();listeners.visibilitychange();
  assert.equal(writes,writesAfter,'same-day timer and focus do not write storage');
  assert.equal(events.length,eventsAfter);

  const store=window.BaroLabHistory.loadHistoryStore();
  store['2026-10-17']={date:'2026-10-17',cf:{target:16,completed:2,items:[{id:'existing'}],sourceStatus:'current'},naver:{target:7,completed:1,items:[],sourceStatus:'current'}};
  localStorage.setItem('BAROLAB_POSTING_HISTORY_V1',JSON.stringify(store));
  clock=Date.parse('2026-10-16T15:00:01Z');listeners.focus();
  assert.equal(events.at(-1).stats.date,'2026-10-17');
  assert.equal(events.at(-1).stats.totalCompleted,3,'focus keeps existing current-day evidence from another tab');
  assert.equal(window.BaroLabHistory.loadHistoryStore()['2026-10-15'].cf.completed,13);

  const index=fs.readFileSync(path.join(__dirname,'../dashboard/index.html'),'utf8').replace(/\r\n/g,'\n');
  const rateBlock=index.match(/if \(kpiRateEl\) \{([\s\S]*?)\n    \}\n    if \(headerQuotaEl\)/);
  assert.ok(rateBlock,'overview publication source label block exists');
  for(const statuses of [{cfSourceStatus:'unknown',naverSourceStatus:'current'},{cfSourceStatus:'current',naverSourceStatus:'unknown'}]) {
    const rate=new Element();
    vm.runInNewContext('if (kpiRateEl) {'+rateBlock[1]+'}',{kpiRateEl:rate,todayStats:statuses,overallTarget:23,overallCompleted:0});
    assert.equal(rate.textContent,'오늘 발행 기록 조회 대기','unknown source is not a confirmed pending schedule');
  }
}

async function main() {
  const snapshot=fixture(),before=JSON.stringify(snapshot);
  const old=await harness(snapshot,'2026-10-15T15:00:01Z'); // October 16, 00:00:01 KST.
  assert.equal(old.elements['summary-visitors-value'].textContent,'미수집');
  assert.match(old.elements['summary-visitors-coverage'].textContent,/2026-10-15.*갱신 필요/);
  assert.equal(old.elements['overview-today-cf'].textContent,'미수집');
  assert.equal(old.elements['overview-today-naver'].textContent,'미수집');
  assert.equal(old.window.BaroLabTraffic.coverage(snapshot.trafficAnalysis,'today').ga4,0);
  assert.equal(old.elements['metric-revenue-value'].textContent,'미수집');
  assert.match(old.elements['revenue-period'].textContent,/어제 2026-10-15.*오늘 2026-10-16.*자료 기준 2026-10-15/);
  assert.doesNotMatch(old.elements['revenue-overview'].textContent,/47/);
  assert.match(old.elements['revenue-daily'].textContent,/2026-10-15.*47/,'dated historical revenue remains visible');
  assert.match(old.elements['revenue-sources'].textContent,/CF only/,'source scope remains visible');
  assert.match(old.elements['metrics-refresh-status'].textContent,/2026.*10.*15/,'collection label includes its actual date');
  assert.equal(old.elements['growth-naver-counters'].children[0].children[1].textContent,'미수집');
  assert.equal(old.elements['growth-naver-counters'].children[0].children[2].textContent,'47','previous snapshot today becomes actual yesterday');
  assert.equal(JSON.stringify(snapshot),before,'rendering must not mutate source data');

  const cf=await harness(fixture(),'2026-10-15T15:00:01Z','cf');
  assert.equal(cf.elements['summary-visitors-value'].textContent,'미수집');
  assert.equal(cf.elements['summary-stat-day'].textContent,'미수집','old yesterday must not become the new yesterday');
  const future=await harness(fixture('2026-10-17'),'2026-10-16T02:00:00Z','cf');
  assert.equal(future.elements['summary-visitors-value'].textContent,'미수집');
  assert.equal(future.elements['overview-today-cf'].textContent,'미수집');
  assert.equal(future.elements['metric-revenue-value'].textContent,'미수집');
  const futureNaver=await harness(fixture('2026-10-17'),'2026-10-16T02:00:00Z');
  assert.equal(futureNaver.elements['summary-visitors-value'].textContent,'미수집');
  assert.equal(futureNaver.elements['growth-naver-counters'].children[0].children[1].textContent,'미수집');

  const zero=await harness(fixture('2026-10-16',0),'2026-10-16T02:00:00Z');
  assert.match(zero.elements['summary-visitors-value'].textContent,/^0명/,'a verified zero must stay zero');
  assert.match(zero.elements['summary-visitors-coverage'].textContent,/1\/5/,'partial scope must stay explicit');
  assert.equal(zero.elements['overview-today-cf'].textContent,'0명');
  assert.match(zero.elements['metric-revenue-value'].textContent,/0\.00/);
  assert.equal(zero.window.BaroLabTraffic.coverage(fixture('2026-10-16',0).trafficAnalysis,'today').ga4,1);

  const midnight=await harness(fixture(),'2026-10-15T14:59:59Z');
  assert.match(midnight.elements['summary-visitors-value'].textContent,/^47명/);
  midnight.failFetch();midnight.setTime('2026-10-15T15:00:01Z');midnight.listeners.focus();
  assert.equal(midnight.elements['summary-visitors-value'].textContent,'미수집');
  assert.equal(midnight.elements['overview-today-cf'].textContent,'미수집');
  assert.equal(midnight.elements['metric-revenue-value'].textContent,'미수집');
  await midnight.intervals.find(timer=>timer.ms===60000).fn();await midnight.settle();
  assert.equal(midnight.elements['summary-visitors-value'].textContent,'미수집','failed refresh must not restore yesterday');
  assert.equal(midnight.elements['metric-revenue-value'].textContent,'미수집');
  const freshSources=fixture('2026-10-16',8);
  delete freshSources.collectionObservability;
  const healthRecord={schema:1,evidenceMode:'windows_static_fallback',collectionStatus:'failed',checkedAt:'2026-10-15T13:56:24Z',exportedAt:'2026-10-15T14:13:16Z',sources:[]};
  const delayedRecord=await harness(freshSources,'2026-10-16T14:00:00Z','naver',healthRecord);
  assert.match(delayedRecord.elements['collection-health'].children[0].textContent,/운영 기록 갱신 지연/);
  assert.doesNotMatch(delayedRecord.elements['collection-health'].children[0].textContent,/수집 실패|수집 지연/);
  assert.match(delayedRecord.elements['collection-health'].textContent,/운영 기록 기준 2026.*10.*15.*22[^0-9]*56[^0-9]*24/);
  assert.match(delayedRecord.elements['summary-visitors-value'].textContent,/^8명/,'old operating records must not hide fresh source results');
  assert.match(delayedRecord.elements['metrics-refresh-status'].textContent,/2026.*10.*16/,'actual source collection date is retained');
  await historyRollover();
  console.log('Dashboard date regressions passed: previous/future snapshots, historical evidence, missing/zero, scope, midnight, failed refresh and offline publication rollover.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
