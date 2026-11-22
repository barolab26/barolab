/* Fixed EGO operations for editorial_images.py. No model/page strings are code.
 * Every network request/redirect is checked before release; cookies/auth stripped.
 * No claimTaskSpace, recovery retries, form actions, submissions or new profiles.
 */
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {dirname} from 'node:path';
import {lookup} from 'node:dns/promises';
import {isIP} from 'node:net';
import {createHash} from 'node:crypto';

const hash = text => createHash('sha256').update(text).digest('hex');
export function knownPublicNewsAlert(error,targetURL,mainURL) {
  return targetURL==='https://www.hyundaimotorgroup.com/ko/news/genesis-gv90-special-exhibition'&&
    mainURL===targetURL&&/PageDialogOpenedError/.test(String(error))&&
    /JavaScript alert dialog \("undefined"\)/.test(String(error));
}
export function dismissSujiOperatingNotice() {
  // Observed public information dialog only; no preference checkboxes or forms.
  for(const dialog of document.querySelectorAll('[role=dialog]')) {
    const r=dialog.getBoundingClientRect(),text=dialog.innerText||'';
    if(!r.width||!r.height||!text.includes('운영 안내')||!text.includes('주말 주차 안내')||
       dialog.querySelector('input:not([type=checkbox]),form'))continue;
    const close=dialog.querySelector('button.cta-button.type-line');
    if(close?.type==='button'&&close.innerText.trim()==='닫기'){close.click();return true;}
  }
  return false;
}
export function revealJongnoRefundNotice() {
  // These three observed information notices cover the refund-policy notice.
  // Use only their confirmation buttons, never the preference or refund form.
  let closed=0;
  for(const [id,word] of [['150','수거 시간'],['149','사업장'],['151','관외']]) {
    const button=document.getElementById('btnConfirm_'+id);
    if(!button||button.form||button.innerText.trim()!=='확인')continue;
    let box=button.parentElement;
    for(let depth=0;box&&depth<5;depth++,box=box.parentElement) {
      const text=(box.innerText||'').replace(/\s+/g,' ').trim();
      if(text.includes(word)&&text.length<2000&&!box.querySelector('form,input,textarea')) {
        button.click();closed++;break;
      }
    }
  }
  return closed;
}
export function publicScreenInitialization(p,parentURL,mainFrameId) {
  // Bokjiro loads its PUBLIC calculator iframe through a navigation POST,
  // carrying only screen/menu metadata. This is not an application or a
  // calculation submission. Keep every other POST and all user data blocked.
  try {
    const parent=new URL(parentURL),u=new URL(p.request.url),body=p.request.postData||'';
    const keys=[...new URLSearchParams(body).keys()],allowed=new Set(['menuParam','curScrId','pageParam','befScrId','scrGid']);
    return p.resourceType==='Document'&&p.frameId!==mainFrameId&&!!mainFrameId&&
      p.request.method==='POST'&&parent.origin==='https://www.bokjiro.go.kr'&&u.origin===parent.origin&&
      parent.pathname==='/ssis-tbu/twatbz/mkclAsis/mkclInsertBspnPage.do'&&
      u.pathname==='/ssis-tbu/twatbz/mkclAsis/mkclInsertBspnEmp.do'&&!u.search&&
      body.length>0&&body.length<=4000&&keys.includes('curScrId')&&keys.every(k=>allowed.has(k));
  }catch{return false;}
}
function globalIP(ip) {
  if (isIP(ip) === 4) {
    const [a,b,c] = ip.split('.').map(Number);
    return !(a === 0 || a === 10 || a === 127 || a >= 224 ||
      (a === 100 && b >= 64 && b <= 127) || (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b <= 31) || (a === 192 && (b === 168 || b === 0 || (b === 88 && c === 99) || (b === 0 && c === 2))) ||
      (a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100))) ||
      (a === 203 && b === 0 && c === 113));
  }
  // Conservative IPv6 global unicast only; translation/tunnelling and docs held.
  return isIP(ip) === 6 && /^[23]/i.test(ip) && !/^2001:(?:0*0:|0*2:|db8:|0*10:|0*20:)/i.test(ip) && !/^2002:/i.test(ip);
}
const dnsCache = new Map();
async function publicURL(raw) {
  if (typeof raw !== 'string' || raw.length > 4096 || /[\s\\\x00-\x1f]/.test(raw)) throw Error('unsafe_navigation');
  const u = new URL(raw);
  if (!['https:', 'http:'].includes(u.protocol) || u.username || u.password || (u.port && !['80','443'].includes(u.port))) throw Error('unsafe_navigation');
  if (/(?:^|[/_?&=.-])(login|signin|logout|checkout|payment|submit|delete|token|session|oauth|account|mypage)(?:$|[/_?&=.-])/i.test(u.pathname+'?'+u.search)) throw Error('unsafe_navigation');
  const host = u.hostname.replace(/^\[|\]$/g, '');
  if (/^(localhost)$|\.(localhost|local|internal)$/i.test(host)) throw Error('unsafe_navigation');
  let ips = dnsCache.get(host);
  if (!ips) {
    ips = isIP(host) ? [{address:host}] : await Promise.race([
      lookup(host, {all:true}),
      new Promise((_, reject) => setTimeout(() => reject(Error('dns_timeout')), 2500))
    ]);
    dnsCache.set(host, ips);
  }
  if (!ips.length || ips.some(x => !globalIP(x.address))) throw Error('unsafe_navigation');
  return u.href;
}

// Read-only DOM extraction; region ids refer to this exact observed viewport.
const observe = () => {
  let text = (document.body?.innerText || '').slice(0, 24000);
  let frameSensitive = false;
  const visible = e => { const r=e.getBoundingClientRect(); return r.width >= 80 && r.height >= 80 && r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; };
  const regions = [...document.querySelectorAll('figure,img,table,td,th,article,main,section,[role=main]')]
    .filter(visible).slice(0,40).map((e,id) => {
      const r=e.getBoundingClientRect();
      return {id,tag:e.tagName,text:(e.innerText||e.alt||'').slice(0,3000),
        credit:(e.closest('figure')?.innerText||'').slice(0,1500),
        clip:{x:r.left,y:r.top,width:r.width,height:r.height}};
    });
  // A bounded heading+following-text excerpt is a useful public documentation
  // region when the main element itself extends below the viewport.
  const rendered = e => {
    const r=e.getBoundingClientRect(),style=getComputedStyle(e);
    if (!(r.width>0 && r.height>0) || e.closest('nav,[role=navigation]') ||
      style.display==='none' || ['hidden','collapse'].includes(style.visibility) || style.opacity==='0') return false;
    // Opacity is not inherited: a transparent ancestor still hides its children.
    for(let parent=e.parentElement;parent;parent=parent.parentElement) {
      const inherited=getComputedStyle(parent);
      if(inherited.display==='none' || inherited.opacity==='0')return false;
    }
    return true;
  };
  const headings=[...document.querySelectorAll('h1,h2,h3')].filter(h=>{
    const r=h.getBoundingClientRect();
    return rendered(h) && (h.innerText||'').trim() && r.left>=0 && r.top>=0 &&
      r.top<=innerHeight-100 && Math.min(r.width,innerWidth-r.left)>=80;
  }).slice(0,12);
  for (const h of headings) {
    const r=h.getBoundingClientRect();
    let right=r.right, bottom=r.bottom, excerpt=h.innerText;
    let startEl = h.nextElementSibling ? h : (h.parentElement && !h.parentElement.nextElementSibling ? h.parentElement.parentElement : h.parentElement);
    for(let sibling=(startEl||h).nextElementSibling,n=0;sibling&&n<8;sibling=sibling.nextElementSibling,n++){
      if(/^H[1-6]$/.test(sibling.tagName))break;
      if(/^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT)$/.test(sibling.tagName) || !rendered(sibling))continue;
      const sr=sibling.getBoundingClientRect();
      if(sr.top>=innerHeight)break;
      if(sr.bottom > innerHeight - 6 && bottom - r.top >= 260) break;
      if(sr.right <= innerWidth) right = Math.max(right, sr.right);
      bottom=Math.max(bottom,sr.bottom);excerpt+='\n'+(sibling.innerText||'');
    }
    bottom=Math.min(innerHeight,Math.max(r.bottom+100,bottom),r.top+900);
    regions.push({id:regions.length,tag:'EXCERPT',text:excerpt.slice(0,3000),credit:'',
      clip:{x:r.left,y:r.top,width:Math.min(right-r.left,innerWidth-r.left),height:bottom-r.top}});
  }
  // Official guides frequently render formulas/criteria in ordinary div/dl
  // boxes, not semantic tables or headings. Offer their actual visible bounds;
  // the vision selector and independent review still decide relevance.
  for(const e of [...document.querySelectorAll('div,dl,ul,ol,p')]) {
    if(regions.length>=64)break;
    if(!visible(e)||!rendered(e)||e.closest('nav,header,footer,[role=navigation]'))continue;
    const r=e.getBoundingClientRect(),t=(e.innerText||'').trim();
    if(r.width<300||r.width>1280||r.height>800||t.length<45||t.length>3000||e.children.length>12)continue;
    if(regions.some(x=>Math.abs(x.clip.x-r.left)<2&&Math.abs(x.clip.y-r.top)<2&&Math.abs(x.clip.width-r.width)<2&&Math.abs(x.clip.height-r.height)<2))continue;
    regions.push({id:regions.length,tag:'CONTENT',text:t,credit:'',
      clip:{x:r.left,y:r.top,width:r.width,height:r.height}});
  }
  // Public FAQ answers often consist of short paragraphs. Group actual adjacent
  // paragraphs so a complete rule and its qualification form a legible crop.
  for(const e of [...document.querySelectorAll('p,li')]) {
    if(regions.length>=80)break;
    const r=e.getBoundingClientRect(),t=(e.innerText||'').trim();
    if(!rendered(e)||e.closest('nav,header,footer,[role=navigation]')||r.width<300||r.height<20||r.height>=80||
       r.left<0||r.top<0||r.right>innerWidth||r.bottom>innerHeight||t.length<45||t.length>1500)continue;
    let bottom=r.bottom,right=r.right,excerpt=t;
    for(let next=e.nextElementSibling,n=0;next&&n<2;next=next.nextElementSibling,n++) {
      const nr=next.getBoundingClientRect();
      if(next.tagName!==e.tagName||!rendered(next)||nr.top-bottom>100||nr.right>innerWidth||nr.bottom>innerHeight||nr.bottom-r.top>400)break;
      bottom=nr.bottom;right=Math.max(right,nr.right);excerpt+='\n'+(next.innerText||'');
      if(bottom-r.top>=80)break;
    }
    bottom=Math.max(bottom,r.top+80);
    if(bottom>innerHeight)continue;
    regions.push({id:regions.length,tag:'PARAGRAPH_EXCERPT',text:excerpt.slice(0,3000),credit:'',
      clip:{x:r.left,y:r.top,width:right-r.left,height:bottom-r.top}});
  }
  // Older official FAQ templates use text nodes separated by BR tags instead
  // of P elements. DOM Ranges expose those actual rendered paragraphs.
  for(const e of [...document.querySelectorAll('div,p')]) {
    if(regions.length>=96)break;
    if(!rendered(e)||e.closest('nav,header,footer,[role=navigation]')||
       [...e.children].filter(n=>n.tagName==='BR').length<2)continue;
    const blocks=[];let start=null,last=null,breaks=0;
    for(const node of e.childNodes) {
      if(node.nodeType===1&&node.tagName==='BR') {
        if(++breaks>=2&&start&&last){blocks.push({start,last});start=last=null;}
      } else if((node.textContent||'').trim()) {start??=node;last=node;breaks=0;}
    }
    if(start&&last)blocks.push({start,last});
    for(let i=0;i<Math.min(blocks.length,24)&&regions.length<96;i++) {
      const range=document.createRange();range.setStartBefore(blocks[i].start);range.setEndAfter(blocks[i].last);
      let r=range.getBoundingClientRect(),text=range.toString().trim();
      if(text.length<45||text.length>1500)continue;
      if(r.height<80&&blocks[i+1]){range.setEndAfter(blocks[i+1].last);r=range.getBoundingClientRect();text=range.toString().trim();}
      const height=Math.max(80,r.height);
      if(r.width<300||r.width>1280||r.left<0||r.top<0||r.right>innerWidth||r.top+height>innerHeight||height>500)continue;
      regions.push({id:regions.length,tag:'BR_PARAGRAPH_EXCERPT',text,credit:'',
        clip:{x:r.left,y:r.top,width:r.width,height}});
    }
  }
  const frameEvidence=[];
  for(const frame of [...document.querySelectorAll('iframe')].slice(0,8)) {
    // Same-origin frames only. Never bypass frame access controls or use a
    // private/authenticated frame as public source evidence.
    let doc;try{doc=frame.contentDocument;if(!doc?.body)continue;}catch{continue;}
    const fr=frame.getBoundingClientRect();
    if(fr.right<=0||fr.bottom<=0||fr.left>=innerWidth||fr.top>=innerHeight)continue;
    const ft=(doc.body.innerText||'').slice(0,24000);
    text+='\n'+ft;
    frameEvidence.push({url:doc.URL,text:ft});
    if([...doc.querySelectorAll('input[type=password],input[autocomplete="cc-number"],input[autocomplete="one-time-code"]')].some(e=>e.getBoundingClientRect().height>0))frameSensitive=true;
    for(const e of [...doc.querySelectorAll('figure,img,table,section,div,dl')]) {
      if(regions.length>=96)break;
      const r=e.getBoundingClientRect(),x=fr.left+r.left,y=fr.top+r.top;
      const t=(e.innerText||e.alt||'').trim(),style=doc.defaultView.getComputedStyle(e);
      if(style.display==='none'||style.visibility==='hidden'||style.opacity==='0'||r.width<200||r.height<80||r.width>1280||r.height>850||x<0||y<0||x+r.width>innerWidth||y+r.height>innerHeight||t.length<20||t.length>4000)continue;
      if(e.closest('nav,header,footer,[role=navigation]'))continue;
      regions.push({id:regions.length,tag:'FRAME_'+e.tagName,text:t,credit:'',
        clip:{x,y,width:r.width,height:r.height}});
    }
  }
  const links=[...document.querySelectorAll('a[href]')].map(a=>({url:a.href,title:(a.innerText||'').trim().slice(0,500)}))
    .filter(x=>x.title && /^https?:/.test(x.url)).slice(0,120);
  const pwInput = document.querySelector('input[type=password],input[autocomplete="cc-number"],input[autocomplete="one-time-code"]');
  const sensitive = frameSensitive || !!(pwInput && rendered(pwInput));
  return {url:location.href,title:document.title,text,regions,links,sensitive,frameEvidence,scroll:{x:(document.scrollingElement?.scrollLeft ?? (typeof scrollX==='number'?scrollX:0)),y:(document.scrollingElement?.scrollTop ?? (typeof scrollY==='number'?scrollY:0))},viewport:{width:innerWidth,height:innerHeight}};
};

async function screenshot(page,path,clip) {
  try {
    await page.screenshot({path,...(clip?{clip}:{fullPage:false})});
    return 'ego-screenshot';
  } catch(error) {
    // EGO 0.6.2 can reject viewport capture with "Invalid parameters" on
    // otherwise healthy pages. Capture the same observed pixels via Chrome;
    // never edit the page or synthesize a replacement image.
    if(!/Invalid parameters/.test(String(error)))throw error;
    const view=await page.evaluate(()=>({x:(document.scrollingElement?.scrollLeft ?? (typeof scrollX==='number'?scrollX:0)),y:(document.scrollingElement?.scrollTop ?? (typeof scrollY==='number'?scrollY:0)),width:document.documentElement.clientWidth,height:innerHeight,dpr:devicePixelRatio}));
    if(view.dpr!==1)throw Error('screenshot_scale_unverified');
    const shot=await page.cdp('Page.captureScreenshot',{format:'png',captureBeyondViewport:false,
      ...(clip?{clip:{...clip,scale:1}}:{})});
    await mkdir(dirname(path),{recursive:true});
    await writeFile(path,Buffer.from(shot.data,'base64'));
    return 'chrome-viewport-capture';
  }
}

export async function run(requestFile) {
  let space;
  let capturePageLabel;
  const eventMethods = {};
  const blockedDocuments=[];
  let phase = "request";
  try {
    const input=JSON.parse(await readFile(new URL(requestFile),'utf8'));
    if (!['observe','inspect','scroll','capture','finish'].includes(input.op)) throw Error('invalid_operation');
    let targetSpace=input.space ?? input.name;
    if(input.work_space_name && input.space==null) {
      const existing=(await listTaskSpaces()).filter(s=>s.name===input.work_space_name);
      if(existing.length!==1)throw Error('working_taskspace_missing_or_ambiguous');
      if(existing[0].ownership!=='agent')throw Error('user_takeover');
      targetSpace=existing[0].id;
    }
    const task=await taskSpace(targetSpace);
    space=task.spaceId;
    if (task.ownership !== 'agent') throw Error('user_takeover');
    if(input.work_space_name && task.name!==input.work_space_name)throw Error('taskspace_changed');
    if (input.op === 'finish') {
      if(input.work_space_name) {
        const tab=(await task.tabs()).find(t=>t.label===input.page_label&&t.openedBy==='agent');
        if(!tab)throw Error('capture_page_missing');
        await task.page(tab.label).close();
        console.log('EDITORIAL_JSON:'+JSON.stringify({ok:true,space,captureTabClosed:true,workingSpacePreserved:true}));
        return;
      }
      const closure=await task.finish({keep:[]});
      console.log('EDITORIAL_JSON:'+JSON.stringify({ok:true,space,closure}));
      return;
    }
    const managed=(await task.tabs()).filter(tab=>tab.label && tab.openedBy==='agent');
    // A diagnosed hung agent Page can be replaced manually inside this same
    // owned space. Never create/claim a space or choose a user tab to recover.
    let selected;
    if(input.page_label) {
      selected=managed.find(t=>t.label===input.page_label);
      if(!selected)throw Error('capture_page_missing');
    } else if(input.work_space_name) {
      const capture=await task.newPage();
      selected={label:capture.label};
    } else {
      if(managed.length!==1)throw Error('taskspace_page_ambiguous');
      selected=managed[0];
    }
    let page=task.page(selected.label),rendererRecovery=null,frameTree;
    capturePageLabel=page.label;
    try {frameTree=await page.cdp('Page.getFrameTree');}
    catch(readError) {
      if(!/timed out.*Page\.getFrameTree|Page\.getFrameTree.*timed out/i.test(String(readError)))throw readError;
      phase='renderer diagnosis';
      try {
        await page.snapshot(); // Read current state before considering recovery.
      } catch(diagnosis) {
        if(!/PageUnresponsiveError/.test(String(diagnosis))||!/renderer is probably hung/.test(String(diagnosis)))throw diagnosis;
        const current=(await task.tabs()).find(t=>t.label===page.label&&t.openedBy==='agent');
        if(!current||task.ownership!=='agent')throw Error('user_takeover');
        if(current.url!=='about:blank')await publicURL(current.url);
        const oldLabel=page.label;
        await page.close();
        page=await task.newPage(); // Same owned TaskSpace, never another space/profile.
        capturePageLabel=page.label;
        rendererRecovery={reason:'confirmed_hung_renderer_after_read_only_probe',oldPage:oldLabel,newPage:page.label,
                          sameTaskspace:space,userTabsClosed:false};
      }
      // One read-only retry; another error is held without further recovery.
      frameTree=await page.cdp('Page.getFrameTree');
    }
    const mainFrameId=frameTree?.frameTree?.frame?.id;
    // Fit common fixed 1200px public-service layouts, including their sidebar.
    // A narrower viewport silently clips the right side before crop selection.
    await page.cdp('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
    let mainURL=await page.url();
    const network=[];
    let publicNewsAlerts=0;
    phase = 'network setup';
    await page.cdp('Network.enable');
    await page.cdp('Network.setBypassServiceWorker',{bypass:true});
    await page.cdp('Network.setCacheDisabled',{cacheDisabled:true});
    await page.cdp('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
    await page.cdp('Network.setBlockedURLs',{urls:[]});
    async function pump(requireNavigation=false, sameDocumentTarget=null) {
      let domReady=!requireNavigation;
      let mainLoaded=!requireNavigation;
      const until=Date.now()+12000;
      let requests=0;
      while (true) {
        if (Date.now()>until || requests>250) {
          if (domReady) return;
          throw Error('network_budget_exhausted');
        }
        const events=await page.events();
        for (const event of events) {
          eventMethods[event.method]=(eventMethods[event.method]||0)+1;
          if(event.method==='Page.javascriptDialogOpening' && event.params?.type==='alert' &&
             event.params?.message==='undefined' &&
             event.params?.url==='https://www.hyundaimotorgroup.com/ko/news/genesis-gv90-special-exhibition' &&
             publicNewsAlerts<2) {
            publicNewsAlerts++;
            await page.dismissDialog();
            continue;
          }
          if (event.method === 'Page.domContentEventFired') domReady=true;
          if (event.method === 'Page.loadEventFired') mainLoaded=true;
          if (event.method !== 'Fetch.requestPaused') continue;
          const p=event.params;
          requests++;
          try {
            const screenInit=publicScreenInitialization(p,mainURL,mainFrameId);
            if (!screenInit && (p.request.method !== 'GET' || p.request.postData)) throw Error('unsafe_navigation');
            if (p.resourceType !== 'Document' && /(^|\.)(googlesyndication|doubleclick|googletagmanager|google-analytics|adservice|coupang|criteo|taboola|dable|widerplanet|kakao\.com\/adfit)\./i.test(new URL(p.request.url).hostname)) {
              throw Error('ad_tracker_skipped');
            }
            await publicURL(p.request.url);
            if(p.resourceType==='Document'&&p.frameId===mainFrameId)mainURL=p.request.url;
            const headers=Object.entries(p.request.headers).filter(([k])=>! /^(cookie|authorization|proxy-authorization|referer)$/i.test(k)).map(([name,value])=>({name,value:String(value)}));
            await page.cdp('Fetch.continueRequest',{requestId:p.requestId,headers});
            if (p.resourceType === 'Document') network.push({url:p.request.url,method:p.request.method,credentials:'omitted',
              ...(screenInit?{purpose:'public_calculator_screen_initialization'}:{})});
          } catch (error) {
            // Fetch.disable ends the previous round's pauses. Buffered events
            // can still arrive afterwards; an already-resolved id has no action
            // left to authorize or retry.
            if(/Invalid InterceptionId|Invalid requestId/i.test(String(error)))continue;
            await page.cdp('Fetch.failRequest',{requestId:p.requestId,errorReason:'BlockedByClient'});
            if (p.resourceType === 'Document') {
              const u=new URL(p.request.url);
              const body=p.request.postData||'';
              let bodyKeys=[];
              try{bodyKeys=body.trim().startsWith('{')?Object.keys(JSON.parse(body)):[...new URLSearchParams(body).keys()];}catch{}
              blockedDocuments.push({method:p.request.method,host:u.hostname,path:u.pathname,reason:String(error),
                bodyKeys:bodyKeys.filter(k=>/^[A-Za-z0-9_.-]{1,80}$/.test(k)).slice(0,30)});
              // Deny tracking/payment/login frames, while retaining the public
              // product/article itself. A forbidden root redirect still fails.
              if(mainFrameId && p.frameId && p.frameId!==mainFrameId)continue;
              throw Error('unsafe_navigation');
            }
          }
        }
        if(domReady && mainLoaded){
          // The high-level evaluate queue waits for navigation, but navigation
          // waits for the Fetch pauses serviced here. Read readiness directly
          // through CDP so the network pump cannot deadlock on its own queue.
          const ready=await page.cdp('Runtime.evaluate',{returnByValue:true,expression:
            `document.readyState==='complete' && (!document.fonts||document.fonts.status==='loaded') &&
             [...document.querySelectorAll('iframe')].every(f=>{try{return !f.src||f.src==='about:blank'||!f.contentDocument||(f.contentDocument.readyState==='complete'&&f.contentDocument.URL!=='about:blank');}catch{return true;}}) &&
             [...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight;}).every(i=>i.complete)`});
          if(ready?.result?.value && (!sameDocumentTarget||mainURL===sameDocumentTarget))return;
        }
        await new Promise(resolve=>setTimeout(resolve,30));
      }
    }
    let output;
    if (['observe','inspect','scroll'].includes(input.op)) {
      await publicURL(input.url);
      if (input.op === 'observe') {
        await page.cdp('Page.enable');
        await page.events();
        let targetUrl = input.url;
        const mNaver = /^https?:\/\/blog\.naver\.com\/([A-Za-z0-9_-]+)\/(\d+)/i.exec(targetUrl);
        if (mNaver) targetUrl = `https://m.blog.naver.com/${mNaver[1]}/${mNaver[2]}`;
        const before=await page.url();
        const sameDocument=before!==targetUrl && before.split('#')[0]===targetUrl.split('#')[0];
        // goto waits inside EGO's per-page command queue, preventing the host
        // from servicing Fetch pauses. Fixed read-only navigation returns first;
        // all resulting requests/redirects still pass the public-content gate.
        if(before!==targetUrl) {
          await page.evaluate(url=>{setTimeout(()=>location.assign(url),0);return true;},targetUrl);
          phase = 'source navigation';
          try {await pump(!sameDocument,sameDocument?targetUrl:null);}
          catch(error) {
            if(!knownPublicNewsAlert(error,targetUrl,mainURL)) {
              throw Error(String(error)+'; sourceTarget='+targetUrl+'; observedMainURL='+mainURL);
            }
            await page.dismissDialog(); // Observed non-transactional public-source alert only.
            await pump(false);
          }
        } else {
          // Reconcile an interrupted read against the already observed source.
          // Reloading the same document discards useful state for no new evidence.
          phase = 'existing source readiness';
          await pump(false);
        }
      } else if(input.op === 'scroll') {
        const before=await page.url();
        await publicURL(before);
        const focused=input.focus_quote && await page.evaluate(quote=>{
          const normalize=s=>(s||'').replace(/\s+/g,' ').trim(),q=normalize(quote);
          if(q.length<8||q.length>500)return false;
          const phrases=[q,...quote.split(/\n+|[.!?]\s+/).map(normalize).filter(s=>s.length>=24)];
          const docs=[document];
          for(const f of document.querySelectorAll('iframe')){try{if(f.contentDocument?.body)docs.push(f.contentDocument);}catch{}}
          const matches=[];
          for(const doc of docs)for(const e of doc.querySelectorAll('p,li,dt,dd,h1,h2,h3,h4,div,td,th,section,figure')){
            const t=normalize(e.innerText),r=e.getBoundingClientRect();
            if(phrases.some(s=>t.includes(s))&&r.width>80&&r.height>0&&!e.closest('nav,header,footer,[role=navigation]'))matches.push({e,n:t.length});
          }
          matches.sort((a,b)=>a.n-b.n);
          if(!matches.length)return false;
          (matches[0].e.closest('figure')||matches[0].e).scrollIntoView({block:'center',behavior:'instant'});
          return true;
        },input.focus_quote);
        if(!focused){
          await page.mouse.move(480,420,{label:'inspect source below'});
          await page.mouse.wheel(0,540,{label:'inspect source below'});
        }
        await pump();
        if (await page.url() !== before) throw Error('source_changed');
      } else if(await page.url()!==input.url) {
        throw Error('source_changed');
      }
      await publicURL(await page.url());
      const sourceURL=new URL(await page.url());
      if(input.op==='observe'&&sourceURL.hostname==='www.genesis.com'&&
         sourceURL.pathname==='/kr/ko/experience/space/genesis-suji.html') {
        await page.evaluate(dismissSujiOperatingNotice);
        await pump();
      }
      if(input.op==='observe'&&sourceURL.hostname==='www.jongno.go.kr'&&
         sourceURL.pathname==='/waste/pc/web/main/main.do') {
        await page.evaluate(revealJongnoRefundNotice);
        await pump();
      }
      // Background TaskSpaces may throttle requestAnimationFrame. Observe actual
      // geometry from the host instead. Search links need no screenshot region.
      let previous='',steady=input.search?3:0,stableSince=Date.now();
      const layoutDeadline=Date.now()+6000;
      while(!input.search && (steady<3 || Date.now()-stableSince<1000) && Date.now()<layoutDeadline){
        await pump();
        const state=JSON.stringify(await page.evaluate(()=>[(document.scrollingElement?.scrollLeft ?? (typeof scrollX==='number'?scrollX:0)),(document.scrollingElement?.scrollTop ?? (typeof scrollY==='number'?scrollY:0)),
          ...[...document.querySelectorAll('h1,h2,h3,figure,img,main')].slice(0,60).map(e=>{
            const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height];
          })]));
        if(state===previous)steady++;else {steady=0;stableSince=Date.now();}
        previous=state;
        if(steady<3)await new Promise(resolve=>setTimeout(resolve,50));
      }
      // The official SAVETAX comparison answer is behind a published FAQ
      // accordion. Open that observed content control, never a refund form.
      if(!input.search && input.op==='observe' && new URL(await page.url()).hostname==='refund.save-tax.co.kr'){
        for(const question of ['홈택스에는 환급액이 없는데 SAVETAX 환급에서는 왜 환급액이 있나요?','예상 환급액과 실제 환급액이 다를 수 있나요?']){
        const closed=await page.evaluate(q=>[...document.querySelectorAll('div[data-framer-name="Desktop-Closed"][tabindex="0"]')]
          .some(e=>(e.querySelector('h3')?.innerText||'').trim()===q),question);
        if(closed){
          // Framer's long sticky section prevents the SDK wheel scroller
          // from reaching this below-fold accordion. Scroll the observed
          // public widget into view before dispatching its real click.
          await page.evaluate(q=>[...document.querySelectorAll('div[data-framer-name="Desktop-Closed"][tabindex="0"]')]
            .find(e=>(e.querySelector('h3')?.innerText||'').trim()===q)?.scrollIntoView({block:'center'}),question);
          await page.click('loc=css:div[data-framer-name="Desktop-Closed"][tabindex="0"]:has-text('+JSON.stringify(question)+')');
          await page.waitForFunction(q=>[...document.querySelectorAll('div[data-framer-name="Desktop-Open"]')]
            .some(e=>(e.querySelector('h3')?.innerText||'').trim()===q&&e.innerText.length>q.length+30),question,{timeout:5000});
          await pump();
          await page.evaluate(()=>{document.scrollingElement.scrollTop=0;});
        }
        }
      }
      // Dismiss the observed Hyundai purchase-consultation promotion through
      // its actual "close window" control. Do not open consultation forms.
      if(!input.search && new URL(await page.url()).hostname==='www.hyundai.com'){
        const close=await page.evaluate(()=>{
          if(!document.body.innerText.includes('특별한 구매혜택 확인과,전문적인 구매상담을 통해'))return null;
          for(const b of document.querySelectorAll('button,a')){
            if((b.innerText||'').trim()!=='창닫기')continue;
            const r=b.getBoundingClientRect();
            if(r.width>0&&r.height>0&&r.left>=0&&r.top>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&getComputedStyle(b).display!=='none')
              return {x:r.x+r.width/2,y:r.y+r.height/2};
          }
          return null;
        });
        if(close){
          await page.mouse.click(close.x,close.y,{label:'close purchase promotion'});
          await pump();
        }
      }
      // Close only an observed recipe-site advertisement through its real
      // dismiss button. Never hide DOM nodes or dismiss login/permission dialogs.
      if(!input.search && /(^|\.)10000recipe\.com$/.test(new URL(await page.url()).hostname)){
        const ad=await page.evaluate(()=>{
          for(const modal of document.querySelectorAll('.modal')){
            const r=modal.getBoundingClientRect();
            if(r.width<=0||r.height<=0||getComputedStyle(modal).display==='none'||!/파워링크/.test(modal.innerText||''))continue;
            const b=modal.querySelector('button.close[data-dismiss="modal"][aria-label="Close"]');
            if(!b)continue;const q=b.getBoundingClientRect();
            if(q.width>0&&q.height>0)return {x:q.x+q.width/2,y:q.y+q.height/2};
          }
          return null;
        });
        if(ad)await page.mouse.click(ad.x,ad.y,{label:'close source advertisement'});
      }
      phase = 'DOM observation';
      output=await page.evaluate(observe);
      if (input.op === 'observe' && input.search) {
        const extLinks = (output.links || []).filter(x => {
          try { return !/(^|\.)(google\.[a-z.]+|gstatic\.com|googleapis\.com|search\.naver\.com)$/i.test(new URL(x.url).hostname); }
          catch { return false; }
        });
        if (extLinks.length === 0) {
          const q = new URL(input.url).searchParams.get('q') || '';
          if (q) {
            const naverSearch = 'https://search.naver.com/search.naver?where=nexearch&query=' + encodeURIComponent(q);
            await publicURL(naverSearch);
            await page.evaluate(url=>{setTimeout(()=>location.assign(url),0);return true;},naverSearch);
            await pump(true, null);
            output = await page.evaluate(observe);
          }
        }
      }
      if (output.sensitive) throw Error('private_page');
      output.text_sha256=hash(output.text);
      phase = 'source screenshot';
      if (input.screenshot) output.captureTransport=await screenshot(page,input.screenshot);
    } else {
      const url=await page.url();
      await publicURL(url);
      if (url !== input.url) throw Error('source_changed');
      const current=await page.evaluate(observe);
      const region=current.regions.find(r=>r.id===input.region.id);
      const same=region && ['id','tag','text','credit'].every(k=>region[k]===input.region[k]) &&
        ['x','y','width','height'].every(k=>region.clip[k]===input.region.clip[k]);
      if (current.sensitive) throw Error('source_changed:privacy');
      if (hash(current.text)!==input.expected_text_sha256) throw Error('source_changed:text');
      if (!same) throw Error('source_changed:region:'+JSON.stringify({expected:input.region.clip,actual:region?.clip,
        changed:['id','tag','text','credit'].filter(k=>region?.[k]!==input.region[k])}));
      const c=region.clip;
      if (![c.x,c.y,c.width,c.height].every(Number.isFinite) || c.x<0 || c.y<0 || c.width<80 || c.height<80) throw Error('invalid_clip');
      // EGO screenshot clip is in document CSS pixels; observed DOM rectangles
      // are viewport CSS pixels, including after a native wheel/anchor scroll.
      const documentClip={...c,x:c.x+current.scroll.x,y:c.y+current.scroll.y};
      await screenshot(page,input.screenshot,documentClip);
      output={url,region,document_clip:documentClip,scroll:current.scroll};
    }
    // Freeze networking between rounds, including the model's decision time.
    phase = 'network freeze';
    await page.cdp('Network.setBlockedURLs',{urls:['*']});
    await page.cdp('Fetch.disable');
    console.log('EDITORIAL_JSON:'+JSON.stringify({ok:true,space,page:page.label,rendererRecovery,public_only:true,network,blockedDocuments,...output}));
  } catch (error) {
    const raw=String(error);
    const reason=/task space not found|working_taskspace_missing_or_ambiguous/i.test(raw)?'taskspace_missing':/PageEvaluationTimeoutError/i.test(raw)?'browser_held':/control|inactive|unassigned|ownership|takeover|not_owned|TAKEN|\bSTOPPED\b/i.test(raw)?'user_takeover':/unsafe_navigation/.test(raw)?'unsafe_navigation':/source_changed/.test(raw)?'source_changed':'browser_held';
    // No page action/finish/claim after an error or user takeover.
    console.log('EDITORIAL_JSON:'+JSON.stringify({ok:false,space,page:capturePageLabel,reason,
      phase, diagnostic:(error.stack || raw).replace(/https?:\/\/\S+/g,'[public-url]').slice(0,500),eventMethods,blockedDocuments}));
  }
}
