import React from 'react'
import { usePositions } from '../hooks/useApi'

function badge(direction: string) {
  return direction === 'YES'
    ? 'bg-green-500/20 text-green-400 border border-green-500/30'
    : 'bg-red-500/20 text-red-400 border border-red-500/30'
}

export default function Positions() {
  const { data: open, loading: oL } = usePositions('open')
  const { data: all, loading: aL } = usePositions('closed')

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">Positions</h1>

      <section>
        <h2 className="text-[#6B7FA3] text-xs uppercase tracking-wider mb-3">
          Open ({open.length})
        </h2>
        {oL ? (
          <p className="text-[#6B7FA3]">Loading...</p>
        ) : open.length === 0 ? (
          <p className="text-[#6B7FA3] text-sm">No open positions</p>
        ) : (
          <div className="space-y-3">
            {open.map((p: any) => (
              <div key={p.id} className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <p className="text-white text-sm font-medium">{p.question}</p>
                    <p className="text-[#6B7FA3] text-xs mt-1">
                      Whale: <span className="text-[#3BD6AC]">{p.whale_name}</span> · Score: {p.claude_score}/10
                    </p>
                    {p.reasoning && (
                      <p className="text-[#6B7FA3] text-xs mt-1 italic line-clamp-2">{p.reasoning}</p>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <span className={`px-2 py-0.5 rounded text-xs font-mono ${badge(p.direction)}`}>
                      {p.direction}
                    </span>
                    <p className="text-white text-sm font-mono mt-1">${(+p.size).toFixed(2)}</p>
                    <p className="text-[#6B7FA3] text-xs">@ {(+p.entry_price * 100).toFixed(1)}¢</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <h2 className="text-[#6B7FA3] text-xs uppercase tracking-wider mb-3">
          Closed ({all.length})
        </h2>
        {aL ? (
          <p className="text-[#6B7FA3]">Loading...</p>
        ) : all.length === 0 ? (
          <p className="text-[#6B7FA3] text-sm">No closed trades yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[#6B7FA3] text-xs uppercase tracking-wider border-b border-[#1A2740]">
                  <th className="text-left pb-2 pr-4">Market</th>
                  <th className="text-left pb-2 pr-4">Side</th>
                  <th className="text-right pb-2 pr-4">Entry</th>
                  <th className="text-right pb-2 pr-4">Exit</th>
                  <th className="text-right pb-2 pr-4">Size</th>
                  <th className="text-right pb-2">PnL</th>
                </tr>
              </thead>
              <tbody>
                {all.map((t: any) => (
                  <tr key={t.id} className="border-b border-[#1A2740] last:border-0">
                    <td className="py-2 pr-4 text-white max-w-xs truncate">{t.question}</td>
                    <td className="py-2 pr-4">
                      <span className={`px-2 py-0.5 rounded text-xs font-mono ${badge(t.direction)}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-[#6B7FA3]">
                      {(+(t.entry_price || 0) * 100).toFixed(1)}¢
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-[#6B7FA3]">
                      {t.exit_price ? (+(t.exit_price) * 100).toFixed(1) + '¢' : '—'}
                    </td>
                    <td className="py-2 pr-4 text-right font-mono text-white">${(+t.size).toFixed(2)}</td>
                    <td className={`py-2 text-right font-mono font-semibold ${
                      +(t.pnl || 0) > 0 ? 'text-green-400' : +(t.pnl || 0) < 0 ? 'text-red-400' : 'text-[#6B7FA3]'
                    }`}>
                      {+(t.pnl || 0) >= 0 ? '+' : ''}${(+(t.pnl || 0)).toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
