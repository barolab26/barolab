const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const html = fs.readFileSync('dashboard/chat.html', 'utf8');
const start = html.indexOf('  let followLatest = true;');
const end = html.indexOf('  // =========================================================================', start);
const handlers = {};
let frames = [], mutation, resize, clicks;
const stream = {
  scrollTop: 900, scrollHeight: 1000, clientHeight: 100,
  addEventListener(name, fn) { handlers[name] = fn; },
};
let scrollTop = stream.scrollTop;
Object.defineProperty(stream, 'scrollTop', {
  get: () => scrollTop,
  set: value => { scrollTop = Math.max(0, Math.min(value, stream.scrollHeight - stream.clientHeight)); },
});
const context = {
  streamEl: stream, floatingBtnEl: {addEventListener(name, fn) { clicks = fn; }},
  scrollLockStatusEl: {}, unreadBelowCount: 0,
  updateFloatingNewMsgButton() {},
  isUserNearBottom: n => stream.scrollHeight - stream.scrollTop - stream.clientHeight <= n,
  performance: {now: () => 100},
  requestAnimationFrame(fn) { frames.push(fn); return frames.length; },
  MutationObserver: class { constructor(fn) { mutation = fn; } observe() {} },
  ResizeObserver: class { constructor(fn) { resize = fn; } observe() {} },
};
vm.createContext(context);
vm.runInContext(html.slice(start, end), context);
function flush() {
  const pending = frames; frames = [];
  pending.forEach(fn => fn());
  // Emulate browser clamping.
  stream.scrollTop = Math.min(stream.scrollTop, stream.scrollHeight - stream.clientHeight);
}
// Own questions and replies both follow the bottom; updates coalesce.
stream.scrollHeight = 1400;
context.handleSmartScrollOnNewMessage({}, true, false);
mutation(); resize();
assert.equal(frames.length, 1);
flush(); assert.equal(stream.scrollTop, 1300);
// Layout changes alone cannot suspend following.
stream.scrollHeight = 1800; handlers.scroll(); mutation(); flush();
assert.equal(stream.scrollTop, 1700);
// Explicit upward scrolling cancels even an already queued follow.
mutation(); handlers.wheel({deltaY: -100}); stream.scrollTop = 900;
flush(); mutation(); resize(); handlers.load(); flush();
assert.equal(stream.scrollTop, 900);
context.handleSmartScrollOnNewMessage({}, false, false);
assert.equal(context.unreadBelowCount, 1);
// The latest button resumes following and clears unread messages.
clicks(); flush(); assert.equal(stream.scrollTop, 1700);
assert.equal(context.unreadBelowCount, 0);
// A touch drag upwards through history also suspends follow.
handlers.touchstart({touches: [{clientY: 100}]});
handlers.touchmove({touches: [{clientY: 150}]});
stream.scrollTop = 1200; mutation(); flush(); assert.equal(stream.scrollTop, 1200);
// Manually returning to the bottom resumes following.
stream.scrollTop = 1700; handlers.scroll(); flush();
stream.scrollHeight = 2000; mutation(); flush(); assert.equal(stream.scrollTop, 1900);
console.log('Chat scroll regression checks passed');

// Real strategy replies from all participating employees belong in the conversation.
const replyStart = html.indexOf('  function staffMessageText(value) {');
const replyEnd = html.indexOf('  function isConversationMessage', replyStart);
const replies = {};
vm.createContext(replies);
vm.runInContext(html.slice(replyStart,replyEnd),replies);
const conversationStart = html.indexOf('  function isConversationMessage(m) {');
const conversationEnd = html.indexOf('  function renderWorkRecords', conversationStart);
vm.runInContext(html.slice(conversationStart,conversationEnd),replies);
assert.equal(replies.isConversationMessage({who:'system',goalId:'goal',userTurnId:'user'}),true);
assert.equal(replies.isConversationMessage({who:'system'}),false);
for (const who of ['jarvis','radar','trace','publi','patch','doctor']) {
  const row = {eventType:'crew_work_event',who,stage:'post-style-planning',phase:'completed',messageKind:'staff_reply',model:'observed-model',outputKind:'실제 조사 결과를 보고합니다.'};
  assert.equal(replies.crewConversationText(row),row.outputKind);
  assert.equal(replies.crewConversationText({...row,messageKind:'host_ack'}),null);
}

// Article links travel in trusted metadata, separately from staff prose.
const linkStart = html.indexOf('  function articleLinkHtml(m) {');
const linkEnd = html.indexOf('  function messageBodyText', linkStart);
const links = {URL, escapeHtml: text => String(text).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]))};
vm.createContext(links);
vm.runInContext(html.slice(linkStart,linkEnd),links);
const actualUrl = 'https://www.example.com/exact-article';
const link = links.articleLinkHtml({who:'doctor',deliverableUrl:actualUrl});
assert(link.includes(`href="${actualUrl}"`));
assert(link.includes('수정 대상 글 열기'));
assert(link.includes('rel="noopener noreferrer"'));
assert.equal(links.articleLinkHtml({deliverableUrl:'javascript:alert(1)'}),'');
assert.equal(links.articleLinkHtml({deliverableUrl:'https://user:password@example.com/article'}),'');
assert.equal(links.articleLinkHtml({}),'');
assert(links.articleLinkHtml({who:'doctor',taskTracker:{deliverableUrl:actualUrl}}).includes(actualUrl));

assert(links.articleLinkHtml({who:'doctor',deliverableUrl:actualUrl,deliverableLabel:'<script>제목</script>'}).includes('&lt;script&gt;제목&lt;/script&gt;'));

const factsStart = html.indexOf('  function reportContextHtml(m) {');
const factsEnd = html.indexOf('  function articleLinkHtml',factsStart);
vm.runInContext(html.slice(factsStart,factsEnd),links);
const details = links.reportContextHtml({reportContext:{channel:'네이버 블로그',account:'soultin',reserveTime:'2026-10-23 19:30',title:'<실제 글>',status:'예약 작성 보류'}});
for (const text of ['soultin','2026-10-23 19:30','&lt;실제 글&gt;','예약 작성 보류']) assert(details.includes(text));
assert.equal(links.reportContextHtml({}),'');
assert.equal(replies.crewConversationText({eventType:'crew_work_event',who:'publi',stage:'channel-cycle-summary',phase:'completed',model:'observed-model',outputKind:'채널 전체 점검.'}),null);

// Refreshing an already sorted stream must not detach any message rows.
const orderStart = html.indexOf('  function sortVisibleMessages() {');
const orderEnd = html.indexOf('  function syncActivePreparing', orderStart);
let moves = 0;
const rows = ['a', 'b', 'c'].map(id => ({id}));
const orderedStream = {
  scrollTop: 77,
  get firstElementChild() { return rows[0] || null; },
  querySelector(selector) { return rows.find(row => selector.includes(`"${row.id}"`)); },
  insertBefore(row, next) {
    moves++;
    rows.splice(rows.indexOf(row), 1);
    rows.splice(next ? rows.indexOf(next) : rows.length, 0, row);
  },
};
for (const row of rows) Object.defineProperty(row, 'nextElementSibling', {
  get() { return rows[rows.indexOf(row) + 1] || null; },
});
const ordering = {
  streamEl: orderedStream, CSS: {escape: value => value}, followLatest: false,
  messageStore: new Map(['a', 'b', 'c'].map(id => [id, {id}])),
  chronologicalMessages: values => [...values],
};
vm.createContext(ordering);
vm.runInContext(html.slice(orderStart, orderEnd), ordering);
ordering.sortVisibleMessages();
assert.equal(moves, 0);
assert.equal(orderedStream.scrollTop, 77);
rows.unshift(rows.pop());
ordering.sortVisibleMessages();
assert.deepEqual(rows.map(row => row.id), ['a', 'b', 'c']);
const correctedMoves = moves;
ordering.sortVisibleMessages();
assert.equal(moves, correctedMoves);
console.log('Chat stable DOM ordering checks passed');
