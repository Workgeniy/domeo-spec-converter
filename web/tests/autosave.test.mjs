import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

const out = resolve('node_modules/.tmp/autosave-test.mjs')
await build({ stdin: { contents: `export * from './src/projects'; export { useWorkspace } from './src/store'; export { useTemplates } from './src/templates'`,
  resolveDir: process.cwd(), loader: 'ts' }, outfile: out, bundle: true, platform: 'node', format: 'esm', packages: 'external' })
let sequence = 0
const ok = (data) => new Response(JSON.stringify({ success: true, data }), { status: 200 })
const conflict = () => new Response(JSON.stringify({ detail: 'Объект изменён' }), { status: 409 })
const tick = () => new Promise((resolve) => setImmediate(resolve))
function doc() { return { file_name: 'test.xlsx', doc_code: '', title: 'Школа', spec_title: '', pages: [], items: [], documents: [], warnings: [],
  summary: [{ pos: '1', name: 'Стол', qty: 2, price: 100, excluded: false }, { pos: '2', name: 'Стул', qty: 1, price: 50, excluded: true }] } }
async function app(cache) {
  const values = new Map(cache ? [['domeo-spec-workspace', JSON.stringify(cache)]] : [])
  globalThis.localStorage = { getItem: (k) => values.get(k) ?? null, setItem: (k, v) => values.set(k, v), removeItem: (k) => values.delete(k) }
  globalThis.window = { addEventListener() {}, confirm: () => true }
  const module = await import(`${pathToFileURL(out)}?instance=${sequence++}`)
  await module.startAutosave()
  return module
}
function server() {
  const rows = new Map(), requests = []
  globalThis.fetch = async (url, options) => {
    const id = String(url).split('/').at(-1)
    if (options?.method !== 'PUT') return rows.has(id) ? ok(rows.get(id).detail) : new Response('{}', { status: 404 })
    const body = JSON.parse(options.body); requests.push({ id, body })
    const current = rows.get(id)
    if (current?.body.mutation_id === body.mutation_id && JSON.stringify(current.body) === options.body) return ok(current.detail.info)
    if ((current?.detail.info.revision ?? 0) !== body.expected_revision) return conflict()
    const info = { id, revision: body.expected_revision + 1, updated_at: new Date().toISOString(), quotation_id: body.quotation_id, title: body.snapshot.title }
    rows.set(id, { body, detail: { info, snapshot: body.snapshot } })
    return ok(info)
  }
  return { rows, requests }
}

test('правки во время запроса сохраняются следующей версией, вместе с маржой и шаблоном', async () => {
  const remote = server(), send = globalThis.fetch
  const a = await app()
  let release
  const waiting = new Promise((r) => { release = r })
  let calls = 0
  globalThis.fetch = async (...args) => { if (++calls === 1) await waiting; return send(...args) }
  a.useWorkspace.getState().addDocument(doc())
  const saving = a.flushProject(); await tick()
  const state = a.useWorkspace.getState()
  state.updateRow({ docId: state.documents[0].id, index: 0 }, { price: 900 })
  state.setKp({ margin_percent: 25 })
  a.useTemplates.getState().restore('Zm9ybQ==', 'Моя форма')
  release(); await saving
  assert.equal(remote.requests.length, 2)
  const final = remote.rows.get(state.projectId).detail
  assert.equal(final.info.revision, 2)
  assert.equal(final.snapshot.documents[0].doc.summary[0].price, 900)
  assert.equal(final.snapshot.documents[0].doc.summary[1].excluded, true)
  assert.equal(final.snapshot.kp.margin_percent, 25)
  assert.equal(final.snapshot.template, 'Zm9ybQ==')
  assert.equal(a.useCloud.getState().status, 'saved')
  await a.closeProject()
})

test('потерянный ответ: сначала повторяется тот же запрос, затем отправляются новые правки', async () => {
  const remote = server(), send = globalThis.fetch, a = await app()
  let drop = true
  globalThis.fetch = async (...args) => { const reply = await send(...args); if (drop) { drop = false; throw new TypeError('Обрыв связи') } return reply }
  a.useWorkspace.getState().addDocument(doc())
  await assert.rejects(a.flushProject(), /Обрыв/)
  assert.equal(a.useCloud.getState().status, 'error')
  a.useWorkspace.getState().setTitle('Школа с правками')
  await a.flushProject()
  assert.equal(remote.requests.length, 3)
  assert.deepEqual(remote.requests[0], remote.requests[1])
  assert.equal(a.useWorkspace.getState().cloud.revision, 2)
  assert.equal(a.useWorkspace.getState().cloud.dirty, false)
  await a.closeProject()
})

test('конфликт блокирует закрытие, отдельная копия сохраняет обе работы', async () => {
  const remote = server(), send = globalThis.fetch, a = await app()
  a.useWorkspace.getState().addDocument(doc()); await a.flushProject()
  const id = a.useWorkspace.getState().projectId
  const existing = structuredClone(remote.rows.get(id).detail)
  a.useWorkspace.getState().setTitle('Мои правки')
  globalThis.fetch = async (url, opts) => String(url).endsWith(id) && opts?.method === 'PUT' ? conflict() : send(url, opts)
  await assert.rejects(a.flushProject())
  await assert.rejects(a.closeProject())
  assert.equal(a.useWorkspace.getState().projectId, id)
  assert.equal(a.useWorkspace.getState().title, 'Мои правки')
  await a.saveProjectCopy()
  assert.notEqual(a.useWorkspace.getState().projectId, id)
  assert.deepEqual(remote.rows.get(id).detail, existing)
  assert.equal(remote.rows.size, 2)
  assert.match(a.useWorkspace.getState().title, /Мои правки — копия/)
  await a.closeProject()
})

test('при открытии другого объекта текущие правки сначала сохраняются; пустой объект тоже сохраняется', async () => {
  const remote = server(), a = await app()
  a.useWorkspace.getState().addDocument(doc()); await a.flushProject()
  const first = a.useWorkspace.getState().projectId
  await a.closeProject()
  a.useWorkspace.getState().addDocument(doc())
  a.useWorkspace.getState().setTitle('Второй объект')
  const second = a.useWorkspace.getState().projectId
  await a.openProject(first)
  assert.equal(remote.rows.get(second).detail.snapshot.title, 'Второй объект')
  assert.equal(a.useWorkspace.getState().projectId, first)
  a.useWorkspace.getState().removeDocument(a.useWorkspace.getState().documents[0].id)
  await a.flushProject()
  assert.equal(remote.rows.get(first).detail.snapshot.documents.length, 0)
  await a.closeProject()
})

test('после перезагрузки чистый кэш обновляется с сервера, грязный не затирается', async () => {
  const remote = server(), a = await app()
  a.useWorkspace.getState().addDocument(doc()); await a.flushProject()
  const cached = JSON.parse(localStorage.getItem('domeo-spec-workspace'))
  const id = a.useWorkspace.getState().projectId
  remote.rows.get(id).detail.snapshot.title = 'Правки коллеги'
  remote.rows.get(id).detail.info.revision++
  await a.closeProject()
  const b = await app(cached)
  assert.equal(b.useWorkspace.getState().title, 'Правки коллеги')
  await b.closeProject()
  cached.state.cloud.dirty = true; cached.state.title = 'Локальные правки'
  const c = await app(cached)
  assert.equal(c.useCloud.getState().status, 'conflict')
  assert.equal(c.useWorkspace.getState().title, 'Локальные правки')
  await c.saveProjectCopy(); await c.closeProject()
})
