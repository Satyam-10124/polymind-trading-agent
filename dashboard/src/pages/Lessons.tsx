import React, { useState } from 'react'
import { GraduationCap } from 'lucide-react'
import { useLessons } from '../hooks/useApi'

const CATEGORIES = ['all', 'politics', 'crypto', 'sports', 'science', 'other']

export default function Lessons() {
  const [category, setCategory] = useState('all')
  const { data: lessons, loading } = useLessons(category)

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <GraduationCap size={22} className="text-[#3BD6AC]" />
        <div>
          <h1 className="text-2xl font-bold text-white">Lessons Learned</h1>
          <p className="text-[#6B7FA3] text-sm">Post-mortem insights fed back into the committee</p>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {CATEGORIES.map(c => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={`px-3 py-1 rounded-full text-xs font-mono transition-colors ${
              category === c
                ? 'bg-[#167D6F]/30 text-[#3BD6AC] border border-[#167D6F]/40'
                : 'text-[#6B7FA3] border border-[#1A2740] hover:text-white'
            }`}
          >
            {c}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="text-[#6B7FA3]">Loading lessons...</p>
      ) : lessons.length === 0 ? (
        <p className="text-[#6B7FA3] text-sm">No lessons for this category yet</p>
      ) : (
        <div className="space-y-3">
          {lessons.map((l: any) => {
            const helped = (l.reduced_losses || 0) > (l.ignored || 0)
            const status =
              l.applied_count > 0
                ? helped ? { t: '✅ reduced losses', c: 'text-green-400' }
                         : { t: '⚠️ ignored', c: 'text-orange-400' }
                : { t: '• new', c: 'text-[#6B7FA3]' }
            return (
              <div key={l.id} className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-4">
                <div className="flex items-center justify-between gap-3 mb-1">
                  <span className="px-2 py-0.5 rounded text-xs font-mono bg-[#167D6F]/20 text-[#3BD6AC]">
                    {l.category}
                  </span>
                  <div className="flex items-center gap-3 text-xs font-mono">
                    <span className={status.c}>{status.t}</span>
                    <span className={Number(l.pnl) >= 0 ? 'text-green-400' : 'text-red-400'}>
                      {Number(l.pnl) >= 0 ? '+' : ''}${Number(l.pnl || 0).toFixed(2)}
                    </span>
                  </div>
                </div>
                <p className="text-white text-sm">{l.lesson}</p>
                {l.future_rule && (
                  <p className="text-[#6B7FA3] text-xs mt-1">
                    <span className="text-[#3BD6AC]">Rule →</span> {l.future_rule}
                  </p>
                )}
                <div className="flex gap-3 mt-2 text-xs text-[#6B7FA3] font-mono">
                  <span>{l.edge_was_real ? 'real edge' : 'phantom edge'}</span>
                  <span>·</span>
                  <span>{l.thesis_correct ? 'thesis correct' : 'thesis wrong'}</span>
                  {l.applied_count > 0 && <><span>·</span><span>applied {l.applied_count}×</span></>}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
