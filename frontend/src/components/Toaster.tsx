import { useEffect, useState } from 'react'
import { Spinner } from './ui'
import { dismiss, subscribe, type ToastMessage } from '../state/toast'

export function Toaster() {
  const [items, setItems] = useState<ToastMessage[]>([])

  useEffect(() => subscribe(setItems), [])

  if (!items.length) return null

  return (
    <div className="toasts" aria-live="polite">
      {items.map((message) => (
        <div key={message.id} className={`toast toast-${message.tone}`}>
          {message.busy && <Spinner />}
          <span className="grow">{message.text}</span>
          {!message.busy && (
            <button type="button" className="copy" onClick={() => dismiss(message.id)}>
              close
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
