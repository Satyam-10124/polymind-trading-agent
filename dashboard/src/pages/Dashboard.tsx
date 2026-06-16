import React from 'react'
import { TrendingUp, DollarSign, Target, Activity, Zap, BarChart2 } from 'lucide-react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts'
import StatCard from '../components/StatCard'
import { useStatus, usePositions, useEquity } from '../hooks/useApi'

function pnlColor(val: number) {
  return val > 0 ? 'green' : val < 0 ? 'red' : 'default'
}

export default function Dashboard() {
  const { data: status, loading } = useStatus()
  const { data: openPos } = usePositions('open')
  const { data: equity } = useEquity()

  const chartData = (equity || []).map((p: any) => ({
    name: p.date,
    equity: p.equity,
    pnl: p.pnl,
  }))

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-[#3BD6AC] font-mono animate-pulse">Loading PolyMind...</div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-[#6B7FA3] text-sm mt-1">Live performance overview</p>
        </div>
        <span className={`px-3 py-1 rounded-full text-xs font-mono font-semibold ${
          status?.paper_mode
            ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
            : 'bg-red-500/20 text-red-400 border border-red-500/30'
        }`}>
          {status?.paper_mode ? '📄 PAPER MODE' : '🔴 LIVE'}
        </span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Wallet Balance"
          value={`$${(status?.wallet_balance ?? 0).toFixed(2)}`}
          sub="USDC on Polygon"
          icon={<DollarSign size={13} />}
          color="teal"
        />
        <StatCard
          label="Total PnL"
          value={`$${(status?.total_pnl ?? 0).toFixed(2)}`}
          sub="All time"
          icon={<TrendingUp size={13} />}
          color={pnlColor(status?.total_pnl ?? 0)}
        />
        <StatCard
          label="Win Rate"
          value={`${status?.win_rate ?? 0}%`}
          sub={`${status?.wins ?? 0}W / ${status?.losses ?? 0}L`}
          icon={<Target size={13} />}
          color={(status?.win_rate ?? 0) >= 55 ? 'green' : 'red'}
        />
        <StatCard
          label="Total Trades"
          value={status?.total_trades ?? 0}
          sub={`${status?.open_positions ?? 0} open now`}
          icon={<Activity size={13} />}
        />
      </div>

      <div className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <BarChart2 size={16} className="text-[#3BD6AC]" />
          <span className="text-white font-semibold">Equity Curve</span>
          <span className="text-[#6B7FA3] text-xs ml-auto">daily, live</span>
        </div>
        {chartData.length > 1 ? (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#3BD6AC" stopOpacity={0.4} />
                  <stop offset="100%" stopColor="#3BD6AC" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#1A2740" />
              <XAxis dataKey="name" tick={{ fill: '#6B7FA3', fontSize: 11 }} />
              <YAxis tick={{ fill: '#6B7FA3', fontSize: 11 }} domain={['auto', 'auto']} />
              <Tooltip
                contentStyle={{ background: '#0D1526', border: '1px solid #1A2740', borderRadius: 8 }}
                labelStyle={{ color: '#6B7FA3' }}
                formatter={(v: any, n: any) => [`$${v}`, n === 'equity' ? 'Equity' : 'Daily PnL']}
              />
              <Area type="monotone" dataKey="equity" stroke="#3BD6AC" strokeWidth={2}
                    fill="url(#eq)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[220px] flex items-center justify-center text-[#6B7FA3]">
            No closed trades yet — equity curve builds as trades resolve
          </div>
        )}
      </div>

      <div className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Zap size={16} className="text-[#3BD6AC]" />
          <span className="text-white font-semibold">Open Positions ({openPos.length})</span>
        </div>
        {openPos.length === 0 ? (
          <p className="text-[#6B7FA3] text-sm">No open positions</p>
        ) : (
          <div className="space-y-3">
            {openPos.slice(0, 5).map((p: any) => (
              <div key={p.id} className="flex items-center justify-between py-2 border-b border-[#1A2740] last:border-0">
                <div className="flex-1 min-w-0">
                  <p className="text-white text-sm truncate">{p.question}</p>
                  <p className="text-[#6B7FA3] text-xs mt-0.5">
                    {p.direction} @ {(+p.entry_price * 100).toFixed(1)}¢ · {p.whale_name} · Score: {p.claude_score}/10
                  </p>
                </div>
                <div className="ml-4 text-right">
                  <span className="text-xs font-mono text-[#3BD6AC]">${(+p.size).toFixed(2)}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
