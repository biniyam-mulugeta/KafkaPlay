/** App-wide context: deployment metadata, the signed-in user, and colour mode. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import { ApiError, api, setCsrfToken, type Me, type Meta } from '@/lib/api'
import {
  applyFavicon,
  applyTheme,
  persistMode,
  resolveInitialMode,
  type ColorMode,
} from '@/theme/themeLoader'

interface SessionValue {
  meta: Meta
  me: Me | null
  mode: ColorMode
  setMode: (mode: ColorMode) => void
  signIn: (username: string, password: string) => Promise<void>
  signUp: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  /** True when the deployment needs a login and nobody is signed in. */
  needsLogin: boolean
}

const SessionContext = createContext<SessionValue | null>(null)

export function SessionProvider({ meta, initialMe, children }: {
  meta: Meta
  initialMe: Me | null
  children: ReactNode
}) {
  const [me, setMe] = useState<Me | null>(initialMe)
  const [mode, setModeState] = useState<ColorMode>(resolveInitialMode)

  useEffect(() => {
    applyTheme(meta.theme, mode)
    applyFavicon(meta.theme.favicon)
  }, [meta.theme, mode])

  const setMode = useCallback((next: ColorMode) => {
    setModeState(next)
    persistMode(next)
  }, [])

  const signIn = useCallback(async (username: string, password: string) => {
    const user = await api.login(username, password)
    setCsrfToken(user.csrf_token)
    setMe(user)
  }, [])

  const signUp = useCallback(async (username: string, password: string) => {
    const user = await api.signup(username, password)
    setCsrfToken(user.csrf_token)
    setMe(user)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      // Clear locally even if the request failed; the cookie may already be gone.
      setCsrfToken(null)
      setMe(null)
    }
  }, [])

  const value = useMemo<SessionValue>(
    () => ({
      meta,
      me,
      mode,
      setMode,
      signIn,
      signUp,
      signOut,
      needsLogin: meta.auth_mode !== 'none' && me === null,
    }),
    [meta, me, mode, setMode, signIn, signUp, signOut],
  )

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext)
  if (!value) throw new Error('useSession must be used inside a SessionProvider')
  return value
}

/** Fetches the current user, treating 401 as "not signed in" rather than an error. */
export async function fetchInitialMe(): Promise<Me | null> {
  try {
    const me = await api.me()
    setCsrfToken(me.csrf_token)
    return me
  } catch (error) {
    if (error instanceof ApiError && error.isUnauthenticated) return null
    throw error
  }
}
