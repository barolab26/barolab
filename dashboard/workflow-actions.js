'use strict';
(() => {
  const button = document.getElementById('wf-retry-button');
  const message = document.getElementById('wf-retry-message');
  const requests = new Map();
  let sending = false;
  let shownDomain = '';
  function selected() {
    const status = window.__PIPELINE_STATUS__ || {};
    const today = new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Seoul'}).format(new Date());
    if (status.scheduleDate !== today) return null;
    return typeof CF_SITES !== 'undefined' ? CF_SITES[selectedIndex] : null;
  }
  function render() {
    const site = selected(), job = site && requests.get(site.domain);
    if (site?.domain !== shownDomain) { shownDomain = site?.domain || ''; message.textContent = ''; }
    button.disabled = sending || !site || !['failed','review_required','retry_wait'].includes(site.status) || Boolean(job);
    button.textContent = sending ? '요청 접수 중…' : job ? (job.status === 'running' ? '재실행 진행 중' : '재실행 요청 접수됨') : '선택한 작업 다시 실행';
    if (job) message.textContent = job.status === 'running' ? '재실행 중입니다. 단계별 진행은 타임라인에서 확인하세요.' : '다른 발행 작업이 없으면 즉시 시작합니다. 작업 중이면 종료 후 순서대로 실행합니다.';
  }
  async function poll(domain, jobId) {
    try {
      const response = await fetch('/api/workflows/jobs/' + jobId, {cache:'no-store'});
      if (!response.ok) throw new Error('재실행 요청 상태를 확인하지 못했습니다.');
      const data = await response.json();
      const current = requests.get(domain);
      if (current) current.status = data.status;
      if (data.status === 'failed' || data.status === 'succeeded') {
        requests.delete(domain);
        if (selected()?.domain === domain) {
          const error = String(data.error || '재실행 요청 처리에 실패했습니다.');
          const lastError = selected()?.lastError || '';
          const repeated = lastError && (error.includes(lastError) || lastError.includes(error));
          message.textContent = data.status === 'failed' ? (repeated ? '재실행에 실패했습니다. 상세 사유는 마지막 실패에서 확인하세요.' : error) : '재실행이 완료됐습니다. 발행 결과는 타임라인에서 확인하세요.';
        }
        render(); return;
      }
    } catch (error) {
      if (selected()?.domain === domain) message.textContent = error.message + ' 요청은 유지되며 다시 확인합니다.';
    }
    setTimeout(() => poll(domain, jobId), 3000);
  }
  button.addEventListener('click', async () => {
    const site = selected();
    if (button.disabled || !site) return;
    sending = true; render(); message.textContent = '재실행 요청을 보내고 있습니다…';
    try {
      const status = window.__PIPELINE_STATUS__ || {};
      const date = status.scheduleDate || status.date || new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Seoul'}).format(new Date());
      const response = await fetch('/api/workflows/cf/retry', {method:'POST', headers:{'Content-Type':'application/json','X-Barolab-Settings':'1'}, body:JSON.stringify({domain:site.domain,date})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '재실행 요청에 실패했습니다.');
      requests.set(site.domain, {id:data.id, status:data.status}); message.textContent = data.message;
      poll(site.domain, data.id);
    } catch (error) { message.textContent = error.message; }
    finally { sending = false; render(); }
  });
  setInterval(render, 1000); render();
})();
