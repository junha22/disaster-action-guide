import { useSyncExternalStore } from 'react'

function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    onChange => {
      const list = window.matchMedia(query)
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    () => window.matchMedia(query).matches,
  )
}

// Matches Tailwind's lg breakpoint, where the result card floats over the map.
export function useIsWide(): boolean {
  return useMediaQuery('(min-width: 1024px)')
}

export function useReducedMotion(): boolean {
  return useMediaQuery('(prefers-reduced-motion: reduce)')
}
