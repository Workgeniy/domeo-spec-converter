// Совпадающие позиции между томами одного объекта — их легко посчитать дважды. Ищем по
// наименованию (как в ядре, app/parsing/aggregate.py), а не по номеру позиции: тома
// нумеруются независимо, одинаковый номер в ТХ1 и ТХ2 — это обычно разные вещи.

import type { RowKey, WorkspaceDocument } from './store'

export interface DuplicateOccurrence {
  rowKey: RowKey
  docCode: string
  pos: string
  name: string
  qty: number | null
  excluded: boolean
}

export interface DuplicateGroup {
  key: string
  name: string
  occurrences: DuplicateOccurrence[]
}

/** Ключ совпадения: строчные, ё→е, без пунктуации. Полное описание, иначе краткое имя. */
function duplicateKey(text: string): string {
  return text
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[^a-zа-я0-9]+/g, ' ')
    .trim()
}

/** Группы позиций с одинаковым наименованием минимум из двух разных томов. */
export function crossVolumeDuplicates(documents: WorkspaceDocument[]): DuplicateGroup[] {
  if (documents.length < 2) return []
  const byKey = new Map<string, DuplicateOccurrence[]>()
  for (const d of documents) {
    const docCode = d.doc.doc_code || d.doc.file_name
    d.doc.summary.forEach((row, index) => {
      const key = duplicateKey((row.description || row.name).trim())
      if (key.length < 3) return
      const occ: DuplicateOccurrence = {
        rowKey: { docId: d.id, index },
        docCode,
        pos: row.pos,
        name: row.name,
        qty: row.qty,
        excluded: row.excluded === true,
      }
      const list = byKey.get(key)
      if (list) list.push(occ)
      else byKey.set(key, [occ])
    })
  }
  const groups: DuplicateGroup[] = []
  for (const occurrences of byKey.values()) {
    if (new Set(occurrences.map((o) => o.docCode)).size >= 2) {
      groups.push({ key: occurrences[0].name, name: occurrences[0].name, occurrences })
    }
  }
  return groups
}
