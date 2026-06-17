import React from 'react'
import { FlaskConical } from 'lucide-react'
import { useBacktests, useCalibration } from '../hooks/useApi'

function Metric({ label, value, good }: { label: string; value: any; good?: boolean }) {
  const color = good === undefined ? 'text-white' : good ? 'text-green-400' : 'text-red-400'
  return (
    <div className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-3">
      <p className="text-[#6B7FA3] text-xs">{label}</p>
      <p className={`text-lg font-mono ${color}`}>{value}</p>
    </div>
  )
}

export default function Backtest() {
  const { data: runs, loading } = useBacktests()
  const { data: cal } = useCalibration()

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <FlaskConical size={22} className="text-[#3BD6AC]" />
        <div>
          <h1 className="text-2xl font-bold text-white">Backtest &amp; Calibration</h1>
          <p className="text-[#6B7FA3] text-sm">Out-of-sample validation and probability calibration</p>
        </div>
      </div>

      {/* ── Calibration curve ── */}
      <section className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-5">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-white font-semibold">Probability calibration</h2>
          <span className="text-xs font-mono text-[#6B7FA3]">
            {cal.n_samples} samples · trust factor{' '}
            <span className={cal.factor >= 0.8 ? 'text-green-400' : cal.factor >= 0.5 ? 'text-orange-400' : 'text-red-400'}>
              {Number(cal.factor).toFixed(2)}
            </span>
          </span>
        </div>
        <p className="text-[#6B7FA3] text-xs mb-4">
          Predicted vs realized win rate per bucket. If realized &lt; predicted, the committee is overconfident
          and its probability is shrunk toward the market before Kelly sizing.
        </p>
        {(!cal.curve || cal.curve.length === 0) ? (
          <p className="text-[#6B7FA3] text-sm">Not enough closed trades yet to build a calibration curve.</p>
        ) : (
          <div className="space-y-2">
            {cal.curve.map((b: any) => {
              const over = b.realized < b.predicted
              return (
                <div key={b.bucket} className="flex items-center gap-3 text-xs font-mono">
                  <span className="text-[#6B7FA3] w-16">{b.bucket}</span>
                  <div className="flex-1 h-5 bg-[#060C18] rounded relative overflow-hidden">
                    <div className="absolute h-full bg-[#3BD6AC]/40" style={{ width: `${b.predicted * 100}%` }} />
                    <div className="absolute h-full bg-[#3BD6AC]" style={{ width: `${b.realized * 100}%`, opacity: 0.85 }} />
                  </div>
                  <span className="text-[#6B7FA3] w-24">
                    pred {(b.predicted * 100).toFixed(0)}% / <span className={over ? 'text-red-400' : 'text-green-400'}>real {(b.realized * 100).toFixed(0)}%</span>
                  </span>
                  <span className="text-[#6B7FA3] w-10">n={b.n}</span>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* ── Backtest runs ── */}
      <section className="space-y-3">
        <h2 className="text-white font-semibold">Walk-forward runs</h2>
        {loading ? (
          <p className="text-[#6B7FA3]">Loading backtests...</p>
        ) : runs.length === 0 ? (
          <p className="text-[#6B7FA3] text-sm">
            No backtest runs yet. Ingest history (<span className="font-mono">python3 -m backtest.ingest</span>) then run{' '}
            <span className="font-mono">python3 -m backtest.engine</span>.
          </p>
        ) : (
          runs.map((r: any) => {
            const test = r.results?.test || {}
            const train = r.results?.train || {}
            return (
              <div key={r.id} className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-4">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-white font-mono text-sm">{r.label}</span>
                  <span className="text-[#6B7FA3] text-xs font-mono">
                    test: {r.test_start} → {r.test_end}
                  </span>
                </div>
                <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
                  <Metric label="Trades (OOS)" value={r.n_trades} />
                  <Metric label="Win rate" value={`${((r.win_rate || 0) * 100).toFixed(0)}%`} good={r.win_rate >= 0.5} />
                  <Metric label="ROI (OOS)" value={`${((r.roi || 0) * 100).toFixed(1)}%`} good={r.roi >= 0} />
                  <Metric label="Sharpe" value={Number(r.sharpe || 0).toFixed(2)} good={r.sharpe >= 0} />
                  <Metric label="Max DD" value={`${((r.max_drawdown || 0) * 100).toFixed(1)}%`} good={r.max_drawdown <= 0.2} />
                  <Metric label="Avg slippage" value={Number(r.avg_slippage || 0).toFixed(3)} />
                </div>
                {train.roi !== undefined && (
                  <p className="text-[#6B7FA3] text-xs mt-3 font-mono">
                    in-sample ROI {((train.roi || 0) * 100).toFixed(1)}% vs out-of-sample {((r.roi || 0) * 100).toFixed(1)}%
                    {train.roi > 0 && r.roi < train.roi * 0.5 && (
                      <span className="text-orange-400"> · ⚠ possible overfit</span>
                    )}
                  </p>
                )}
              </div>
            )
          })
        )}
      </section>
    </div>
  )
}
