import { useState } from 'react'

/**
 * Collapsible section wrapper used inside ResultCard
 */
function Section({ title, children, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="mt-2 border border-gray-200 rounded-md overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex justify-between items-center px-3 py-2 text-xs font-semibold text-gray-500 bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <span>{title}</span>
        <span className="text-gray-400">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="px-3 py-3 bg-white">{children}</div>}
    </div>
  )
}

/**
 * ResultCard — displays one RequirementResult with expandable detail sections
 */
import VerdictBadge from './VerdictBadge.jsx'

export default function ResultCard({ result }) {
  const leftBorder = {
    PROVEN:   'border-l-4 border-l-green-500',
    FAILED:   'border-l-4 border-l-red-500',
    UNPROVEN: 'border-l-4 border-l-yellow-400',
  }[result.verdict] ?? 'border-l-4 border-l-gray-300'

  const hasContract   = result.contract?.summary
  const hasTracedCode = result.traced_code?.length > 0
  const hasTest       = result.generated_test?.trim().length > 10
  const hasOutput     = result.execution_output?.trim()
  const hasError      = result.error?.trim()

  return (
    <div className={`bg-white rounded-lg border border-gray-200 shadow-sm p-4 ${leftBorder}`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <span className="text-xs font-mono text-gray-400 mr-2">{result.id}</span>
          <span className="text-sm font-medium text-gray-800">{result.raw}</span>
        </div>
        <div className="shrink-0">
          <VerdictBadge verdict={result.verdict} />
        </div>
      </div>

      {/* Evidence summary */}
      {result.evidence_summary && (
        <p className="mt-2 text-xs text-gray-600 leading-relaxed">
          {result.evidence_summary}
        </p>
      )}

      {/* Error banner */}
      {hasError && (
        <p className="mt-2 text-xs text-red-600 bg-red-50 rounded px-2 py-1 font-mono break-words">
          {result.error}
        </p>
      )}

      {/* ── Collapsible details ── */}

      {hasContract && (
        <Section title={`Intent Contract — strategy: ${result.contract.evidence_strategy ?? 'unknown'}`}>
          <div className="text-xs text-gray-700 space-y-1.5">
            <p>
              <span className="font-semibold">Summary:</span>{' '}
              {result.contract.summary}
            </p>
            {result.contract.acceptance_criteria?.length > 0 && (
              <div>
                <span className="font-semibold">Acceptance criteria:</span>
                <ul className="list-disc list-inside mt-0.5 space-y-0.5">
                  {result.contract.acceptance_criteria.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
            {result.contract.keywords?.length > 0 && (
              <p>
                <span className="font-semibold">Keywords:</span>{' '}
                {result.contract.keywords.join(', ')}
              </p>
            )}
            {result.contract.test_hint && (
              <p>
                <span className="font-semibold">Test hint:</span>{' '}
                {result.contract.test_hint}
              </p>
            )}
          </div>
        </Section>
      )}

      {hasTracedCode && (
        <Section title={`Traced code — ${result.traced_code.length} region(s)`}>
          <div className="space-y-3">
            {result.traced_code.map((region, i) => (
              <div key={i}>
                <p className="text-xs font-mono text-blue-700 mb-1">
                  {region.file}:{region.line_start}–{region.line_end}
                  <span className="ml-2 text-gray-400">score={region.score}</span>
                </p>
                <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-2 text-gray-700 leading-snug overflow-x-auto max-h-40 whitespace-pre-wrap break-words">
                  {region.snippet}
                </pre>
              </div>
            ))}
          </div>
        </Section>
      )}

      {hasTest && (
        <Section title="Generated test">
          <pre className="text-xs bg-gray-900 text-green-300 rounded p-3 overflow-x-auto max-h-64 whitespace-pre-wrap">
            {result.generated_test}
          </pre>
        </Section>
      )}

      {hasOutput && (
        <Section
          title="Execution output"
          defaultOpen={result.verdict === 'FAILED'}
        >
          <pre className="text-xs bg-gray-900 text-gray-200 rounded p-3 overflow-x-auto max-h-64 whitespace-pre-wrap">
            {result.execution_output}
          </pre>
        </Section>
      )}
    </div>
  )
}
