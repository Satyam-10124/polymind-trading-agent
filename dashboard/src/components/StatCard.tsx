import React from 'react'

interface Props {
  label: string
  value: string | number
  sub?: string
  color?: 'green' | 'red' | 'teal' | 'default'
  icon?: React.ReactNode
}

export default function StatCard({ label, value, sub, color = 'default', icon }: Props) {
  const colorMap = {
    green:   'text-green-400',
    red:     'text-red-400',
    teal:    'text-teal-300',
    default: 'text-white',
  }
  return (
    <div className="bg-[#0D1526] border border-[#1A2740] rounded-xl p-5 flex flex-col gap-1">
      <div className="flex items-center gap-2 text-[#6B7FA3] text-xs font-medium uppercase tracking-wider">
        {icon}
        {label}
      </div>
      <div className={`text-2xl font-bold font-mono ${colorMap[color]}`}>{value}</div>
      {sub && <div className="text-[#6B7FA3] text-xs">{sub}</div>}
    </div>
  )
}
