import { useState } from 'react'
import SummaryBar from './components/SummaryBar.jsx'
import ResultCard from './components/ResultCard.jsx'
import ReportLookup from './components/ReportLookup.jsx'
import './App.css'

function App() {
  const [requirements, setRequirements] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState(null)

  const handleVerify = async () => {
    const text = requirements.trim()

    if (!text) {
      setError('Please enter the developer requirements.')
      return
    }

    setLoading(true)
    setError('')
    setReport(null)

    try {
      const response = await fetch('/verify', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          repo_url: 'https://github.com/JAGANSAI-2006/flaskshop',
         requirements: [text],
        }),
      })

      const data = await response.json()

      if (!response.ok) {
        throw new Error(data.detail ?? `HTTP ${response.status}`)
      }
      console.log('VERIFY RESPONSE:', data)
      setReport(data)
    } catch (err) {
      setError(err.message || 'Verification failed.')
    } finally {
      setLoading(false)
    }
  }

  const handleLoadedReport = (data) => {
    setError('')
    setReport(data)
  }

  const summary = report?.summary ?? {
    total: 0,
    proven: 0,
    failed: 0,
    unproven: 0,
  }

  const results = report?.results ?? report?.requirements ?? []

  return (
    <div className="min-h-screen bg-gray-100">
      <header className="bg-gray-900 text-white">
        <div className="max-w-6xl mx-auto px-6 py-6">
          <h1 className="text-2xl font-bold">
            Requirement-to-Code Verifier
          </h1>
          <p className="mt-1 text-sm text-gray-300">
            Verify whether software changes actually satisfy the developer's
            requirements.
          </p>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8">
        <section className="bg-white border border-gray-200 rounded-lg shadow-sm p-6">
          <h2 className="text-lg font-semibold text-gray-800">
            Verify a Software Change
          </h2>

          <p className="mt-1 text-sm text-gray-500">
            Enter the original developer requirements. The system will trace
            them through the implementation, tests, execution, and evidence.
          </p>

          <textarea
            value={requirements}
            onChange={(e) => {
              setRequirements(e.target.value)
              setError('')
            }}
            placeholder={`Example:
- Password reset token must expire after 15 minutes
- Token must be single-use
- Previous reset tokens must be invalidated`}
            rows={8}
            className="mt-4 w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 resize-y"
          />

          <div className="mt-4 flex items-center gap-3">
            <button
              type="button"
              onClick={handleVerify}
              disabled={loading || !requirements.trim()}
              className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-md disabled:opacity-50 transition-colors"
            >
              {loading ? 'Verifying...' : 'Verify Requirements'}
            </button>

            {loading && (
              <span className="text-sm text-gray-500">
                Running verification pipeline...
              </span>
            )}
          </div>

          {error && (
            <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-md">
              <p className="text-sm text-red-700">{error}</p>
            </div>
          )}

          <ReportLookup onLoaded={handleLoadedReport} />
        </section>

        {report && (
          <section className="mt-8">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-semibold text-gray-800">
                  Verification Report
                </h2>

                {report.job_id && (
                  <p className="text-xs text-gray-500 mt-1">
                    Job ID:{' '}
                    <span className="font-mono">{report.job_id}</span>
                  </p>
                )}
              </div>

              {report.verdict && (
                <span className="px-3 py-1 rounded-full text-xs font-bold bg-gray-100 text-gray-700">
                  {report.verdict}
                </span>
              )}
            </div>

            <SummaryBar summary={summary} />

            <div className="space-y-4">
              {results.length > 0 ? (
                results.map((result, index) => (
                  <ResultCard
                    key={result.id ?? index}
                    result={result}
                  />
                ))
              ) : (
                <div className="bg-white border border-gray-200 rounded-lg p-6 text-center text-sm text-gray-500">
                  No requirement results were returned.
                </div>
              )}
            </div>
          </section>
        )}
      </main>
    </div>
  )
}

export default App