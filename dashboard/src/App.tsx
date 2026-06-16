import React, { useState } from 'react'
import { BarChart2, Zap, BrainCircuit, Activity, Grid3x3, Waves, GraduationCap } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Positions from './pages/Positions'
import Signals from './pages/Signals'
import Committee from './pages/Committee'
import Whales from './pages/Whales'
import Lessons from './pages/Lessons'

type Page = 'dashboard' | 'positions' | 'signals' | 'committee' | 'whales' | 'lessons'

const NAV = [
  { id: 'dashboard',  label: 'Dashboard',  icon: BarChart2 },
  { id: 'positions',  label: 'Positions',  icon: Zap },
  { id: 'signals',    label: 'Signals',    icon: BrainCircuit },
  { id: 'committee',  label: 'Committee',  icon: Grid3x3 },
  { id: 'whales',     label: 'Whales',     icon: Waves },
  { id: 'lessons',    label: 'Lessons',    icon: GraduationCap },
]

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')

  return (
    <div className="min-h-screen bg-[#060C18] flex">
      <aside className="w-56 bg-[#0D1526] border-r border-[#1A2740] flex flex-col fixed h-full hidden md:flex">
        <div className="px-5 py-5 border-b border-[#1A2740]">
          <div className="flex items-center gap-2">
            <Activity size={20} className="text-[#3BD6AC]" />
            <span className="font-bold text-white text-lg">PolyMind</span>
          </div>
          <p className="text-[#6B7FA3] text-xs mt-0.5">AI Trading Agent</p>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setPage(id as Page)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                page === id
                  ? 'bg-[#167D6F]/30 text-[#3BD6AC] border border-[#167D6F]/40'
                  : 'text-[#6B7FA3] hover:text-white hover:bg-[#1A2740]'
              }`}
            >
              <Icon size={16} />
              {label}
            </button>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-[#1A2740]">
          <p className="text-[#6B7FA3] text-xs font-mono">
            Powered by Virtuals AI
          </p>
        </div>
      </aside>

      <div className="flex-1 md:ml-56">
        <header className="bg-[#0D1526] border-b border-[#1A2740] px-6 py-3 flex items-center justify-between md:hidden">
          <div className="flex items-center gap-2">
            <Activity size={18} className="text-[#3BD6AC]" />
            <span className="font-bold text-white">PolyMind</span>
          </div>
          <div className="flex gap-2">
            {NAV.map(({ id, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setPage(id as Page)}
                className={`p-2 rounded-lg ${
                  page === id ? 'text-[#3BD6AC] bg-[#167D6F]/20' : 'text-[#6B7FA3]'
                }`}
              >
                <Icon size={18} />
              </button>
            ))}
          </div>
        </header>

        <main className="p-6 max-w-5xl mx-auto">
          {page === 'dashboard' && <Dashboard />}
          {page === 'positions' && <Positions />}
          {page === 'signals'   && <Signals />}
          {page === 'committee' && <Committee />}
          {page === 'whales'    && <Whales />}
          {page === 'lessons'   && <Lessons />}
        </main>
      </div>
    </div>
  )
}
