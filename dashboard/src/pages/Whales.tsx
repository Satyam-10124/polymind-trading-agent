import React from 'react'
import { Waves, TrendingUp, Clock, Layers } from 'lucide-react'
import { useWhales } from '../hooks/useApi'

function pct(v: number) {
  return `${(v * 100).toFixed(0)}%`
}

function CatRate({ name, rate }: { name: string; rate: number }) {
  const color =
    rate >= 0.65 ? 'text-green-400' : rate >= 0.5 ? 'text-yellow-400' : 'text-red-400'
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#0B1322] border border-[#1A2740] text-xs font-mono">
      <span className="text-[#6B7FA3]">{name}</span>
      <span className={color}>{pct(rate)}</span>
    </span>
  )
}

export default function Whales() {
  const { data: whales, loading } = useWhales()

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Waves size={22} className="text-[#3BD6AC]" />
        <div>
          <h1 className="text-2xl font-bold text-white">Tracked Whales</h1>
          <p className="text-[#6B7FA3] text-sm">Profiled wallets, category win rates & behavior</p>
        </div>
      </div>

      {loading ? (
        <p className="text-[#6B7FA3]">Loading whales...</p>
      ) : whales.length === 0 ? (
        <p className="text-[#6B7FA3] text-sm">No whales profiled yet — bot is scanning the leaderboard</p>
      ) : (
        <div className="space-y-3">
          {whales.map((w: any) => {
            const cats = w.category_win_rates || {}
            return (
              <div key={w.wallet} className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-white font-semibold truncate">
                      {w.username || w.wallet?.slice(0, 10)}
                    </p>
                    <p className="text-[#6B7FA3] text-xs font-mono truncate">{w.wallet}</p>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-[#3BD6AC] font-mono font-bold">
                      ${Number(w.pnl || 0).toLocaleString()}
                    </p>
                    <p className="text-[#6B7FA3] text-xs">all-time PnL</p>
                  </div>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3 text-xs">
                  <div className="flex items-center gap-1 text-[#6B7FA3]">
                    <TrendingUp size={12} />
                    Win rate: <span className="text-white font-mono">{pct(w.win_rate || 0)}</span>
                  </div>
                  <div className="flex items-center gap-1 text-[#6B7FA3]">
                    <Clock size={12} />
                    Hold: <span className="text-white font-mono">{(w.avg_hold_hours || 0).toFixed(0)}h</span>
                  </div>
                  <div className="flex items-center gap-1 text-[#6B7FA3]">
                    <Layers size={12} />
                    <span className="text-white font-mono">{w.conviction_signal || '—'}</span>
                  </div>
                  <div className="text-[#6B7FA3]">
                    Exit:{' '}
                    <span className="text-white font-mono">
                      {w.closes_early ? 'early' : 'to resolution'}
                    </span>
                  </div>
                </div>

                {Object.keys(cats).length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-3">
                    {Object.entries(cats).map(([name, rate]) => (
                      <CatRate key={name} name={name} rate={Number(rate)} />
                    ))}
                  </div>
                )}

                {Array.isArray(w.top_categories) && w.top_categories.length > 0 && (
                  <p className="text-[#6B7FA3] text-xs mt-2">
                    Focus: {w.top_categories.join(' · ')} · {w.total_trades || 0} trades · {w.recent_streak}
                  </p>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
