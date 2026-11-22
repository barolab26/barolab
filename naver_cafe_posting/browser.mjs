/* Fixed Cafe editor operations. Article/model strings are data, never code. */
import fs from 'node:fs/promises';
import crypto from 'node:crypto';
const hash=x=>crypto.createHash('sha256').update(JSON.stringify(x)).digest('hex');
const norm=x=>String(x||'').replace(/[\s\u200b\ufeff]+/g,'');
const emit=async(folder,name,value)=>fs.writeFile(folder+'/'+name,JSON.stringify(value,null,2),'utf8');
const expected=d=>d.blocks.flatMap(b=>b.type==='table'?b.rows.flat():b.text.split('\n')).filter(Boolean);

async function article(page){
  await page.waitForFunction(()=>!!(document.querySelector('#cafe_main')?.contentDocument||document).querySelector('.article_viewer'),undefined,{timeout:15000});
  return page.evaluate(()=>{const d=document.querySelector('#cafe_main')?.contentDocument||document,v=d.querySelector('.article_viewer');return {
    title:d.querySelector('.title_text')?.innerText,body:v.innerText,
    paragraphs:[...v.querySelectorAll('p')].map(p=>p.innerText).filter(t=>t.trim()),
    tables:[...v.querySelectorAll('table')].map(t=>[...t.rows].map(r=>[...r.cells].map(c=>c.innerText))),
    links:[...v.querySelectorAll('a[href]')].map(a=>({label:a.innerText,url:a.href})),
    info:d.querySelector('.article_info')?.innerText,
    board:[...d.querySelectorAll('.ArticleTitle a')].map(a=>a.innerText.trim()).find(t=>t.startsWith('[')),
    canEdit:[...d.querySelectorAll('a,button')].some(e=>e.innerText?.trim()==='수정')};});
}

function check(observed, document, title){
  if(norm(title)!==norm(document.title))throw Error('Title mismatch');
  if(document.presentation?.boardName&&observed.board!==document.presentation.boardName)throw Error('Category board mismatch');
  const body=norm(observed.body);
  let position=0;
  for(const text of expected(document)){
    const found=body.indexOf(norm(text),position);
    if(found<0)throw Error('Missing or reordered article content: '+text.slice(0,60));
    position=found+norm(text).length;
  }
  if(body!==norm(expected(document).join('')))throw Error('Unexpected article content or leftover old body');
  const wantedTables=document.blocks.filter(b=>b.type==='table').map(b=>b.rows);
  if(JSON.stringify(observed.tables.map(t=>t.map(r=>r.map(norm))))!==JSON.stringify(wantedTables.map(t=>t.map(r=>r.map(norm)))))throw Error('Table structure mismatch');
  const links=document.lineLinks||{};
  for(const [label,url] of Object.entries(links))if(!observed.links.some(a=>norm(a.label)===norm(label)&&a.url===url))throw Error('Clickable link missing');
  if(observed.links.some(a=>!Object.values(links).includes(a.url)))throw Error('Unexpected outgoing link');
  if(observed.paragraphs.length<document.blocks.filter(b=>b.type==='text'||b.type==='heading').length)throw Error('Paragraphs collapsed');
}

async function editor(page){
  return page.evaluate(()=>{const v=document.querySelector('.se-components-wrap');return {title:document.querySelector('textarea.textarea_input')?.value,body:v?.innerText,
    board:document.querySelector('.FormSelectButton .button')?.innerText.trim(),
    paragraphs:[...v.querySelectorAll('.se-text-paragraph')].map(p=>p.innerText).filter(t=>t.trim()),
    tables:[...v.querySelectorAll('table')].map(t=>[...t.rows].map(r=>[...r.cells].map(c=>c.innerText))),
    links:[...v.querySelectorAll('a[href],.se-link[data-href]')].map(a=>({label:a.innerText,url:a.href||a.getAttribute('data-href')}))};});
}

export async function run(input){
  const task=await taskSpace(input.space),page=task.page(input.page);
  const {folder,document,url,mode}=input;
  if(mode==='stage'){
    const previous=JSON.parse(await fs.readFile(folder+'/intent.json','utf8'));
    if(['submitting','submission_unknown','verified_updated','verified_published'].includes(previous.status))throw Error('Existing write receipt requires reconciliation, not repetition');
    if(url){
      if(previous.revisionAuthorized!==true||previous.url!==url)throw Error('Exact revision authorization required');
      // Preserve an already-open editor, including the user's unrelated tabs.
      const reader=await task.newPage();await reader.goto(url);const before=await article(reader);
      if(!before.canEdit)throw Error('Author editing permission absent');
      await emit(folder,'before.json',{url,observedAt:new Date().toISOString(),...before});
      await reader.close();
      if((await page.url())!==url+'/modify')await page.goto(url+'/modify');
    }else {
      const target='https://cafe.naver.com/ca-fe/cafes/'+input.clubId+'/menus/'+input.menuId+'/articles/write?boardType=L';
      if((await page.url())!==target)await page.goto(target);
    }
    await page.waitForSelector('textarea.textarea_input',{timeout:15000});
    if(document.presentation?.boardName){
      const name=document.presentation.boardName;
      const current=await page.evaluate(()=>document.querySelector('.FormSelectButton .button')?.innerText.trim());
      if(current!==name){
        const expanded=await page.evaluate(()=>document.querySelector('.FormSelectButton .button')?.getAttribute('aria-expanded')==='true');
        if(!expanded)await page.click('.FormSelectButton .button >> nth=0',{label:'choose matching category board'});
        const selector='loc=role:button[name='+JSON.stringify(name)+']';
        await page.waitForSelector(selector,{state:'visible',timeout:10000});
        await page.click(selector,{label:'select article category'});
        await page.waitForFunction(name=>document.querySelector('.FormSelectButton .button')?.innerText.trim()===name,name,{timeout:10000});
      }
    }
    await page.evaluate(()=>document.querySelector('.se-text-paragraph')?.scrollIntoView({block:'center'}));
    await page.click('.se-text-paragraph >> nth=0',{label:'replace article body'});
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.paste({text:expected(document).join('\n\n'),html:input.html});
    await page.waitForFunction(()=>document.querySelector('.se-components-wrap')?.innerText.length>100,undefined,{timeout:10000});
    // Commit the controlled title through actual keyboard input after the
    // rich-text paste, then independently read both title and complete body.
    await page.evaluate(()=>document.querySelector('textarea.textarea_input')?.scrollIntoView({block:'center'}));
    await page.click('textarea.textarea_input',{label:'enter reviewed article title'});
    await page.keyboard.press('ControlOrMeta+A');
    await page.keyboard.insertText(document.title);
    await page.keyboard.press('Tab');
    const staged=await editor(page);check(staged,document,staged.title);
    const stageHash=hash(staged);
    await emit(folder,'stage-evidence.json',{status:'staged',url,stageHash,observed:staged,checkedAt:new Date().toISOString()});
    await emit(folder,'intent.json',{...previous,status:'staged',url,documentSha256:input.documentSha256,stageHash,space:input.space,page:input.page,stagedAt:new Date().toISOString()});
    console.log({status:'staged',url,paragraphs:staged.paragraphs.length,tables:staged.tables.length});
    return;
  }
  if(mode==='submit'){
    const intent=JSON.parse(await fs.readFile(folder+'/intent.json','utf8'));
    const expectedUrl=url?url+'/modify':'https://cafe.naver.com/ca-fe/cafes/'+input.clubId+'/menus/'+input.menuId+'/articles/write?boardType=L';
    if((await page.url())!==expectedUrl||intent.space!==input.space||intent.page!==input.page||intent.status!=='submitting')throw Error('Wrong editor or write intent');
    const staged=await editor(page);check(staged,document,staged.title);
    if(hash(staged)!==intent.stageHash)throw Error('Editor changed since stage');
    await page.click('loc=role:button[name="등록"]',{label:'save reviewed cafe article'});
    await page.waitForFunction(()=>!location.pathname.endsWith('/modify')&&!location.pathname.endsWith('/write'),undefined,{timeout:20000});
    const submittedUrl=await page.url();
    // Naver may return an encoded legacy iframe URL. Verify the exact canonical
    // article below instead of accepting/rejecting that redirect as a receipt.
    await emit(folder,'submit-evidence.json',{status:'submitted',url:url||submittedUrl,observedAt:new Date().toISOString()});
    // Separate navigation: the editor response alone is not verification.
    await page.goto(url||submittedUrl);const observed=await article(page);check(observed,document,observed.title);
    const status=url?'verified_updated':'verified_published';
    const evidence={status,url:url||submittedUrl,documentSha256:input.documentSha256,observed,checkedAt:new Date().toISOString()};
    await emit(folder,'public-evidence.json',evidence);await emit(folder,'submit-evidence.json',evidence);
    await emit(folder,'intent.json',{...intent,status,url:evidence.url,verifiedAt:evidence.checkedAt});
    console.log({status,url:evidence.url,paragraphs:observed.paragraphs.length,tables:observed.tables.length});
    return;
  }
  if(mode==='verify'){
    const intent=JSON.parse(await fs.readFile(folder+'/intent.json','utf8'));
    if(!url||intent.url!==url||intent.documentSha256!==input.documentSha256)throw Error('Exact existing write identity required');
    await page.goto(url);const observed=await article(page);check(observed,document,observed.title);
    const evidence={status:'verified_updated',url,documentSha256:input.documentSha256,observed,checkedAt:new Date().toISOString()};
    await emit(folder,'public-evidence.json',evidence);await emit(folder,'verify-evidence.json',evidence);
    await emit(folder,'intent.json',{...intent,status:evidence.status,verifiedAt:evidence.checkedAt});
    console.log({status:evidence.status,url,paragraphs:observed.paragraphs.length,tables:observed.tables.length});return;
  }
  throw Error('Unknown browser operation');
}
