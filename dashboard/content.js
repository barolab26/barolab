/* Read-only article maintenance queue from independent index/search evidence. */
(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  if (!$('content-rows')) return;
  const PAGE_SIZE = 15;
  const labels = {
    all: '전체 공개 글',
    not_indexed: '미색인 확인 · 원인 점검',
    opportunity: '상승 후보 (11~50위·100위)',
    top: '평균 10위 이내 · 유지',
    deep: '평균 100위 밖 · 재검토',
    indexed_no_report: '색인 확인 · 실적 미관측',
    unknown: '개별 색인 검사 대기'
  };
  const numbers = value => Number(value).toLocaleString('ko-KR');
  const decoded = value => { try { return decodeURI(value); } catch (_) { return value; } };
  const text = (parent, tag, value, className='') => {
    const element = document.createElement(tag);element.textContent = value;
    if (className) element.className = className;
    parent.appendChild(element);return element;
  };
  let data = {rows:[], counts:{}}, page = 0;
  const initialBucket=new URLSearchParams(location.search).get('bucket');
  if(Object.hasOwn(labels,initialBucket) || initialBucket==='inspection_pending') $('content-bucket').value=initialBucket;
  function render() {
    const selected = $('content-domain').value, bucket = $('content-bucket').value;
    const query = $('content-query').value.trim().toLocaleLowerCase();
    for(const button of $('content-counts').querySelectorAll('button')) {
      const btnBucket = button.dataset.bucket;
      const isPressed = btnBucket === bucket || (bucket === 'inspection_pending' && btnBucket === 'unknown');
      button.setAttribute('aria-pressed', String(isPressed));
      button.classList.toggle('active', isPressed);
    }
    const rows = data.rows.filter(r => (selected === 'all' || r.domain === selected) &&
      (bucket === 'all' || (bucket === 'inspection_pending' ? r.index === 'unknown' : r.bucket === bucket)) && decoded(r.url).toLocaleLowerCase().includes(query));
    const order = {not_indexed:0,deep:1,opportunity:2,top:3,indexed_no_report:4,unknown:5};
    rows.sort((a,b)=>order[a.bucket]-order[b.bucket] || (b.search?.impressions || 0)-(a.search?.impressions || 0) || a.url.localeCompare(b.url));
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));page=Math.min(page,pages-1);
    $('content-result-count').textContent = `조건에 맞는 글 ${numbers(rows.length)}개 · 페이지당 ${PAGE_SIZE}개 표시`;
    $('content-page').textContent = `${page+1} / ${pages}`;
    $('content-prev').disabled = page === 0;$('content-next').disabled = page === pages-1;
    const body = $('content-rows');body.replaceChildren();
    for (const row of rows.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE)) {
      const tr=document.createElement('tr'), title=document.createElement('td');
      const link=text(title,'a',decoded(new URL(row.url).pathname).slice(1) || row.domain);
      link.href=row.url;link.target='_blank';link.rel='noopener noreferrer';
      text(title,'small',`${row.domain}${row.inventoryStale?' · 글 목록 재확인 필요':''}`);tr.appendChild(title);
      const requestCell = (request) => {
        const cell=document.createElement('td'), status=request?.status || 'unknown';
        const names={requested:'요청 접수',request_received:'수집 요청 접수',reserved:'제출 결과 미확인',unknown:'미확인',failed:'요청 실패',blocked:'요청 보류'};
        text(cell,'strong',names[status] || '접수 미확인');
        if(request?.at) text(cell,'small',new Date(request.at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}));
        text(cell,'small','요청 접수는 색인 완료가 아닙니다');tr.appendChild(cell);return cell;
      };
      const naverRequest=requestCell(row.naverRequest);
      const protocol=row.indexNowRequest;
      if(protocol && protocol.status!=='unknown') {
        const accepted=['ping_accepted','accepted_pending_key_check'].includes(protocol.status);
        text(naverRequest,'small',`IndexNow 프로토콜: ${accepted?'접수':'접수 미확인'} · 서치어드바이저 접수와 별도`);
        if(protocol.at) text(naverRequest,'small',new Date(protocol.at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}));
      }
      const naver=document.createElement('td');
      text(naver,'strong',row.naverIndex==='indexed'?'색인 확인':row.naverIndex==='not_indexed'?'미색인 확인':'미확인');
      text(naver,'small',row.naverInspectionAt?new Date(row.naverInspectionAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}):'개별 URL 색인 검사 근거 없음');tr.appendChild(naver);
      requestCell(row.googleRequest);
      const index=document.createElement('td');
      text(index,'strong',row.index==='indexed'?'색인 확인':row.index==='not_indexed'?'미색인 확인':'미확인',row.index==='not_indexed'?'content-warning':'');
      if(row.inspectionAt) text(index,'small',`${row.inspectionStale?'이전 검사: ':'검사: '}${new Date(row.inspectionAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})}`);
      if(row.index==='unknown' && row.inspectionPendingReason) text(index,'small',row.inspectionPendingReason);
      if(row.index==='unknown' && row.inspectionAttemptAt) text(index,'small',`최근 검사 시도: ${new Date(row.inspectionAttemptAt).toLocaleString('ko-KR',{timeZone:'Asia/Seoul'})}`);
      if(row.coverageState) text(index,'small',row.coverageState);
      if(row.googleCanonical) text(index,'small',`Google 대표 URL: ${row.googleCanonical}`);
      if(row.requestOutcome==='requested') text(index,'small','색인 요청 접수 · 완료 미확인');
      tr.appendChild(index);
      const dual=document.createElement('td');
      const both=row.index==='indexed' && row.naverIndex==='indexed';
      text(dual,'strong',both?'양사 색인 확인':'양사 확인 대기',both?'status-badge':'');tr.appendChild(dual);
      const performance=document.createElement('td');
      if(row.search){
        const s=row.search;
        text(performance,'strong',`평균 ${Number(s.position).toFixed(1)}위`);
        text(performance,'small',`노출 ${numbers(s.impressions)} · 클릭 ${numbers(s.clicks)}${s.impressions<10?' · 적은 표본':''}`);
        text(performance,'small',`${row.searchStart} ~ ${row.searchEnd} (PT)`);
        if(row.index==='unknown') text(performance,'small','기간 내 검색 관측 · 현재 색인 미확인');
      } else text(performance,'small',row.ambiguousPage?'여러 대표 주소 행 · 개별 확인 필요':row.pageReportAvailable?'공개 보고서에 해당 글 행 없음':'글별 실적 미수집');
      tr.appendChild(performance);
      const action=document.createElement('td');text(action,'strong',row.action);text(action,'small',row.explanation);tr.appendChild(action);body.appendChild(tr);
    }
    if(!rows.length){const tr=document.createElement('tr');const td=text(tr,'td','조건에 맞는 글 없음');td.colSpan=8;body.appendChild(tr);}
  }
  for(const id of ['content-domain','content-bucket','content-query']) {
    $(id).addEventListener('input',()=>{page=0;render();});
    $(id).addEventListener('change',()=>{page=0;render();});
  }
  $('content-prev').addEventListener('click',()=>{page--;render();});
  $('content-next').addEventListener('click',()=>{page++;render();});
  window.BaroLabContent = {render(next){
    data=next || {rows:[],counts:{}};
    const inspected=data.rows.filter(r=>r.index!=='unknown').length;
    const pending = Object.entries(data.inspectionPendingReasons || {}).map(([label,count])=>`${label} ${numbers(count)}개`).join(' · ');
    $('content-coverage').textContent=`공개 글 ${numbers(data.inventoryTotal || 0)}개 · 개별 색인 확인 ${numbers(inspected)}/${numbers(data.inventoryTotal || 0)}개 · 도메인 ${data.inventoryDomains || 0}/${data.expectedDomains || 16}개`;
    if (pending) $('content-coverage').title = `${pending} · 미확인은 미색인 판정이 아닙니다.`;
    const domain=$('content-domain'),previous=domain.value;domain.replaceChildren();
    const all=text(domain,'option','전체 CF 도메인');all.value='all';
    for(const name of [...new Set(data.rows.map(r=>r.domain))].sort()) text(domain,'option',name).value=name;
    if([...domain.options].some(o=>o.value===previous))domain.value=previous;
    const cards=$('content-counts');cards.replaceChildren();
    for(const [key,label] of Object.entries(labels)){
      const button=text(cards,'button','');button.type='button';
      button.dataset.bucket=key;
      const countVal = key === 'all' ? (data.rows?.length || data.inventoryTotal || 0) : (data.counts[key] || 0);
      text(button,'span',label);text(button,'strong',`${numbers(countVal)}개`);
      if(['top','opportunity','deep'].includes(key)) text(button,'span',`노출 10회 미만 ${numbers(data.rows.filter(r=>r.bucket===key&&r.search?.impressions<10).length)}개 포함`);
      button.addEventListener('click',()=>{
        const bucketSelect = $('content-bucket');
        if (bucketSelect) {
          bucketSelect.value = key;
          bucketSelect.dispatchEvent(new Event('change'));
        }
      });
    }
    render();
  },failed(){ $('content-coverage').textContent='관리 목록 조회 실패 · 화면의 값은 이전 조회 결과입니다.'; }};
})();
