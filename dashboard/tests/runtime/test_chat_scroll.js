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
