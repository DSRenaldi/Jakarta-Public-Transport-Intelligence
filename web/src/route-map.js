function stopKey(stop) {
  if (!stop) return null
  return stop.stop_id || `${stop.lat}:${stop.lon}:${stop.display || stop.name || ''}`
}

function sameStop(left, right) {
  return Boolean(stopKey(left) && stopKey(left) === stopKey(right))
}

function sameJourneyLeg(left, right) {
  return (left?.journey_leg || null) === (right?.journey_leg || null)
}

function sameRide(left, right) {
  return Boolean(
    left?.type === 'ride'
    && right?.type === 'ride'
    && left.mode === right.mode
    && left.line_id === right.line_id
    && left.route_id === right.route_id
    && sameJourneyLeg(left, right)
    && sameStop(left.to, right.from)
  )
}

function collapseSegments(segments = []) {
  const legs = []
  for (const raw of segments) {
    const segment = { ...raw, via: [] }
    const previous = legs.at(-1)
    if (sameRide(previous, segment)) {
      previous.to = segment.to
      previous.travel_sec = (previous.travel_sec || 0) + (segment.travel_sec || 0)
      previous.wait_sec = (previous.wait_sec || 0) + (segment.wait_sec || 0)
      continue
    }
    if (previous?.type === 'walk' && segment.type === 'walk' && sameJourneyLeg(previous, segment) && sameStop(previous.to, segment.from)) {
      previous.via.push(previous.to, ...(segment.via || []))
      previous.to = segment.to
      previous.walk_sec = (previous.walk_sec || 0) + (segment.walk_sec || 0)
      continue
    }
    legs.push(segment)
  }
  return legs
}

export function serviceLabel(leg) {
  if (!leg || leg.type !== 'ride') return 'layanan berikutnya'
  const service = leg.corridor || leg.line || leg.mode || 'layanan'
  return String(service).toLocaleLowerCase('id-ID').startsWith(String(leg.mode || '').toLocaleLowerCase('id-ID'))
    ? String(service)
    : `${leg.mode} ${service}`
}

function changeKind(before, after) {
  if (before.mode !== after.mode) return {
    kind: 'mode',
    title: `Ganti moda ${before.mode} ke ${after.mode}`,
  }
  if (before.line_id !== after.line_id) return {
    kind: 'line',
    title: `Pindah jalur ${before.mode}`,
  }
  return {
    kind: 'service',
    title: `Pindah layanan ${before.mode}`,
  }
}

function uniqueStops(stops, excludedKeys = new Set()) {
  const seen = new Set(excludedKeys)
  return stops.filter((stop) => {
    const key = stopKey(stop)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

/**
 * Bentuk marker perpindahan dari urutan leg, bukan dari daftar pasangan moda.
 * Karena itu semua kombinasi MRT/KRL/LRT/BRT dan perubahan jalur otomatis ikut.
 */
export function buildRouteMapData(result) {
  const legs = result?.itinerary?.length ? result.itinerary : collapseSegments(result?.segments)
  const rideIndexes = legs
    .map((leg, index) => (leg.type === 'ride' ? index : -1))
    .filter((index) => index >= 0)
  const transfers = []
  const waypointCandidates = []
  let transferNumberCounter = 0

  for (const leg of legs) {
    if (leg.type === 'walk') waypointCandidates.push(...(leg.via || []))
  }

  for (let ridePosition = 0; ridePosition < rideIndexes.length - 1; ridePosition += 1) {
    const beforeIndex = rideIndexes[ridePosition]
    const afterIndex = rideIndexes[ridePosition + 1]
    const before = legs[beforeIndex]
    const after = legs[afterIndex]
    if (!sameJourneyLeg(before, after)) continue
    const between = legs.slice(beforeIndex + 1, afterIndex)
    const walkingLegs = between.filter((leg) => leg.type === 'walk')
    const change = changeKind(before, after)
    const transferNumber = ++transferNumberCounter
    const exitStop = before.to
    const entryStop = after.from
    const walkingSeconds = walkingLegs.reduce((total, leg) => total + (leg.walk_sec || 0), 0)
    const common = {
      event: transferNumber,
      kind: change.kind,
      title: change.title,
      fromMode: before.mode,
      toMode: after.mode,
      fromService: serviceLabel(before),
      toService: serviceLabel(after),
      walkingSeconds,
    }

    if (sameStop(exitStop, entryStop)) {
      transfers.push({
        ...common,
        label: String(transferNumber),
        phase: 'direct',
        stop: exitStop,
        instruction: `Turun dari ${serviceLabel(before)}, lalu naik ${serviceLabel(after)}.`,
      })
      continue
    }

    transfers.push({
      ...common,
      label: `${transferNumber}A`,
      phase: 'exit',
      stop: exitStop,
      instruction: `Turun dari ${serviceLabel(before)} dan mulai berjalan ke titik keberangkatan berikutnya.`,
    })
    transfers.push({
      ...common,
      label: `${transferNumber}B`,
      phase: 'entry',
      stop: entryStop,
      instruction: `Selesai berjalan, lalu naik ${serviceLabel(after)}.`,
    })
  }

  const transferKeys = new Set(transfers.map((point) => stopKey(point.stop)))
  transferKeys.add(stopKey(result?.origin))
  transferKeys.add(stopKey(result?.dest))
  const endpointKeys = new Set([stopKey(result?.origin), stopKey(result?.dest)])
  const journeyWaypoints = uniqueStops((result?.points || []).slice(1, -1), endpointKeys)

  return {
    legs,
    transfers,
    waypoints: uniqueStops(waypointCandidates, transferKeys),
    journeyWaypoints,
    transferCount: new Set(transfers.map((point) => point.event)).size,
  }
}
