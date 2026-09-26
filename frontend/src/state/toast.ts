/**
 * Toast notifications via a module-level emitter.
 *
 * Deliberately not a React context: toasts fire from API helpers and event
 * handlers all over the tree, and a single mounted <Toaster /> is enough.
 */

export interface ToastMessage {
  id: number
  tone: 'ok' | 'error' | 'info'
  text: string
  busy?: boolean
}

let counter = 0
let listeners: Array<(messages: ToastMessage[]) => void> = []
let messages: ToastMessage[] = []

function emit(): void {
  for (const listener of listeners) listener(messages)
}

function push(tone: ToastMessage['tone'], text: string, ttl = 5200): number {
  counter += 1
  const id = counter
  messages = [...messages, { id, tone, text }]
  emit()
  window.setTimeout(() => dismiss(id), ttl)
  return id
}

export function dismiss(id: number): void {
  messages = messages.filter((message) => message.id !== id)
  emit()
}

export function subscribe(listener: (next: ToastMessage[]) => void): () => void {
  listeners.push(listener)
  listener(messages)
  return () => {
    listeners = listeners.filter((candidate) => candidate !== listener)
  }
}

export const toast = {
  ok: (text: string) => push('ok', text),
  error: (text: string) => push('error', text, 8000),
  info: (text: string) => push('info', text),
  /** Long-running call: shows a spinner toast and resolves to a handle. */
  begin(text: string) {
    counter += 1
    const id = counter
    messages = [...messages, { id, tone: 'info', text, busy: true }]
    emit()
    return {
      done(next: string) {
        messages = messages.map((m) => (m.id === id ? { ...m, text: next, busy: false } : m))
        emit()
        window.setTimeout(() => dismiss(id), 4200)
      },
      fail(next: string) {
        messages = messages.map((m) => (m.id === id ? { ...m, text: next, tone: 'error', busy: false } : m))
        emit()
        window.setTimeout(() => dismiss(id), 7000)
      },
    }
  },
}
