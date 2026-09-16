/**
 * i18n setup.
 *
 * Locale files live at the repo root in locales/ so an operator can add a
 * language by mounting a file, the same way themes work. They are imported
 * here at build time for the shipped languages.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from '../../../locales/en.json'
import hu from '../../../locales/hu.json'

export const SUPPORTED_LOCALES = ['en', 'hu'] as const
export type Locale = (typeof SUPPORTED_LOCALES)[number]

export const LOCALE_LABELS: Record<Locale, string> = {
  en: 'English',
  hu: 'Magyar',
}

const STORAGE_KEY = 'kafkaplay.locale'

export function storedLocale(): Locale | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return SUPPORTED_LOCALES.includes(value as Locale) ? (value as Locale) : null
  } catch {
    return null
  }
}

export function persistLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    // Non-fatal: the language just resets on the next visit.
  }
}

export function initI18n(defaultLocale: string): typeof i18n {
  const initial = storedLocale() ?? (SUPPORTED_LOCALES.includes(defaultLocale as Locale)
    ? (defaultLocale as Locale)
    : 'en')

  void i18n.use(initReactI18next).init({
    resources: {
      en: { translation: en },
      hu: { translation: hu },
    },
    lng: initial,
    fallbackLng: 'en',
    interpolation: { escapeValue: false },
    returnNull: false,
  })

  return i18n
}

export default i18n
