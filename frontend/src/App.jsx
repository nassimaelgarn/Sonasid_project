import React from 'react'
import AuthGate from './components/AuthGate.jsx'
import ChatErrorBoundary from './components/ChatErrorBoundary.jsx'

const ChatWorkspace = React.lazy(() => import('./components/ChatWorkspace.jsx'))

function App() {
  return (
    <ChatErrorBoundary>
      <React.Suspense fallback={<div className="p-6 text-slate-200">Chargement…</div>}>
        <AuthGate>
          <ChatWorkspace />
        </AuthGate>
      </React.Suspense>
    </ChatErrorBoundary>
  )
}

export default App
