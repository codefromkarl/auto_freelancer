import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import {
  createBid,
  getMessages,
  getMessageThreads,
  searchProjects,
  triggerScript,
  exportProjects,
  scoreProject,
  updatePromptTemplate,
} from './api.ts';

const originalFetch = globalThis.fetch;
const calls: { url: string; options?: RequestInit }[] = [];
let body: unknown;
let status: number;
const storage = new Map<string, string>();

beforeEach(() => {
  calls.length = 0;
  storage.clear();
  storage.set('api_url', 'http://local.test/api/v1');
  storage.set('api_key', 'local-test-key');
  Object.defineProperty(globalThis, 'window', { value: {}, configurable: true });
  Object.defineProperty(globalThis, 'localStorage', {
    value: { getItem: (key: string) => storage.get(key) || null },
    configurable: true,
  });
  body = { status: 'success', data: [] };
  status = 200;
  globalThis.fetch = async (input, options) => {
    calls.push({ url: String(input), options });
    return new Response(JSON.stringify(body), { status });
  };
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  Reflect.deleteProperty(globalThis, 'window');
  Reflect.deleteProperty(globalThis, 'localStorage');
});

test('project filters use backend parameter names and current key', async () => {
  await searchProjects({ min_score: 7, score_range: [7, 9], budget_min: 100, refresh: true });
  const url = new URL(calls[0].url);
  assert.equal(url.searchParams.get('score_min'), '7');
  assert.equal(url.searchParams.get('score_max'), '9');
  assert.equal(url.searchParams.get('budget_min'), '100');
  assert.equal(new Headers(calls[0].options?.headers).get('X-API-Key'), 'local-test-key');
  storage.set('api_key', 'updated-key');
  await scoreProject(123);
  assert.equal(new Headers(calls[1].options?.headers).get('X-API-Key'), 'updated-key');
});

test('bid sends explicit currency and project ID without placeholders', async () => {
  await createBid(123, { amount: 585, amount_currency: 'INR', period: 7 });
  assert.deepEqual(JSON.parse(String(calls[0].options?.body)), {
    project_id: 123,
    amount: 585,
    amount_currency: 'INR',
    period: 7,
  });
  assert.equal(calls.length, 1);
});

test('uncertain submission errors propagate without retries', async () => {
  body = { detail: 'Remote reconciliation required' };
  status = 409;
  await assert.rejects(createBid(123, { amount: 100, period: 7 }), /reconciliation/);
  assert.equal(calls.length, 1);
});

test('thread list does not read every conversation', async () => {
  body = { data: [{ thread_id: 42, project_id: 123, unread_count: 2 }] };
  const threads = await getMessageThreads();
  assert.equal(threads[0].thread_id, 42);
  assert.deepEqual(threads[0].messages, []);
  assert.equal(calls.length, 1);
});

test('messages normalize the actual backend contract', async () => {
  body = {
    data: [
      {
        id: 9,
        thread_id: 42,
        user_id: 100,
        username: 'Client',
        message: 'Hello',
        is_read: true,
        send_time: '2026-10-10T00:00:00',
        created_at: '',
      },
    ],
  };
  const messages = await getMessages(42);
  assert.equal(messages[0].content, 'Hello');
  assert.equal(messages[0].sender_name, 'Client');
  assert.equal(calls[0].url, 'http://local.test/api/v1/messages/42');
});

test('unsupported workflows fail without reporting success or making requests', async () => {
  await assert.rejects(triggerScript('score_all'), /尚未接入/);
  await assert.rejects(searchProjects({ skills: ['Python'] }), /数字技能/);
  await assert.rejects(exportProjects({ format: 'xlsx', fields: [], filters: {} }), /尚未接入/);
  assert.equal(calls.length, 0);
});

test('template updates use the configuration endpoint', async () => {
  await updatePromptTemplate(7, { content: 'Reviewed prompt' });
  assert.equal(calls[0].url, 'http://local.test/api/v1/prompt-templates/7');
  assert.equal(calls[0].options?.method, 'PUT');
});

test('CSV exports use actual data and escape formula cells', async () => {
  body = { data: [{ id: 123, title: '=HYPERLINK("test")', status: 'open' }] };
  const csv = await exportProjects({ format: 'csv', fields: ['title'], filters: {} });
  assert.match(await csv.text(), /'=/);
});
