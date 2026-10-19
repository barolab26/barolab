const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const revenue=require('./metrics.js');
const day='2026-10-19';
const period=(status,amounts={},reason='')=>({status,amounts,reason});
const fixture={today:day,totals:{today:period('partial',{USD:0,KRW:0}),month:period('partial',{USD:12,KRW:300}),yesterday:period('partial',{USD:7})},categories:[
 {id:'adsense',periods:{today:period('pending',{},'D+1 보고서 대기'),yesterday:period('collected',{USD:99})}},
 {id:'adpost',periods:{today:period('collected',{KRW:0})}},
 {id:'affiliate',periods:{today:period('configured_no_report_api')}}]};

test('observed zero, pending settlement and configuration without a report are distinct',()=>{
 assert.equal(revenue.periodView(period('collected',{KRW:0})).text,'₩0');
 assert.match(revenue.periodView(period('collected',{KRW:0})).note,/0원 확인/);
 assert.equal(revenue.periodView(period('pending',{},'D+1 정산 대기')).hasAmount,false);
 assert.match(revenue.periodView(period('pending',{},'D+1 정산 대기')).note,/D\+1/);
 const configured=revenue.periodView(period('configured_no_report_api',{KRW:0}));
 assert.equal(configured.hasAmount,false);
 assert.match(configured.text,/설정됨.*정산서 미확인/);
 for(const status of ['auth_required','not_enrolled','duplicate_source','not_configured']) assert.equal(revenue.currencyValue(period(status,{KRW:0}),'KRW'),null);
});

test('missing or malformed values never become zero and original currencies stay separate',()=>{
 const p=period('partial',{KRW:0,USD:'1.20',EUR:null,JPY:'',GBP:'invalid',CAD:false,AUD:' ',CHF:[]});
 assert.deepEqual(revenue.periodView(p).amounts,{KRW:0,USD:1.2});
 assert.equal(revenue.currencyValue(null,'USD'),null);
 assert.match(revenue.periodView(period('collected',{USD:0})).note,/수익 0 확인/);
 assert.equal(revenue.categoryPeriod(fixture,'adsense','today','2026-10-20'),null);
 assert.equal(revenue.currencyValue(revenue.categoryPeriod(fixture,'adsense','today',day),'USD'),null);
});

test('source states distinguish affiliate tracking from report access without exposing credential values',()=>{
 const view=revenue.sourceView({status:'configured_no_report_api',configurationStatus:'configured',reportCapability:'affiliate_tracking_only',credentialPresence:{apiKey:false,apiSecret:false,affiliateIds:true,login:'SECRET_VALUE',token:'SECRET_TOKEN'}});
 assert.match(view.statusLabel,/설정됨/);
 assert.match(view.capabilityLabel,/추적 ID만/);
 assert.match(view.credentialLabel,/제휴 추적 ID 있음/);
 assert(!JSON.stringify(view).includes('SECRET'));
 assert.equal(revenue.sourceView({status:'not_enrolled',optional:true}).accountLabel,'추가 계정');
 assert.equal(revenue.sourceView({status:'collected'}).statusLabel,'보고서 확인');
 assert.equal(revenue.sourceView({status:'collected',reportCapability:'authenticated_html_report'}).capabilityLabel,'로그인 리포트 연결');
});

function renderIndex(data) {
 const elements=new Map();
 const get=id=>{if(!elements.has(id))elements.set(id,{textContent:'',style:{}});return elements.get(id);};
 const html=fs.readFileSync(__dirname+'/index.html','utf8');
 const script=html.slice(html.indexOf('        const revenueView=window.BaroLabRevenue;'),html.indexOf('        // Big Gauge 3:'));
 vm.runInNewContext(script,{window:{BaroLabRevenue:revenue},data:{revenue:data},today:day,document:{getElementById:get},setRingGauge:(id,circ,pct)=>{get(id).pct=pct;}});
 return get;
}
test('overview rendering does not substitute yesterday and distinguishes collected zero from pending',()=>{
 const get=renderIndex(fixture);
 assert.equal(get('val-rev-adsense').textContent,'집계 대기');
 assert.equal(get('val-rev-adpost').textContent,'₩0');
 assert.match(get('val-rev-affiliate').textContent,/설정됨/);
 assert.equal(get('bar-rev-adpost').style.width,'0%');
 assert.equal(get('arc-revenue-goal').pct,0);
 const stale=renderIndex({...fixture,today:'2026-10-18'});
 assert.equal(stale('gauge-rev-pct').textContent,'—');
 assert.equal(stale('val-rev-adsense').textContent,'미수집');
});

test('growth headline uses actual period totals, includes KRW zero, and does not fabricate current revenue',()=>{
 const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,{textContent:'',style:{}});return elements.get(id);};
 const html=fs.readFileSync(__dirname+'/growth.html','utf8');
 const script=html.slice(html.indexOf('    // KPI 1: Revenue'),html.indexOf('    // KPI 2: Visitors'));
 class Clock extends Date {static now(){return Date.parse(day+'T03:00:00Z');}}
 const run=doc=>vm.runInNewContext(script,{latestMetricsDoc:{revenue:doc},window:{BaroLabRevenue:revenue},Date:Clock,$:get});
 run(fixture);
 assert.match(get('kpi-rev-today').textContent,/₩0/);
 assert.equal(get('kpi-rev-bar').style.width,'0%');
 run({...fixture,today:'2026-10-18'});
 assert.match(get('kpi-rev-today').textContent,/미수집/);
 assert.match(get('kpi-rev-pct').textContent,/USD 미확인/);
});
