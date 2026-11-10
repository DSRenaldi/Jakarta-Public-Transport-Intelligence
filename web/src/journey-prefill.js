export function resolvedJourneyPrefill(message) {
  const journey = message?.journey
  if (!journey?.origin?.stop_id || !journey?.dest?.stop_id) return null
  const points = journey.points?.length ? journey.points : [journey.origin, journey.dest]
  if (points.length < 2 || points.some((point) => !point?.stop_id)) return null
  return { ...journey, points, waypoints: points.slice(1, -1) }
}

export function prefillStopLabel(stop) {
  if (typeof stop === 'string') return stop
  return stop?.display || stop?.name || ''
}

export function pickPrefillCandidate(response, target) {
  const candidates = response?.candidates || []
  if (!target) return null

  if (typeof target === 'object' && target.stop_id) {
    const byId = candidates.find((candidate) => candidate.stop_id === target.stop_id)
    if (byId) return byId
  }

  const label = prefillStopLabel(target)
  const wanted = label.trim().toLocaleLowerCase('id-ID')
  const wantedMode = typeof target === 'object' ? target.mode : null
  const exact = candidates.filter((candidate) => [candidate.display, candidate.name]
    .filter(Boolean)
    .some((name) => name.trim().toLocaleLowerCase('id-ID') === wanted))
  return exact.find((candidate) => !wantedMode || candidate.mode === wantedMode)
    || (candidates.length === 1 ? candidates[0] : null)
}
