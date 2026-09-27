/**
 * VerdictBadge — coloured pill showing PROVEN / FAILED / UNPROVEN
 */
export default function VerdictBadge({ verdict }) {
  const styles = {
    PROVEN:   'bg-green-100 text-green-800 border-green-300',
    FAILED:   'bg-red-100   text-red-800   border-red-300',
    UNPROVEN: 'bg-yellow-100 text-yellow-800 border-yellow-300',
  }
  const icons = { PROVEN: '✓', FAILED: '✗', UNPROVEN: '?' }
  const cls = styles[verdict] ?? styles.UNPROVEN
  return (
    <span
      className={`inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-bold rounded-full border ${cls}`}
    >
      {icons[verdict] ?? '?'} {verdict}
    </span>
  )
}
