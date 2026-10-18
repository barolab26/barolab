const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const view = require('./memory_graph_view.js');

const fixture = {
  nodes: Array.from({length: 20}, (_, i) => ({id: `n${i}`, rel: `notes/n${i}.md`, label: `Node ${i}`, isCoreHub: i < 13})),
  edges: Array.from({length: 18}, (_, i) => [i, i + 1]),
};

test('all graph retains 13 hubs, every knowledge node including an orphan, and every edge', () => {
  const graph = view.normalizeGraph(fixture);
  assert.equal(graph.nodes.length, 20);
  assert.equal(graph.nodes.filter(n => n.isCoreHub).length, 13);
  assert.equal(graph.nodes[19].deg, 0);
  assert.deepEqual(graph.edges, fixture.edges);
  assert.throws(() => view.normalizeGraph({detail:'Not Found'}), /응답 형식/);
  assert.throws(() => view.normalizeGraph({...fixture,edges:[[0,99]]}), /노드 번호/);
});

test('fractional DPI has stable integer backing size and fit keeps finite nodes on screen after resizing', () => {
  const points = fixture.nodes.map((_, i) => ({x: Math.cos(i) * i * 80, y: Math.sin(i) * i * 90}));
  for (const [width,height] of [[821,667],[821,480],[400,560],[1280,700]]) {
    const size = view.canvasSize(width,height,1.25);
    assert(Number.isInteger(size.pixelWidth));
    assert(Number.isInteger(size.pixelHeight));
    const camera = view.cameraFor([...points,{x:NaN,y:Infinity}],width,height);
    for (const p of points) {
      assert(p.x * camera.s + camera.x >= 0 && p.x * camera.s + camera.x <= width);
      assert(p.y * camera.s + camera.y >= 0 && p.y * camera.s + camera.y <= height);
    }
  }
  assert.equal(view.canvasSize(0,0,NaN).height,580);
});

function pageHarness(graphResponse, overrideFetch, search='') {
  const elements = new Map(), calls = [], frames = [], labels = [], polls = [];
  let paintCount = 0;
  const context = new Proxy({fillText:(text,x,y)=>{labels.push({text,x,y});paintCount++;},measureText: t => ({width:String(t).length*7}),createRadialGradient: () => ({addColorStop(){}})}, {get(target,key){return target[key] || (() => {paintCount++;});}, set(target,key,value){target[key]=value;return true;}});
  function element(id) {
    if (!elements.has(id)) elements.set(id,{id,hidden:false,style:{},dataset:{},value:'',textContent:'',innerHTML:'',clientWidth:821,clientHeight:667,width:0,height:0,handlers:{},classList:{values:new Set(),add(name){this.values.add(name);},remove(name){this.values.delete(name);},toggle(){},contains(name){return this.values.has(name);}},addEventListener(type,handler){this.handlers[type]=handler;},querySelectorAll(){return [];},getContext(){return context;},getBoundingClientRect(){return {left:0,top:0};},setAttribute(name,value){this.attributes ||= {};this.attributes[name]=value;},focus(){},click(){return this.handlers.click?.({currentTarget:this});}});
    return elements.get(id);
  }
  element('memory-canvas').parentElement = element('graph-viewport');
  element('doc-editor').hidden = true;
  element('delete-doc-confirmation').hidden = true;
  const chips = ['all','skill'].map(cat => {const e=element(`chip-${cat}`);e.getAttribute=()=>cat;return e;});
  const sandbox = {console, URL, URLSearchParams, AbortController, MemoryGraphView:view, devicePixelRatio:1.25,
    document:{hidden:false,addEventListener(){},getElementById:element,querySelectorAll: selector=>selector.includes('data-cat')?chips:[]},
    location:{protocol:'http:',hostname:'example.test',origin:'http://example.test:8790',port:'8790',search},
    requestAnimationFrame: fn => frames.push(fn), addEventListener(){},ResizeObserver:class{observe(){}},
    Path2D:class{moveTo(){}lineTo(){}closePath(){}},
    setTimeout:(fn,delay)=>delay===4000?(polls.push(fn),polls.length):setTimeout(fn,delay), clearTimeout, confirm:()=>true, alert(){},
    fetch: async (url, options={}) => {
      calls.push({url,options});
      if (overrideFetch) { const response = overrideFetch(url,options); if (response) return response; }
      if(url.includes('/graph')) return graphResponse;
      if(options.method==='PATCH') return {ok:true,json:async()=>({ok:true})};
      return {ok:true,json:async()=>({rel:'notes/n0.md',title:'Original',content:'Body',category:'skill',links:['n1'],backlinks:[],revision:'rev1',editable:true,deletable:true})};
    },
  };
  sandbox.window=sandbox;
  const html=fs.readFileSync(__dirname+'/memory.html','utf8');
  const script=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
  vm.runInNewContext(script,sandbox);
  return {element,calls,frames,labels,polls,document:sandbox.document,paintCount:()=>paintCount,flush:()=>new Promise(resolve=>setImmediate(resolve))};
}

test('HTTP 404 stays an explicit graph error, never becomes a successful empty graph',async()=>{
  const page=pageHarness({ok:false,status:404,json:async()=>({detail:'Not Found'})});
  await page.flush();
  assert.match(page.element('graph-status').textContent,/404/);
  assert.equal(page.element('graph-status').hidden,false);
  assert.equal(page.element('stat-visible-nodes').textContent,'확인 불가');
  assert.equal(page.element('vault-integrity-pct').textContent,'확인 불가');
  assert.equal(page.element('graph-data-state').textContent,'연결 실패');
  assert(!page.calls.some(c=>c.url.includes('/doc?')));
  assert(!fs.readFileSync(__dirname+'/memory.html','utf8').includes('● LIVE'));
});

test('real page script paints loaded graph, all resets search, and editor PATCH includes revision',async()=>{
  const page=pageHarness({ok:true,status:200,json:async()=>({...fixture,stats:{total:20,coreHubs:13,links:18}})});
  await page.flush();
  assert.match(page.element('stat-visible-nodes').textContent,/20개 활성/);
  assert.equal(page.element('memory-canvas').attributes['data-node-count'],'20');
  assert.equal(page.element('memory-canvas').attributes['data-edge-count'],'18');
  assert.match(page.element('graph-node-list').innerHTML,/Node 19/);
  assert.match(page.element('lbl-orphan-nodes').textContent,/1$/);
  assert.equal(page.element('vault-integrity-pct').textContent,'95%');
  page.frames.shift()();
  assert(page.paintCount()>30);
  page.element('graph-search').value='filtered';
  page.element('chip-all').click();
  await page.flush();
  assert.equal(page.element('graph-search').value,'');
  assert(page.calls.filter(c=>c.url.includes('/graph')).every(c=>c.url.includes('category=all&q=')));
  page.element('btn-edit-doc').click();
  page.element('edit-doc-title').value='Updated';
  page.element('edit-doc-content').value='Changed body';
  await page.element('doc-editor').handlers.submit({preventDefault(){}});
  const patch=page.calls.find(c=>c.options.method==='PATCH');
  assert(patch);
  assert.equal(JSON.parse(patch.options.body).expectedRevision,'rev1');
  assert.equal(JSON.parse(patch.options.body).content,'Changed body');
  assert.match(page.element('doc-status').textContent,/저장되었습니다/);
});


test('revision conflict preserves unsaved draft and protected nodes cannot issue deletion', async () => {
  const page=pageHarness({ok:true,status:200,json:async()=>fixture}, (url, options) => {
    if (options.method === 'PATCH') return {ok:false,status:409,json:async()=>({detail:'문서가 변경되었습니다. 다시 확인하세요.'})};
  });
  await page.flush();
  page.element('btn-edit-doc').click();
  page.element('edit-doc-content').value='Keep my unsaved work';
  await page.element('doc-editor').handlers.submit({preventDefault(){}});
  assert.equal(page.element('doc-editor').hidden,false);
  assert.equal(page.element('edit-doc-content').value,'Keep my unsaved work');
  assert.match(page.element('doc-status').textContent,/다시 확인/);
  const protectedPage=pageHarness({ok:true,status:200,json:async()=>fixture}, (url) => {
    if (url.includes('/doc?')) return {ok:true,json:async()=>({rel:'hubs/core.md',title:'Protected',revision:'rev1',editable:false,deletable:false,readOnlyReason:'불변 원본'})};
  });
  await protectedPage.flush();
  assert.equal(protectedPage.element('btn-edit-doc').disabled,true);
  assert.equal(protectedPage.element('btn-delete-doc').disabled,true);
  await protectedPage.element('btn-delete-doc').click();
  assert(!protectedPage.calls.some(c=>c.options.method==='DELETE'));
  const boundedPage=pageHarness({ok:true,status:200,json:async()=>fixture},url=>url.includes('/doc?')?{ok:true,json:async()=>({rel:'memory/MEMORY.md',title:'Memory',revision:'rev1',sourceKind:'bounded_memory',editable:true,deletable:false})}:null);
  await boundedPage.flush();
  assert.equal(boundedPage.element('btn-edit-doc').disabled,false);
  assert.equal(boundedPage.element('btn-delete-doc').disabled,true);
  assert.match(boundedPage.element('doc-status').textContent,/항목은 원문 편집에서 삭제 가능/);
});

test('inline delete requires confirmation, supports cancel, sends revision, and restores trash', async () => {
  const page=pageHarness({ok:true,status:200,json:async()=>fixture}, (url, options) => {
    if (options.method==='DELETE') return {ok:true,json:async()=>({ok:true,trashId:'trash-safe-id',restorable:true})};
    if (url.includes('/trash/')) return {ok:true,json:async()=>({ok:true,rel:'notes/n0.md'})};
  });
  await page.flush();
  await page.element('btn-delete-doc').click();
  assert.equal(page.element('delete-doc-confirmation').hidden,false);
  assert.match(page.element('delete-doc-target').textContent,/Original/);
  assert(!page.calls.some(c=>c.options.method==='DELETE'),'opening confirmation must not delete');
  page.element('btn-cancel-delete-doc').click();
  assert.equal(page.element('delete-doc-confirmation').hidden,true);
  assert(!page.calls.some(c=>c.options.method==='DELETE'),'cancelling must not delete');
  await page.element('btn-delete-doc').click();
  await page.element('btn-confirm-delete-doc').click();
  assert(page.calls.some(c=>c.options.method==='DELETE' && c.url.includes('expected_revision=rev1')));
  assert.equal(page.element('btn-restore-doc').hidden,false);
  assert.match(page.element('doc-status').textContent,/복구/);
  await page.element('btn-restore-doc').click();
  assert(page.calls.some(c=>c.options.method==='POST' && c.url.includes('/trash/trash-safe-id/restore')));
  assert.equal(page.element('btn-restore-doc').hidden,true);
  assert.match(page.element('doc-status').textContent,/복구했습니다/);
});

test('NAS missing route discovers loopback once and never retries writes or missing docs on another backend', async () => {
  const page=pageHarness({ok:false,status:404,json:async()=>({detail:'Not Found'})}, (url,options) => {
    if (url.startsWith('http://127.0.0.1:8792') && url.includes('/graph')) return {ok:true,status:200,json:async()=>fixture};
    if (url.startsWith('http://127.0.0.1:8792') && url.includes('/doc?')) {
      if (options.method==='PATCH') return {ok:false,status:503,json:async()=>({detail:'backend write unavailable'})};
      return {ok:true,json:async()=>({rel:'notes/n0.md',title:'Original',content:'Body',revision:'rev1',editable:true,deletable:true})};
    }
  });
  await page.flush();
  assert.equal(page.element('memory-canvas').attributes['data-api-base'],'http://127.0.0.1:8792');
  assert.match(page.element('stat-visible-nodes').textContent,/20개 활성/);
  page.element('btn-edit-doc').click();
  await page.element('doc-editor').handlers.submit({preventDefault(){}});
  const writes=page.calls.filter(c=>c.options.method==='PATCH');
  assert.equal(writes.length,1);
  assert(writes[0].url.startsWith('http://127.0.0.1:8792'));
  assert(page.calls.filter(c=>c.url.includes('/doc?')).every(c=>c.url.startsWith('http://127.0.0.1:8792')));
  assert.match(page.element('doc-status').textContent,/write unavailable/);
});

test('dense hub clique stays spread across the canvas alongside disconnected memories', async () => {
  const nodes=Array.from({length:25},(_,i)=>({id:`dense${i}`,rel:`notes/dense${i}.md`,label:`Dense ${i}`,isCoreHub:i<13}));
  const edges=[];
  for(let i=0;i<16;i++) for(let j=i+1;j<16;j++) edges.push([i,j]);
  const page=pageHarness({ok:true,status:200,json:async()=>({nodes,edges})});
  await page.flush();
  for(let i=0;i<60;i++) page.frames.shift()();
  const labels=page.labels.slice(-25).filter(p=>/^Dense (?:[0-9]|1[0-5])$/.test(p.text));
  assert(labels.length>=15);
  assert(Math.max(...labels.map(p=>p.x))-Math.min(...labels.map(p=>p.x))>300,`dense hub span: ${Math.max(...labels.map(p=>p.x))-Math.min(...labels.map(p=>p.x))}`);
  assert.equal(page.element('memory-canvas').attributes['data-edge-count'],'120');
});

test('explicit API origin is displayed and failure cannot silently select a different service', async () => {
  const page=pageHarness({ok:true,status:200,json:async()=>fixture}, (url) => {
    if (url.startsWith('http://localhost:8792')) return {ok:false,status:503,json:async()=>({detail:'Unavailable'})};
  }, '?memoryApi=http%3A%2F%2Flocalhost%3A8792');
  await page.flush();
  assert(page.calls.length>0);
  assert(page.calls.every(c=>c.url.startsWith('http://localhost:8792')));
  assert.match(page.element('memory-api-status').textContent,/연결 실패/);
  assert.match(page.element('graph-status').textContent,/503/);
});

test('core-hub glyph is always a star and knowledge stays a diamond regardless of degree or crew styling', () => {
  assert.equal(view.nodeShape({isCoreHub:true,subGroup:'crew',type:'agent'}),'star');
  assert.equal(view.nodeShape({isCoreHub:true,category:'skill'}),'star');
  assert.equal(view.nodeShape({isCoreHub:false,category:'skill',deg:99}),'diamond');
  assert.equal(view.nodeShape({type:'agent',category:'episodic'}),'diamond');
});

test('background polling applies changed nodes/edges without moving existing layout and preserves drafts', async () => {
  let graph=structuredClone(fixture);
  const page=pageHarness({ok:true,status:200,json:async()=>graph});
  await page.flush();
  for(let i=0;i<60;i++) page.frames.shift()();
  const before=page.labels.findLast(p=>p.text==='Node 5');
  const docCalls=()=>page.calls.filter(c=>c.url.includes('/doc?')).length;
  const initialDocs=docCalls();
  await page.polls.shift()();
  assert.equal(docCalls(),initialDocs,'unchanged graph must not reload the inspector');
  graph={nodes:[...graph.nodes.map(n=>({...n,updated:'2026-10-19T12:00:00Z'})),{id:'new',rel:'notes/new.md',label:'New memory',revision:'r2',sourceKind:'project_skill',updated:'2026-10-19T12:00:00Z'}],edges:[...graph.edges,[19,20]]};
  await page.polls.shift()();
  assert.equal(page.element('memory-canvas').attributes['data-node-count'],'21');
  assert.equal(page.element('memory-canvas').attributes['data-edge-count'],'19');
  assert.equal(page.element('stat-skill-cnt').textContent,'1건');
  assert(docCalls()>initialDocs,'updated selected-document timestamps must refresh in the inspector');
  page.frames.shift()();
  const after=page.labels.findLast(p=>p.text==='Node 5');
  assert(Math.abs(before.x-after.x)<0.1 && Math.abs(before.y-after.y)<0.1,'background update must preserve existing screen positions');
  page.element('btn-edit-doc').click();
  page.element('edit-doc-content').value='Unsaved local draft';
  graph={nodes:[...graph.nodes,{id:'later',rel:'notes/later.md',label:'Later memory'}],edges:graph.edges};
  await page.polls.shift()();
  assert.equal(page.element('memory-canvas').attributes['data-node-count'],'21');
  assert.equal(page.element('edit-doc-content').value,'Unsaved local draft');
  assert.match(page.element('graph-update-status').textContent,/마치면 반영/);
  page.element('btn-cancel-doc').click();
  await page.polls.shift()();
  assert.equal(page.element('memory-canvas').attributes['data-node-count'],'22');
  page.element('btn-open-new-note').click();
  graph={nodes:[...graph.nodes,{id:'modal',rel:'notes/modal.md',label:'Modal memory'}],edges:graph.edges};
  await page.polls.shift()();
  assert.equal(page.element('memory-canvas').attributes['data-node-count'],'22');
  page.element('btn-close-modal').click();
  await page.polls.shift()();
  assert.equal(page.element('memory-canvas').attributes['data-node-count'],'23');
  page.document.hidden=true;
  const requests=page.calls.length;
  await page.polls.shift()();
  assert.equal(page.calls.length,requests,'hidden tab must not poll');
});

test('knowledge-note registration keeps text on API failure and labels the entry as a memo', async () => {
  const page=pageHarness({ok:true,status:200,json:async()=>fixture},(url,options)=>{
    if(url.endsWith('/note') && options.method==='POST') return {ok:false,status:409,json:async()=>({detail:'Duplicate title'})};
  });
  await page.flush();
  page.element('new-note-title').value='QA unique memory';
  page.element('new-note-content').value='A sufficiently long draft body';
  await page.element('btn-save-note').click();
  assert.equal(page.element('new-note-content').value,'A sufficiently long draft body');
  assert.match(page.element('new-note-status').textContent,/Duplicate/);
  const post=page.calls.find(c=>c.url.endsWith('/note'));
  assert(!Object.hasOwn(JSON.parse(post.options.body),'create'));
  assert.match(fs.readFileSync(__dirname+'/memory.html','utf8'),/실제 SKILL.md 파일은 그래프/);
});
