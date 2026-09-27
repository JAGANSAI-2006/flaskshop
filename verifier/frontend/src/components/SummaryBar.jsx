/**
 * SummaryBar — 4-cell grid showing Total / PROVEN / FAILED / UNPROVEN counts
 */
export default function SummaryBar({ summary }) {
  const { proven, failed, unproven, total } = summary
  const cells = [
    { label: 'Total',    value: total,    bg: 'bg-blue-50',   text: 'text-blue-800',   border: 'border-blue-200'   },
    { label: 'PROVEN',   value: proven,   bg: 'bg-green-50',  text: 'text-green-800',  border: 'border-green-200'  },
    { label: 'FAILED',   value: failed,   bg: 'bg-red-50',    text: 'text-red-800',    border: 'border-red-200'    },
    { label: 'UNPROVEN', value: unproven, bg: 'bg-yellow-50', text: 'text-yellow-800', border: 'border-yellow-200' },
  ]
  return (
    <div className="grid grid-cols-4 gap-3 mb-6">
      {cells.map(({ label, value, bg, text, border }) => (
        <div key={label} className={`${bg} ${border} border rounded-lg p-4 text-center`}>
          <p className={`text-3xl font-bold ${text}`}>{value}</p>
          <p className={`text-xs font-semibold mt-1 ${text} opacity-70`}>{label}</p>
        </div>
      ))}
    </div>
  )
}
