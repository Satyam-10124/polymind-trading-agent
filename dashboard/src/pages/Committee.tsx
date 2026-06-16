import React from 'react'
import { Grid3x3 } from 'lucide-react'
import { useCommitteeReports } from '../hooks/useApi'

// Each column is one committee agent; we extract a 0-10 score from its report.
const AGENTS: { key: string; label: string; score: (r: any) => number | null }[] = [
  { key: 'whale_intent', label: 'Whale Intent', score: r => num(r.whale_intent?.intent_score) ?? scale(r.whale_intent?.alpha_confidence) },
  { key: 'efficiency',   label: 'Efficiency',   score: r => invert(num(r.efficiency?.efficiency_score)) },
  { key: 'archetype',    label: 'Archetype',    score: r => r.archetype?.recommended_max_hold_days != null ? 6 : null },
  { key: 'cro',          label: 'CRO Risk',     score: r => invertPct(r.cro?.rejection_risk_pct ?? r.cro?.rejection_probability) },
  { key: 'portfolio',    label: 'Portfolio',    score: r => num(r.portfolio?.diversification_score) },
  { key: 'sizing',       label: 'Sizing',       score: r => scaleFrac(r.sizing?.kelly_fraction) },
  { key: 'conviction',   label: 'Verdict',      score: r => num(r.conviction) },
]

function num(v: any): number | null {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
function scale(pct: any): number | null { const n = Number(pct); return Number.isFinite(n) ? n / 10 : null }
function scaleFrac(f: any): number | null { const n = Number(f); return Number.isFinite(n) ? n * 10 : null }
function invert(s: number | null): number | null { return s == null ? null : 11 - s }
function invertPct(pct: any): number | null { const n = Number(pct); return Number.isFinite(n) ? (100 - n) / 10 : null }

function cellColor(score: number | null): string {
  if (score == null) return 'bg-[#0B1322] text-[#3A4868]'
  if (score >= 7.5) return 'bg-green-500/30 text-green-300'
  if (score >= 5) return 'bg-yellow-500/25 text-yellow-300'
  if (score >= 3) return 'bg-orange-500/25 text-orange-300'
  return 'bg-red-500/30 text-red-300'
}

export default function Committee() {
  const { data: reports, loading } = useCommitteeReports()

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Grid3x3 size={22} className="text-[#3BD6AC]" />
        <div>
          <h1 className="text-2xl font-bold text-white">Committee Heatmap</h1>
          <p className="text-[#6B7FA3] text-sm">Per-agent scores for every analyzed trade (0–10, green = favorable)</p>
        </div>
      </div>

      {loading ? (
        <p className="text-[#6B7FA3]">Loading committee reports...</p>
      ) : reports.length === 0 ? (
        <p className="text-[#6B7FA3] text-sm">No committee reports yet</p>
      ) : (
        <div className="overflow-x-auto bg-[#0D1526] border border-[#1A2740] rounded-xl p-4">
          <table className="w-full text-sm border-separate" style={{ borderSpacing: '4px' }}>
            <thead>
              <tr className="text-[#6B7FA3] text-xs uppercase tracking-wider">
                <th className="text-left font-medium pr-3">Market</th>
                {AGENTS.map(a => (
                  <th key={a.key} className="px-1 font-medium whitespace-nowrap">{a.label}</th>
                ))}
                <th className="px-1 font-medium">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r: any) => (
                <tr key={r.id}>
                  <td className="text-white text-xs max-w-[200px] truncate pr-3">{r.question}</td>
                  {AGENTS.map(a => {
                    const s = a.score(r)
                    return (
                      <td key={a.key} className="text-center">
                        <div className={`rounded-md py-1.5 font-mono text-xs font-semibold ${cellColor(s)}`}>
                          {s == null ? '–' : s.toFixed(1)}
                        </div>
                      </td>
                    )
                  })}
                  <td className="text-center">
                    <span className={`px-2 py-0.5 rounded text-xs font-mono ${
                      r.verdict === 'APPROVE' ? 'bg-green-500/20 text-green-400'
                        : r.verdict === 'WATCH' ? 'bg-yellow-500/20 text-yellow-400'
                        : 'bg-red-500/20 text-red-400'
                    }`}>
                      {r.verdict || '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
