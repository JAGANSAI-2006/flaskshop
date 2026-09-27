import { useState } from 'react'

/**
 * ReportLookup — lets the user retrieve a previously run job by its job_id
 */
export default function ReportLookup({ onLoaded }) {
  const [jobId, setJobId]     = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState('')

  const fetchReport = async () => {
    const id = jobId.trim()
    if (!id) return
    setLoading(true)
    setError('')
    try {
      const resp = await fetch(`/report/${encodeURIComponent(id)}`)
      const data = await resp.json()
      if (!resp.ok) {
        throw new Error(data.detail ?? `HTTP ${resp.status}`)
      }
      onLoaded(data)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mt-4 p-4 bg-gray-50 border border-gray-200 rounded-lg">
      <p className="text-sm font-semibold text-gray-700 mb-2">
        Retrieve an existing report by Job ID
      </p>
      <div className="flex gap-2">
        <input
          type="text"
          value={jobId}
          onChange={e => { setJobId(e.target.value); setError('') }}
          onKeyDown={e => e.key === 'Enter' && fetchReport()}
          placeholder="e.g. a1b2c3d4e5f6"
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
        <button
          onClick={fetchReport}
          disabled={loading || !jobId.trim()}
          className="px-4 py-2 bg-gray-700 hover:bg-gray-900 text-white text-sm rounded-md disabled:opacity-50 transition-colors"
        >
          {loading ? (
            <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
          ) : (
            'Load'
          )}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
    </div>
  )
}
