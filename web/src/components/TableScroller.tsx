import { useEffect, useRef, useState, type ReactNode } from 'react'

interface Props {
  /** Ширина таблицы, меньше которой столбцы не сжимаются; при нехватке места — прокрутка. */
  minWidth: number
  children: ReactNode
}

/**
 * Горизонтальная прокрутка широкой таблицы с полосой, прижатой к низу экрана.
 *
 * Обычный контейнер с overflow рисует полосу под таблицей, а таблица на 50 строк уходит за
 * экран — полосу не видно, пока не долистаешь до конца. Здесь у контейнера своя полоса скрыта,
 * а под ним лежит sticky-полоса той же ширины: она всегда на экране, и скролл синхронизирован в
 * обе стороны. Когда таблица помещается по ширине, полоса не показывается.
 */
export function TableScroller({ minWidth, children }: Props) {
  const outer = useRef<HTMLDivElement>(null)
  const bar = useRef<HTMLDivElement>(null)
  const [scrollWidth, setScrollWidth] = useState(0)
  const [needed, setNeeded] = useState(false)
  const syncing = useRef(false)

  useEffect(() => {
    const el = outer.current
    if (!el) return
    const update = () => {
      setScrollWidth(el.scrollWidth)
      setNeeded(el.scrollWidth > el.clientWidth + 1)
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(el)
    if (el.firstElementChild) observer.observe(el.firstElementChild)
    return () => observer.disconnect()
  }, [])

  function sync(from: HTMLDivElement | null, to: HTMLDivElement | null) {
    if (!from || !to || syncing.current) return
    syncing.current = true
    to.scrollLeft = from.scrollLeft
    syncing.current = false
  }

  return (
    <>
      <div ref={outer} className="hscroll-hidden" style={{ overflowX: 'auto', overflowY: 'hidden' }} onScroll={() => sync(outer.current, bar.current)}>
        <div style={{ minWidth }}>{children}</div>
      </div>
      {needed && (
        <div
          ref={bar}
          style={{
            position: 'sticky',
            bottom: 0,
            overflowX: 'auto',
            overflowY: 'hidden',
            height: 18,
            background: 'var(--mantine-color-body)',
            borderTop: '1px solid var(--mantine-color-gray-3)',
            zIndex: 5,
          }}
          onScroll={() => sync(bar.current, outer.current)}
          aria-label="горизонтальная прокрутка таблицы"
        >
          <div style={{ width: scrollWidth, height: 1 }} />
        </div>
      )}
    </>
  )
}
