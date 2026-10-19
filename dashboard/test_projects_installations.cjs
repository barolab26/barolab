const assert = require('node:assert/strict');
const {test} = require('node:test');
const {installationState, installationSlot, playAppState, playPortfolioState, playDisplayLabels, saveInstallation} = require('./projects.js');

const doc = (count = 2, tracking = {}) => ({
  contractVersion: 'tester-installations-v1', revision: 3,
  accounts: Array.from({length: 13}, (_, i) => ({id: `account-${i}`, email: `tester${i}@example.test`, installed: i < count})),
  localTracking: {requiredCount: 12, requiredDays: 14, startedAt: null, dayNumber: 0, ...tracking}
});

test('two manual installs never become Google opt-ins or an official countdown', () => {
  const state = installationState(doc());
  assert.equal(state.count, 2); assert.equal(state.required, 12);
  assert.equal(state.started, false); assert.equal(state.day, 0);
  assert.equal(state.googleQualificationVerified, false);
  assert.equal(playAppState().optedIn, null);
});

test('local day is based only on persisted start and clamps to its own 14-day view', () => {
  const startedAt = '2026-10-19T13:00:00+09:00';
  assert.equal(installationState(doc(12, {startedAt, dayNumber: 1})).day, 1);
  assert.equal(installationState(doc(12, {startedAt, dayNumber: 99})).day, 14);
  assert.equal(installationState(doc(11, {startedAt, dayNumber: 8})).started, false);
  assert.equal(installationState(doc(13, {startedAt, dayNumber: 14})).googleQualificationVerified, false);
});

test('unknown or malformed installation responses cannot appear as zero or be saved', () => {
  assert.equal(installationState({}).count, null);
  const duplicate = doc(); duplicate.accounts[1].id = duplicate.accounts[0].id;
  assert.equal(installationState(duplicate).available, false);
  const coerced = doc(); coerced.accounts[0].installed = 'true';
  assert.equal(installationState(coerced).available, false);
});

test('fallback slots cover six phone pairs and the thirteenth spare without duplicate labels', () => {
  const slots = doc().accounts.map(installationSlot);
  assert.equal(slots[0], '폰1-일반'); assert.equal(slots[1], '폰1-보안폴더');
  assert.equal(slots[11], '폰6-보안폴더'); assert.equal(slots[12], '예비13');
  assert.equal(new Set(slots).size, 13);
  assert.equal(installationSlot({slot: '지정 슬롯'}, 0), '지정 슬롯');
  assert.equal(installationSlot({slot: 3}, 0), '폰2-일반');
  assert.equal(installationSlot({slot: 12}, 0), '폰6-보안폴더');
  assert.equal(installationSlot({slot: 13}, 0), '예비13');
});

test('Console unknown counters stay unknown while actual zero stays zero', () => {
  const unknown = playAppState({googleOptInCount: null, googleInstallCount: '0', continuousTestDays: null});
  assert.equal(unknown.optedIn, null); assert.equal(unknown.installs, null); assert.equal(unknown.days, null);
  assert.equal(playAppState({googleOptInCount: 0, continuousTestDays: 0}).optedIn, 0);
});

test('review approval, active track and released state are independent observations', () => {
  const state = playAppState({alpha: {reviewStatus: 'approved', trackActive: true, released: null}});
  assert.equal(state.review, '검토 승인 확인'); assert.equal(state.alphaActive, '트랙 활성');
  assert.equal(state.alphaReleased, '출시 여부 미확인'); assert.equal(state.days, null);
});

test('stale/error preserves prior observed values with their timestamp', () => {
  const state = playAppState({googleOptInCount: 1, checkedAt: '2026-10-19T13:00:00+09:00'}, {stale: true, error: 'collector_busy'});
  assert.equal(state.optedIn, 1); assert.equal(state.stale, true);
  assert.equal(state.error, 'collector_busy'); assert.equal(state.checkedAt, '2026-10-19T13:00:00+09:00');
});

test('portfolio leads with Alpha and preserves each app zero/one opt-in independently', () => {
  const ids = ['bible_app', 'greeting', 'magnifier', 'shopping'];
  const apps = Object.fromEntries(ids.map((id, i) => [id, {alpha: {released: true}, internal: {released: true}, googleOptInCount: i === 0 ? 0 : 1}]));
  const state = playPortfolioState({apps});
  assert.equal(state.alphaReleased, 4); assert.equal(state.alphaObserved, 4);
  assert.deepEqual(state.optIns, [0, 1, 1, 1]);
  assert.deepEqual(playPortfolioState().optIns, [null, null, null, null]);
});

test('project detail next action follows actual Alpha participation, not local installs or legacy pending text', () => {
  const released = {alpha: {released: true, reviewStatus: 'approved'}, internal: {released: true}, googleOptInCount: 1};
  const labels = playDisplayLabels(released, {});
  assert.equal(labels.nextAction, '이 앱 Alpha에 11명 추가 참여 확인 필요');
  assert.match(labels.track, /Alpha 출시됨/); assert.doesNotMatch(labels.detail, /검토 중/);
  const unknown = playDisplayLabels({}, {});
  assert.match(unknown.detail, /Google 참여 미확인/); assert.doesNotMatch(unknown.detail, /0명/);
});

test('toggle PATCH submits revision and strict boolean and accepts server truth only', async () => {
  let request;
  const updated = doc(3); updated.revision = 4;
  const result = await saveInstallation('account/3', true, 3, async (url, options) => {
    request = {url, options}; return {ok: true, json: async () => ({testersControlCenter: updated})};
  });
  assert.equal(request.url, '/api/projects/testers/accounts/account%2F3');
  assert.equal(request.options.method, 'PATCH');
  assert.deepEqual(JSON.parse(request.options.body), {installed: true, expectedRevision: 3});
  assert.equal(result.revision, 4); assert.equal(installationState(result).count, 3);
});

test('conflict or failed save does not mutate the prior state', async () => {
  const previous = doc(); const original = JSON.stringify(previous);
  await assert.rejects(saveInstallation('account-3', true, previous.revision, async () => ({ok: false, status: 409})), error => error.status === 409);
  await assert.rejects(saveInstallation('account-3', true, previous.revision, async () => ({ok: false, status: 500})), error => error.status === 500);
  assert.equal(JSON.stringify(previous), original);
});

test('legacy success response without persisted accounts is rejected', async () => {
  await assert.rejects(saveInstallation('account-3', true, 3, async () => ({ok: true, json: async () => ({ok: true})})), /invalid_installation_response/);
});
