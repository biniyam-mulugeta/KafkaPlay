/**
 * Typed API client.
 *
 * Every mutating request carries the CSRF token that /auth/login handed back,
 * matching the double-submit check the backend enforces in get_principal.
 */

import type { ThemeInfo } from '@/theme/themeLoader'

export type Role = 'viewer' | 'operator' | 'admin'
export type AuthMode = 'local' | 'oidc' | 'none'

export interface Meta {
  app_name: string
  version: string
  auth_mode: AuthMode
  insecure_no_auth: boolean
  read_only: boolean
  masking_enabled: boolean
  mask_presets: string[]
  prometheus_enabled: boolean
  sampler_enabled: boolean
  default_locale: string
  available_locales: string[]
  theme: ThemeInfo
}

export interface Me {
  username: string
  role: Role
  provider: string
  csrf_token: string
}

export interface ClusterSummary {
  name: string
  label: string
  security_protocol: string
  sasl_mechanism: string | null
  has_schema_registry: boolean
  read_only: boolean
  masking_enabled: boolean
  reachable: boolean | null
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  get isUnauthenticated(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }
}

let csrfToken: string | null = null

export function setCsrfToken(token: string | null): void {
  csrfToken = token
}

export function getCsrfToken(): string | null {
  return csrfToken
}

const UNSAFE = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)

  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (UNSAFE.has(method) && csrfToken) {
    headers.set('X-CSRF-Token', csrfToken)
  }

  const response = await fetch(`/api/v1${path}`, {
    ...init,
    method,
    headers,
    // Session cookie is httpOnly; it must ride along on every call.
    credentials: 'same-origin',
  })

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  let parsed: unknown = undefined
  if (text) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = text
    }
  }

  if (!response.ok) {
    const detail =
      parsed && typeof parsed === 'object' && 'detail' in parsed
        ? String((parsed as { detail: unknown }).detail)
        : response.statusText
    throw new ApiError(response.status, detail, parsed)
  }

  return parsed as T
}

export const api = {
  meta: () => request<Meta>('/meta'),
  me: () => request<Me>('/auth/me'),
  login: (username: string, password: string) =>
    request<Me>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<void>('/auth/logout', { method: 'POST' }),
  clusters: () => request<{ clusters: ClusterSummary[] }>('/clusters'),
}
