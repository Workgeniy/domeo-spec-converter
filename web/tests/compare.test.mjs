import { test } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

const out = resolve('node_modules/.tmp/compare-test.mjs')
await build({
  stdin: { contents: `export { diffSpecs } from './src/compare'`, resolveDir: process.cwd(), loader: 'ts' },
  outfile: out, bundle: true, platform: 'node', format: 'esm', packages: 'external',
})
const { diffSpecs } = await import(pathToFileURL(out))

// Минимальная позиция свода — compare читает только pos/pos_key/name/description/type_mark/unit/qty.
const item = (o) => ({ pos: '', pos_key: '', name: '', description: '', type_mark: '', unit: 'шт.', qty: 1, ...o })

test('идентичные версии → всё без изменений', () => {
  const a = [item({ pos: '1', pos_key: '1', name: 'Стол' }), item({ pos: '2', pos_key: '2', name: 'Стул' })]
  const d = diffSpecs(a, a.map((x) => ({ ...x })))
  assert.deepEqual(d.counts, { added: 0, removed: 0, changed: 0, unchanged: 2 })
})

test('смена наименования при том же номере → изменено', () => {
  const d = diffSpecs(
    [item({ pos: '1', pos_key: '1', name: 'Стол письменный' })],
    [item({ pos: '1', pos_key: '1', name: 'Стол компьютерный' })],
  )
  assert.equal(d.counts.changed, 1)
  const change = d.rows[0].changes.find((c) => c.field === 'name')
  assert.equal(change.before, 'Стол письменный')
  assert.equal(change.after, 'Стол компьютерный')
})

test('смена количества → изменено', () => {
  const d = diffSpecs(
    [item({ pos: '1', pos_key: '1', name: 'Стол', qty: 5 })],
    [item({ pos: '1', pos_key: '1', name: 'Стол', qty: 8 })],
  )
  assert.equal(d.counts.changed, 1)
  assert.ok(d.rows[0].changes.some((c) => c.field === 'qty' && c.before === '5' && c.after === '8'))
})

test('добавленные и удалённые позиции', () => {
  const added = diffSpecs(
    [item({ pos: '1', pos_key: '1', name: 'А' })],
    [item({ pos: '1', pos_key: '1', name: 'А' }), item({ pos: '2', pos_key: '2', name: 'Б' })],
  )
  assert.equal(added.counts.added, 1)
  assert.equal(added.counts.unchanged, 1)

  const removed = diffSpecs(
    [item({ pos: '1', pos_key: '1', name: 'А' }), item({ pos: '2', pos_key: '2', name: 'Б' })],
    [item({ pos: '1', pos_key: '1', name: 'А' })],
  )
  assert.equal(removed.counts.removed, 1)
})

test('перенумерованная позиция (то же наименование) → изменено, а не удаление+добавление', () => {
  const d = diffSpecs(
    [item({ pos: '2.5', pos_key: '2.5', name: 'Шкаф для одежды' })],
    [item({ pos: '2.6', pos_key: '2.6', name: 'Шкаф для одежды' })],
  )
  assert.deepEqual({ a: d.counts.added, r: d.counts.removed, c: d.counts.changed }, { a: 0, r: 0, c: 1 })
  assert.ok(d.rows[0].changes.some((c) => c.field === 'pos' && c.before === '2.5' && c.after === '2.6'))
})

test('различия в пробелах не считаются изменением', () => {
  const d = diffSpecs(
    [item({ pos: '1', pos_key: '1', name: 'Стол  обеденный' })],
    [item({ pos: '1', pos_key: '1', name: 'Стол обеденный ' })],
  )
  assert.equal(d.counts.unchanged, 1)
  assert.equal(d.counts.changed, 0)
})
