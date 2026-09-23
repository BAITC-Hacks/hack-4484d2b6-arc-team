// Run with node --test tests/team_api.test.cjs. No browser or extra packages needed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync(require('node:path').join(__dirname, '../app/static/team-api.js'), 'utf8');
const roleSource = fs.readFileSync(require('node:path').join(__dirname, '../app/static/role-lock.js'), 'utf8');
function setup(fetch) {
  const role = { disabled: false };
  const values = new Map();
  const context = { window: {}, fetch, AbortController, URL, setTimeout, clearTimeout,
    document: { querySelector: () => role, querySelectorAll: () => [], documentElement: { dataset: { demoRole: 'team' } } },
    localStorage: { getItem: k => values.get(k), setItem: (k, v) => values.set(k, v) } };
  vm.runInNewContext(roleSource, context);
  vm.runInNewContext(source, context);
  return { api: context.window.SanaTeam, context, role };
}
test('public reads have no profile header; team writes carry only selected identity and JSON', async () => {
  const calls = [];
  const { api } = setup(async (...args) => { calls.push(args); return { ok: true, json: async () => [] }; });
  await api.request('/api/catalog');
  assert.equal(calls[0][1].method, 'GET');
  assert.equal(calls[0][1].headers['X-Demo-Team-Id'], undefined);
  await api.mutate('/api/tasks/task-1/proposals', 'team-2', { idea: 'A', prototype_url: null });
  assert.equal(calls[1][1].method, 'POST');
  assert.equal(calls[1][1].headers['X-Demo-Team-Id'], 'team-2');
  assert.equal(calls[1][1].headers['X-Demo-Business-Id'], undefined);
  assert.deepEqual(JSON.parse(calls[1][1].body), { idea: 'A', prototype_url: null });
});
test('role stays locked until every pending write ends, including rejected requests', async () => {
  const pending = [];
  const { api, role } = setup(() => new Promise(resolve => pending.push(resolve)));
  const first = api.mutate('/one', 'team-1', {});
  const second = api.mutate('/two', 'team-1', {});
  assert.equal(role.disabled, true);
  pending[0]({ ok: true, json: async () => ({}) });
  await first;
  assert.equal(role.disabled, true);
  pending[1]({ ok: false, status: 409, json: async () => ({ error: { code: 'team_not_selected', message: 'Not selected' } }) });
  await assert.rejects(second, e => e.status === 409 && e.code === 'team_not_selected');
  assert.equal(role.disabled, false);
});
test('malformed success responses and server errors do not become successful submissions', async () => {
  const { api } = setup(async () => ({ ok: true, json: async () => { throw new Error('HTML'); } }));
  await assert.rejects(api.request('/api/my/proposals', { teamId: 'team-1' }));
  assert.throws(() => api.proposals([{ id: 'p', status: 'selected' }]));
  assert.throws(() => api.teams({ teams: [{ id: 'team-1', name: 'One', points: -1 }] }));
});
test('unsafe URLs are never rendered as clickable links', () => {
  const { api } = setup();
  for (const value of ['javascript:alert(1)', 'data:text/html,x', 'file:///test', '/relative', 'https://name:pass@example.test']) {
    assert.equal(api.safeUrl(value), null);
  }
  assert.equal(api.safeUrl('https://example.test/demo'), 'https://example.test/demo');
});
test('business and builder cannot unlock the role while a team write is still pending', async () => {
  let finish;
  const { api, role, context } = setup(() => new Promise(resolve => { finish = resolve; }));
  context.window.SanaRole.setBusy('builder', true);
  const sent = api.mutate('/stage', 'team-1', {});
  context.window.SanaRole.setBusy('builder', false);
  context.window.SanaRole.setBusy('business', false);
  assert.equal(role.disabled, true);
  context.window.SanaRole.setBusy('business', true);
  finish({ ok: true, json: async () => ({}) });
  await sent;
  assert.equal(role.disabled, true);
  context.window.SanaRole.setBusy('business', false);
  assert.equal(role.disabled, false);
});
test('drafts remain isolated and usable in memory if browser storage fails', () => {
  const { api, context } = setup();
  context.localStorage = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('quota'); } };
  assert.equal(api.read('unknown'), null);
  assert.equal(api.write('team-1/task-1', 'first'), false);
  assert.equal(api.write('team-2/task-1', 'second'), false);
  assert.equal(api.read('team-1/task-1'), 'first');
  assert.equal(api.read('team-2/task-1'), 'second');
});
