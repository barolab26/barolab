/* Fixed EGO operations for editorial_images.py. No model/page strings are code.
 * Every network request/redirect is checked before release; cookies/auth stripped.
 * No claimTaskSpace, recovery retries, form actions, submissions or new profiles.
 */
import {readFile} from 'node:fs/promises';
import {lookup} from 'node:dns/promises';
import {isIP} from 'node:net';
import {createHash} from 'node:crypto';

const hash = text => createHash('sha256').update(text).digest('hex');
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
async function publicURL(raw) {
  if (typeof raw !== 'string' || raw.length > 4096 || /[\s\\\x00-\x1f]/.test(raw)) throw Error('unsafe_navigation');
  const u = new URL(raw);
  if (!['https:', 'http:'].includes(u.protocol) || u.username || u.password || (u.port && !['80','443'].includes(u.port))) throw Error('unsafe_navigation');
  if (/(?:^|[/_?&=.-])(login|signin|logout|checkout|payment|submit|delete|token|session|oauth|account|mypage)(?:$|[/_?&=.-])/i.test(u.pathname+'?'+u.search)) throw Error('unsafe_navigation');
  const host = u.hostname.replace(/^\[|\]$/g, '');
  if (/^(localhost)$|\.(localhost|local|internal)$/i.test(host)) throw Error('unsafe_navigation');
  const ips = isIP(host) ? [{address:host}] : await lookup(host, {all:true});
  if (!ips.length || ips.some(x => !globalIP(x.address))) throw Error('unsafe_navigation');
  return u.href;
}

// Read-only DOM extraction; region ids refer to this exact observed viewport.
const observe = () => {
  const text = (document.body?.innerText || '').slice(0, 24000);
  const visible = e => { const r=e.getBoundingClientRect(); return r.width >= 80 && r.height >= 80 && r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight; };
  const regions = [...document.querySelectorAll('figure,img,table,article,main,section,[role=main]')]
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
    let bottom=r.bottom,excerpt=h.innerText;
    for(let sibling=h.nextElementSibling,n=0;sibling&&n<8;sibling=sibling.nextElementSibling,n++){
      if(/^H[1-6]$/.test(sibling.tagName))break;
      if(/^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT)$/.test(sibling.tagName) || !rendered(sibling))continue;
      const sr=sibling.getBoundingClientRect();
      if(sr.top>=innerHeight)break;
      bottom=Math.max(bottom,sr.bottom);excerpt+='\n'+(sibling.innerText||'');
    }
    bottom=Math.min(innerHeight,Math.max(r.bottom+100,bottom),r.top+900);
    regions.push({id:regions.length,tag:'EXCERPT',text:excerpt.slice(0,3000),credit:'',
      clip:{x:r.left,y:r.top,width:Math.min(r.width,innerWidth-r.left),height:bottom-r.top}});
  }
  const links=[...document.querySelectorAll('a[href]')].map(a=>({url:a.href,title:(a.innerText||'').trim().slice(0,500)}))
    .filter(x=>x.title && /^https?:/.test(x.url)).slice(0,120);
  const sensitive = !!document.querySelector('input[type=password],input[autocomplete="cc-number"],input[autocomplete="one-time-code"]');
  return {url:location.href,title:document.title,text,regions,links,sensitive,scroll:{x:scrollX,y:scrollY},viewport:{width:innerWidth,height:innerHeight}};
};

export async function run(requestFile) {
  let space;
  const eventMethods = {};
  try {
    const input=JSON.parse(await readFile(new URL(requestFile),'utf8'));
    if (!['observe','inspect','scroll','capture','finish'].includes(input.op)) throw Error('invalid_operation');
    const task=await taskSpace(input.space ?? input.name);
    space=task.spaceId;
    if (task.ownership !== 'agent') throw Error('user_takeover');
    if (input.op === 'finish') {
      const closure=await task.finish({keep:[]});
      console.log('EDITORIAL_JSON:'+JSON.stringify({ok:true,space,closure}));
      return;
    }
    const page=task.page('p1');
    const network=[];
    await page.cdp('Network.enable');
    await page.cdp('Network.setBypassServiceWorker',{bypass:true});
    await page.cdp('Network.setCacheDisabled',{cacheDisabled:true});
    await page.cdp('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
    await page.cdp('Network.setBlockedURLs',{urls:[]});
    async function pump(requireNavigation=false, sameDocumentTarget=null) {
      let domReady=!requireNavigation;
      const until=Date.now()+25000;
      let requests=0;
      while (true) {
        if (Date.now()>until || requests>180) throw Error('network_budget_exhausted');
        const events=await page.events();
        for (const event of events) {
          eventMethods[event.method]=(eventMethods[event.method]||0)+1;
          if (event.method === 'Page.domContentEventFired') domReady=true;
          if (event.method !== 'Fetch.requestPaused') continue;
          const p=event.params;
          requests++;
          try {
            if (p.request.method !== 'GET' || p.request.postData) throw Error('unsafe_navigation');
            await publicURL(p.request.url);
            const headers=Object.entries(p.request.headers).filter(([k])=>! /^(cookie|authorization|proxy-authorization|referer)$/i.test(k)).map(([name,value])=>({name,value:String(value)}));
            await page.cdp('Fetch.continueRequest',{requestId:p.requestId,headers});
            if (p.resourceType === 'Document') network.push({url:p.request.url,method:'GET',credentials:'omitted'});
          } catch (error) {
            await page.cdp('Fetch.failRequest',{requestId:p.requestId,errorReason:'BlockedByClient'});
            if (p.resourceType === 'Document') throw Error('unsafe_navigation');
          }
        }
        if (domReady && (!sameDocumentTarget || await page.url()===sameDocumentTarget) && await page.evaluate(()=>document.readyState!=='loading' && (!document.fonts||document.fonts.status==='loaded') &&
          [...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight;}).every(i=>i.complete))) return;
        await new Promise(resolve=>setTimeout(resolve,30));
      }
    }
    let output;
    if (['observe','inspect','scroll'].includes(input.op)) {
      await publicURL(input.url);
      if (input.op === 'observe') {
        await page.cdp('Page.enable');
        await page.events();
        const before=await page.url();
        const sameDocument=before!==input.url && before.split('#')[0]===input.url.split('#')[0];
        // goto waits inside EGO's per-page command queue, preventing the host
        // from servicing Fetch pauses. Fixed read-only navigation returns first;
        // all resulting requests/redirects still pass the public-content gate.
        await page.evaluate(url=>{setTimeout(()=>location.assign(url),0);return true;},input.url);
        await pump(!sameDocument,sameDocument?input.url:null);
      } else if(input.op === 'scroll') {
        const before=await page.url();
        await publicURL(before);
        await page.mouse.move(480,420,{label:'inspect source below'});
        await page.mouse.wheel(0,540,{label:'inspect source below'});
        await pump();
        if (await page.url() !== before) throw Error('source_changed');
      } else if(await page.url()!==input.url) {
        throw Error('source_changed');
      }
      await publicURL(await page.url());
      // Background TaskSpaces may throttle requestAnimationFrame. Observe actual
      // geometry from the host instead. Search links need no screenshot region.
      let previous='',steady=input.search?3:0,stableSince=Date.now();
      const layoutDeadline=Date.now()+5000;
      while(!input.search && (steady<3 || Date.now()-stableSince<250) && Date.now()<layoutDeadline){
        const state=JSON.stringify(await page.evaluate(()=>[scrollX,scrollY,
          ...[...document.querySelectorAll('h1,h2,h3,figure,img,main')].slice(0,60).map(e=>{
            const r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height];
          })]));
        if(state===previous)steady++;else {steady=0;stableSince=Date.now();}
        previous=state;
        if(steady<3)await new Promise(resolve=>setTimeout(resolve,50));
      }
      if(steady<3)throw Error('source_layout_unstable');
      output=await page.evaluate(observe);
      if (output.sensitive) throw Error('private_page');
      output.text_sha256=hash(output.text);
      if (input.screenshot) await page.screenshot({path:input.screenshot,fullPage:false});
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
      await page.screenshot({path:input.screenshot,clip:documentClip});
      output={url,region,document_clip:documentClip,scroll:current.scroll};
    }
    // Freeze networking between rounds, including the model's decision time.
    await page.cdp('Network.setBlockedURLs',{urls:['*']});
    await page.cdp('Fetch.disable');
    console.log('EDITORIAL_JSON:'+JSON.stringify({ok:true,space,public_only:true,network,...output}));
  } catch (error) {
    const raw=String(error);
    const reason=/control|inactive|unassigned|ownership|takeover|not_owned|TAKEN|STOPPED/i.test(raw)?'user_takeover':/unsafe_navigation/.test(raw)?'unsafe_navigation':/source_changed/.test(raw)?'source_changed':'browser_held';
    // No page action/finish/claim after an error or user takeover.
    console.log('EDITORIAL_JSON:'+JSON.stringify({ok:false,space,reason,
      diagnostic:raw.replace(/https?:\/\/\S+/g,'[public-url]').slice(0,500),eventMethods}));
  }
}
