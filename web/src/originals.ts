// Исходники хранятся отдельно от JSON рабочего пространства: IndexedDB поддерживает большие Blob.
import { downloadUpload } from './api'

export interface OriginalFile { id: string; name: string; serverId?: string; templateId?: string; warning?: string }

async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('domeo-spec-originals', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('files')
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('Не удалось открыть хранилище исходных Excel-файлов.'))
  })
}

export async function rememberOriginal(file: File): Promise<OriginalFile> {
  const db = await database()
  const id = typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`
  try {
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction('files', 'readwrite')
      transaction.objectStore('files').put(file, id)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(new Error('Не удалось сохранить исходный Excel-файл в браузере.'))
      transaction.onabort = () => reject(new Error('Сохранение исходного Excel-файла прервано.'))
    })
    return { id, name: file.name }
  } finally { db.close() }
}

export async function readOriginal(original: OriginalFile): Promise<File> {
  if (original.serverId) return new File([await downloadUpload(original.serverId)], original.name)
  const db = await database()
  try {
    return await new Promise<File>((resolve, reject) => {
      const request = db.transaction('files').objectStore('files').get(original.id)
      request.onsuccess = () => request.result instanceof Blob
        ? resolve(new File([request.result], original.name))
        : reject(new Error('Исходный файл отсутствует в браузере. Загрузите его повторно.'))
      request.onerror = () => reject(new Error('Не удалось прочитать исходный файл.'))
    })
  } finally { db.close() }
}

export async function forgetOriginal(id: string): Promise<void> {
  const db = await database()
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction('files', 'readwrite')
      tx.objectStore('files').delete(id)
      tx.oncomplete = () => resolve()
      tx.onerror = () => reject(tx.error)
      tx.onabort = () => reject(tx.error)
    })
  } finally { db.close() }
}
