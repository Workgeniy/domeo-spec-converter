// Состояние интерфейса, не относящееся к объекту: открыто ли окно поставщиков.
// Отдельно от рабочего пространства, чтобы не попадать в localStorage.

import { create } from 'zustand'

interface UiState {
  suppliersOpen: boolean
  openSuppliers: () => void
  closeSuppliers: () => void
}

export const useUi = create<UiState>()((set) => ({
  suppliersOpen: false,
  openSuppliers: () => set({ suppliersOpen: true }),
  closeSuppliers: () => set({ suppliersOpen: false }),
}))
