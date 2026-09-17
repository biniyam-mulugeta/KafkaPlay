/**
 * Which cluster the UI is currently looking at.
 *
 * Multi-cluster is structural, not a later feature: every data hook takes a
 * cluster name, and the backend has no notion of a default. This context only
 * remembers the operator's last choice.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQuery } from '@tanstack/react-query'

import { api, type ClusterSummary } from '@/lib/api'

const STORAGE_KEY = 'offsetscope.cluster'

interface ClusterValue {
  clusters: ClusterSummary[]
  current: ClusterSummary | null
  currentName: string | null
  setCurrent: (name: string) => void
  isLoading: boolean
  isError: boolean
}

const ClusterContext = createContext<ClusterValue | null>(null)

function storedCluster(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

export function ClusterProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<string | null>(storedCluster)

  const query = useQuery({
    queryKey: ['clusters'],
    queryFn: api.clusters,
    // The configured cluster list only changes on restart.
    refetchInterval: false,
    staleTime: 60_000,
  })

  const clusters = useMemo(() => query.data?.clusters ?? [], [query.data])

  // Fall back to the first configured cluster when nothing is stored, or when
  // the stored one has been removed from the config.
  const currentName = useMemo(() => {
    if (clusters.length === 0) return null
    if (selected && clusters.some((c) => c.name === selected)) return selected
    return clusters[0]?.name ?? null
  }, [clusters, selected])

  useEffect(() => {
    if (!currentName) return
    try {
      localStorage.setItem(STORAGE_KEY, currentName)
    } catch {
      // Losing the preference is harmless.
    }
  }, [currentName])

  const setCurrent = useCallback((name: string) => setSelected(name), [])

  const value = useMemo<ClusterValue>(
    () => ({
      clusters,
      current: clusters.find((c) => c.name === currentName) ?? null,
      currentName,
      setCurrent,
      isLoading: query.isPending,
      isError: query.isError,
    }),
    [clusters, currentName, setCurrent, query.isPending, query.isError],
  )

  return <ClusterContext.Provider value={value}>{children}</ClusterContext.Provider>
}

export function useCluster(): ClusterValue {
  const value = useContext(ClusterContext)
  if (!value) throw new Error('useCluster must be used inside a ClusterProvider')
  return value
}

/** The selected cluster name, or null when none is configured. */
export function useClusterName(): string | null {
  return useCluster().currentName
}
