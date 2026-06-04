import React from 'react'

export default class ChatErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('Chat UI error', error, info)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-lg rounded-2xl border border-red-200 bg-white p-6 text-slate-800 shadow-lg">
          <h2 className="text-lg font-semibold text-red-700">Interface interrompue</h2>
          <p className="mt-2 text-sm">
            Rechargez la page avec{' '}
            <a className="font-medium text-blue-600 underline" href="http://localhost:5175">
              http://localhost:5175
            </a>{' '}
            (pas <code className="text-xs">localhost</code> seul).
          </p>
          <p className="mt-3 text-xs text-slate-500">{String(this.state.error?.message || this.state.error)}</p>
          <button
            type="button"
            className="mt-4 rounded-lg bg-slate-800 px-4 py-2 text-sm text-white"
            onClick={() => window.location.reload()}
          >
            Recharger
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
