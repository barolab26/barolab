// Offline regression: node dashboard/test_cf_dashboard_dates.cjs
// Exercises the actual page and action script in a small DOM double; no network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, 'cf.html'), 'utf8');
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(match => match[1]).join('\n');
const actions = fs.readFileSync(path.join(__dirname, 'workflow-actions.js'), 'utf8');
function node(tag = '') {
  const result = {textContent:'', value:'', style:{}, disabled:false, onclick:null,
    children:[], listeners:{}, classList:{add(){},remove(){}}, scrollTop:0,
    appendChild(child){this.children.push(child);},
    addEventListener(name, fn){this.listeners[name]=fn;},
    querySelector(){return node();}};
  Object.defineProperty(result, 'innerHTML', {get(){return this.html || '';}, set(value){
    this.html=value; this.children=tag==='tr' ? Array.from({length:7},()=>node()) : [];
  }});
  return result;
}
function harness(instant) {
  let now = Date.parse(instant);
  const nodes = new Map(), timers = [], requests = [], opened = [];
  const get = id => {if (!nodes.has(id)) nodes.set(id,node()); return nodes.get(id);};
  class Clock extends Date {constructor(...args){super(...(args.length?args:[now]));} static now(){return now;}}
  const context = vm.createContext({Date:Clock, Intl, URL, console, Event,
    document:{getElementById:get,createElement:node,querySelector:get},
    window:{location:{protocol:'http:'},open:(...args)=>opened.push(args)},
    setInterval:fn=>timers.push(fn),setTimeout:()=>{},
    fetch:(...args)=>{requests.push(args);return new Promise(()=>{});}});
  vm.runInContext(script,context);
  const run = code => vm.runInContext(code,context);
  return {context,get,timers,requests,opened,run,clock:value=>{now=Date.parse(value);},
    source(schedule,state={}) {context.fixtureSchedule=schedule;context.fixtureState=state;
      run('cfSourceSchedule=fixtureSchedule; cfSourceState=fixtureState; renderCFDay();');}};
}
const row = (status='published',url='https://example.test/post') => ({id:1,order:1,
  domain:'example.test',name:'Example',category:'Fixture',title:'Test article',icon:'E',
  color:'#123456',status,publicUrl:url,currentStage:status==='retry_wait'?1:7});
const schedule = (date,items=[row()])=>({date,total:items.length,items});
const state = date=>({date,scheduleDate:date,status:'processing',executionState:'running',domain:'example.test'});
let checks=0;
function test(name,fn) {return Promise.resolve().then(fn).then(()=>{checks++;console.log('PASS '+name);});}
(async()=>{
  await test('prior-day schedule cannot become today jobs or controls',()=>{
    const h=harness('2026-10-15T16:00:00Z'), raw=schedule('2026-10-15');
    h.source(raw,state('2026-10-15'));
    assert.equal(h.run('CF_SITES.length'),0);
    assert.equal(h.get('kpi-done-count').textContent,'0건');
    assert.equal(h.get('kpi-wait-count').textContent,'미확인');
    assert.equal(h.get('header-badge-status').textContent,'오늘 일정 대기 · 발행 완료 0건');
    assert.match(h.get('connection-status').textContent,/기준 2026-10-16 KST · 원본 2026-10-15/);
    assert.equal(h.get('cf-current-date').textContent,'2026-10-16 · KST');
    for(const id of ['btn-open-current-live','btn-prev-blog','btn-next-blog','wf-retry-button']) assert.equal(h.get(id).disabled,true);
    assert.equal(h.get('wf-stages-container').children.length,0);
    assert.equal(h.context.window.__PIPELINE_STATUS__.status,'unknown');
    assert.equal(raw.items[0].status,'published');
  });
  await test('KST midnight works independently of system timezone',()=>{
    const h=harness('2026-10-15T14:59:59Z');h.source(schedule('2026-10-15'),state('2026-10-15'));
    assert.equal(h.get('kpi-done-count').textContent,'1건');
    h.clock('2026-10-15T15:00:00Z');h.run('updateClock()');
    assert.equal(h.get('kpi-done-count').textContent,'0건');
    assert.equal(h.get('kpi-wait-count').textContent,'미확인');
    assert.equal(h.get('cf-current-date').textContent,'2026-10-16 · KST');
    assert.equal(h.get('btn-open-current-live').onclick,null);
  });
  await test('current schedule counts unique valid public URLs only',()=>{
    const h=harness('2026-10-15T16:00:00Z');
    h.source(schedule('2026-10-16',[row(),row('published','javascript:alert(1)'),row('waiting','https://example.test/next'),row()]),state('2026-10-16'));
    assert.equal(h.get('kpi-done-count').textContent,'1건');
    assert.equal(h.get('kpi-wait-count').textContent,'2건');
    assert.equal(h.get('btn-open-current-live').disabled,false);
    assert.equal(h.get('wf-badge-status').textContent,'작업 실행 중');
  });
  await test('yesterday pipeline execution does not attach to new schedule',()=>{
    const h=harness('2026-10-15T16:00:00Z');
    h.source(schedule('2026-10-16',[row('waiting')]),{...state('2026-10-15'),date:'2026-10-16'});
    assert.equal(h.get('wf-badge-status').textContent,'오늘 실행 상태 미확인');
    assert.equal(h.context.window.__PIPELINE_STATUS__.status,'unknown');
  });
  await test('poll failure across midnight removes yesterday display',async()=>{
    const h=harness('2026-10-15T14:59:59Z');h.source(schedule('2026-10-15'),state('2026-10-15'));
    h.clock('2026-10-15T15:00:00Z');
    h.context.fetch=async()=>{throw new Error('offline');};
    await h.run('statusRefreshRunning=false; pollPipelineStatus()');
    assert.equal(h.get('kpi-done-count').textContent,'0건');
    assert.equal(h.get('wf-stages-container').children.length,0);
    assert.match(h.get('connection-status').textContent,/offline/);
    assert.match(h.get('connection-status').textContent,/2026-10-16/);
  });
  await test('pending poll does not block clock rollover',()=>{
    const h=harness('2026-10-15T14:59:59Z');h.source(schedule('2026-10-15'),state('2026-10-15'));
    h.clock('2026-10-15T15:00:00Z');h.run('updateClock()');
    assert.equal(h.run('statusRefreshRunning'),true);
    assert.equal(h.run('CF_SITES.length'),0);
  });
  await test('midnight click cannot retry yesterday task before clock tick',async()=>{
    const h=harness('2026-10-15T14:59:59Z');h.source(schedule('2026-10-15',[row('retry_wait')]),state('2026-10-15'));
    vm.runInContext(actions,h.context);
    assert.equal(h.get('wf-retry-button').disabled,false);
    const before=h.requests.length;
    h.clock('2026-10-15T15:00:00Z');
    await h.get('wf-retry-button').listeners.click();
    assert.equal(h.requests.length,before);
  });
  await test('midnight click cannot open yesterday public URL before clock tick',()=>{
    const h=harness('2026-10-15T14:59:59Z');h.source(schedule('2026-10-15'),state('2026-10-15'));
    h.clock('2026-10-15T15:00:00Z');h.get('btn-open-current-live').onclick();
    assert.equal(h.opened.length,0);
  });
  await test('empty current schedule is a confirmed zero plan',()=>{
    const h=harness('2026-10-15T16:00:00Z');h.source(schedule('2026-10-16',[]),state('2026-10-16'));
    assert.equal(h.get('kpi-wait-count').textContent,'0건');
    assert.equal(h.get('wf-timeline-selection').textContent,'2026-10-16 · 오늘 등록된 작업 없음');
  });
  console.log(`${checks} CF dashboard date regressions passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});

// Overview: one central board per channel and GA4 sessions retain their source date.
{
  const overview = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
  for (const id of ['bento-cf-grid-16', 'bento-naver-grid-5', 'overview-kin-title', 'overview-threads', 'app-projects-gauge-card']) {
    assert.equal(overview.split(`id="${id}"`).length - 1, 1, `single overview board: ${id}`);
  }
  for (const match of overview.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
  const start = overview.indexOf('let latestVisitorMap =');
  const end = overview.indexOf('let latestCfPublishedMap =', start);
  const context = vm.createContext({Date, console});
  vm.runInContext(overview.slice(start, end), context);
  const run = code => vm.runInContext(code, context);
  run(`bindCFSessionMetrics({sites:[{site:{site_id:'www.example.test'},traffic:{status:'collected',sessions:25,points:[{day:'2026-10-17',sessions:9},{day:'2026-10-16',sessions:2}]}}]}, '2026-10-19')`);
  assert.equal(run("latestVisitorMap.cf['example.test']"), 9);
  assert.equal(run("latestVisitorMap.cfDate['example.test']"), '2026-10-17');
  assert.equal(run("cfSessionLabel('example.test')"), '10-17 9회');
  run(`bindCFSessionMetrics({sites:[{site:{site_id:'example.test'},traffic:{status:'collected',points:[{day:'2026-10-17',sessions:0}]}}]}, '2026-10-19')`);
  assert.equal(run("latestVisitorMap.cf['example.test']"), 0);
  run(`bindCFSessionMetrics({sites:[]}, '2026-10-20')`);
  assert.equal(run("cfSessionLabel('example.test')"), 'GA4 미수집');
  run(`bindCFSessionMetrics({trafficAnalysis:{today:'2026-10-19',sites:[{site:{site_id:'example.test'},ga4:{status:'collected',periods:{today:{sessions:7,users:3}}}}]}}, '2026-10-19')`);
  assert.equal(run("latestVisitorMap.cf['example.test']"), 7);
  run(`bindCFSessionMetrics({trafficAnalysis:{today:'2026-10-18',sites:[{site:{site_id:'example.test'},ga4:{periods:{today:{sessions:7}}}}]}}, '2026-10-19')`);
  assert.equal(run("latestVisitorMap.cf['example.test']"), undefined);
  console.log('PASS overview unique boards and dated GA4 sessions');
}
