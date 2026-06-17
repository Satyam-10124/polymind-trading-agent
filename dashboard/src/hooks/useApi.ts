import { useState, useEffect, useCallback } from 'react'

const BASE = '/api'

export function useStatus() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  const fetch_ = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/status`)
      setData(await r.json())
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    fetch_()
    const id = setInterval(fetch_, 15000)
    return () => clearInterval(id)
  }, [fetch_])

  return { data, loading, refetch: fetch_ }
}

export function usePositions(status = 'open') {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  const fetch_ = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}/positions?status=${status}`)
      setData(await r.json())
    } catch { setData([]) }
    finally { setLoading(false) }
  }, [status])

  useEffect(() => {
    fetch_()
    const id = setInterval(fetch_, 15000)
    return () => clearInterval(id)
  }, [fetch_])

  return { data, loading, refetch: fetch_ }
}

export function useHistory() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`${BASE}/history?limit=50`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])

  return { data, loading }
}

export function useSignals() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`${BASE}/signals`)
      .then(r => r.json())
      .then(setData)
      .catch(() => setData([]))
      .finally(() => setLoading(false))
  }, [])

  return { data, loading }
}

/** Generic polling fetch for the new pages. */
function usePoll<T>(path: string, fallback: T, intervalMs = 20000) {
  const [data, setData] = useState<T>(fallback)
  const [loading, setLoading] = useState(true)

  const fetch_ = useCallback(async () => {
    try {
      const r = await fetch(`${BASE}${path}`)
      setData(await r.json())
    } catch { /* keep previous */ }
    finally { setLoading(false) }
  }, [path])

  useEffect(() => {
    fetch_()
    const id = setInterval(fetch_, intervalMs)
    return () => clearInterval(id)
  }, [fetch_, intervalMs])

  return { data, loading, refetch: fetch_ }
}

export function useWhales() {
  return usePoll<any[]>('/whales', [])
}

export function useCommitteeReports() {
  return usePoll<any[]>('/committee', [])
}

export function useLessons(category = 'all') {
  return usePoll<any[]>(`/lessons?category=${category}`, [])
}

export function useEquity() {
  return usePoll<any[]>('/equity', [])
}

export function useBacktests() {
  return usePoll<any[]>('/backtests', [], 30000)
}

export function useCalibration() {
  return usePoll<any>('/calibration', { n_samples: 0, factor: 1, curve: [] }, 30000)
}
