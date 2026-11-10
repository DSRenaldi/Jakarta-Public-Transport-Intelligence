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
    && sameJourneyLeg(left, right)
    && sameStop(left.to, right.from)
  )
}

function groupSegments(segments = [], crowdingSegments = []) {
  const legs = []
  let rideIndex = 0

  for (const raw of segments) {
    const segment = {
      ...raw,
      passedStops: raw.type === 'ride' ? [raw.to] : [],
      via: raw.via ? [...raw.via] : [],
      edgeCount: 1,
      crowd: raw.type === 'ride' ? (crowdingSegments[rideIndex] || null) : null,
    }
    if (raw.type === 'ride') rideIndex += 1

    const previous = legs.at(-1)
    if (sameRide(previous, segment)) {
      previous.to = segment.to
      previous.travel_sec = (previous.travel_sec || 0) + (segment.travel_sec || 0)
      previous.wait_sec = (previous.wait_sec || 0) + (segment.wait_sec || 0)
      previous.fare = (previous.fare || 0) + (segment.fare || 0)
      previous.passedStops.push(segment.to)
      previous.edgeCount += 1
      continue
    }

    if (previous?.type === 'walk' && segment.type === 'walk' && sameJourneyLeg(previous, segment) && sameStop(previous.to, segment.from)) {
      previous.via.push(previous.to, ...segment.via)
      previous.to = segment.to
      previous.walk_sec = (previous.walk_sec || 0) + (segment.walk_sec || 0)
      previous.edgeCount += 1
      continue
    }

    legs.push(segment)
  }

  return legs
}

/**
 * Susun leg untuk detail perjalanan. Itinerary API tetap menjadi sumber
 * ringkasan; edge mentah hanya melengkapi urutan pemberhentian dan crowding.
 */
export function buildRouteDetailData(result) {
  if (result?.status !== 'ok') return []

  const grouped = groupSegments(result.segments, result.crowding?.segments)
  if (!result.itinerary?.length || result.itinerary.length !== grouped.length) return grouped

  return result.itinerary.map((leg, index) => ({
    ...grouped[index],
    ...leg,
    passedStops: grouped[index].passedStops,
    edgeCount: leg.edge_count || grouped[index].edgeCount,
    crowd: grouped[index].crowd,
  }))
}
