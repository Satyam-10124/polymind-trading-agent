import React from 'react'
import { useSignals } from '../hooks/useApi'

export default function Signals() {
  const { data, loading } = useSignals()

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Claude Signals</h1>
        <p className="text-[#6B7FA3] text-sm mt-1">Every market Claude analysed — traded or skipped</p>
      </div>

      {loading ? (
        <p className="text-[#6B7FA3]">Loading signals...</p>
      ) : data.length === 0 ? (
        <p className="text-[#6B7FA3] text-sm">No signals yet — bot is scanning markets</p>
      ) : (
        <div className="space-y-3">
          {data.map((s: any) => (
            <div
              key={s.id}
              className={`bg-[#0D1526] border rounded-xl p-4 ${
                s.action === 'trade'
                  ? 'border-[#3BD6AC]/40'
                  : 'border-[#1A2740]'
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className={`px-2 py-0.5 rounded text-xs font-mono font-bold ${
                      s.action === 'trade'
                        ? 'bg-[#3BD6AC]/20 text-[#3BD6AC]'
                        : 'bg-[#6B7FA3]/20 text-[#6B7FA3]'
                    }`}>
                      {s.action === 'trade' ? '✅ TRADED' : '⏭ SKIPPED'}
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs font-mono ${
                      s.direction === 'YES'
                        ? 'bg-green-500/20 text-green-400'
                        : s.direction === 'NO'
                        ? 'bg-red-500/20 text-red-400'
                        : 'bg-[#6B7FA3]/20 text-[#6B7FA3]'
                    }`}>
                      {s.direction}
                    </span>
                    <span className="text-[#6B7FA3] text-xs font-mono">
                      Score: {s.score}/10 · Edge: {s.edge > 0 ? '+' : ''}{(+(s.edge || 0)).toFixed(3)}
                    </span>
                  </div>
                  <p className="text-white text-sm">{s.question}</p>
                  {s.reasoning && (
                    <p className="text-[#6B7FA3] text-xs mt-2 italic">{s.reasoning}</p>
                  )}
                  {s.key_facts && (() => {
                    try {
                      const facts = JSON.parse(s.key_facts)
                      return facts.length > 0 ? (
                        <ul className="mt-2 space-y-0.5">
                          {facts.map((f: string, i: number) => (
                            <li key={i} className="text-[#6B7FA3] text-xs flex gap-1">
                              <span className="text-[#3BD6AC]">›</span>
                              {f}
                            </li>
                          ))}
                        </ul>
                      ) : null
                    } catch { return null }
                  })()}
                </div>
                <div className="text-right text-xs text-[#6B7FA3] font-mono shrink-0">
                  {new Date(s.created_at).toLocaleTimeString()}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
