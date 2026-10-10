"""Explainable interval packing, shared by live advice and offline experiments."""
from datetime import datetime, timedelta
import random

from .models import ParkingSlot, ParkingSession, Reservation, utcnow
from .services import vehicle_number


def containing_gap(start, end, intervals, lower, upper):
    """Find the free gap containing [start, end); touching bookings are legal."""
    if start < lower or end > upper or end <= start:
        return None
    left, right = lower, upper
    for busy_start, busy_end in intervals:
        if busy_start < end and busy_end > start:
            return None
        if busy_end <= start:
            left = max(left, busy_end)
        if busy_start >= end:
            right = min(right, busy_start)
    return left, right


def ranked_slots(schedules, start, end, lower, upper, strategy='best_fit'):
    candidates = []
    for slot_id, intervals in schedules.items():
        gap = containing_gap(start, end, intervals, lower, upper)
        if gap:
            candidates.append((slot_id, gap))
    if strategy == 'first_fit':
        return sorted(candidates, key=lambda item: item[0])
    # Smallest containing gap preserves larger continuous windows elsewhere.
    # A stable ID tie-break makes recommendations and experiments reproducible.
    return sorted(candidates, key=lambda item: (item[1][1] - item[1][0], item[0]))


def reservation_plan(start, end, vehicle=None):
    now = utcnow()
    if start < now or end <= start or start.date() != end.date():
        raise ValueError('Choose a future arrival and a later departure on the same UTC date, as required by reservation storage.')
    vehicle = vehicle_number(vehicle) if vehicle else None
    lower = datetime.combine(start.date(), datetime.min.time())
    upper = lower + timedelta(days=1)
    slots = ParkingSlot.query.order_by(ParkingSlot.id).all()
    busy_slots = {s.slot_id for s in ParkingSession.query.filter(
        ParkingSession.status.in_(['active', 'awaiting_entry']), ParkingSession.exit_time.is_(None)).all()}
    bookings = Reservation.query.filter(Reservation.status.in_(['confirmed', 'checked_in']),
                                        Reservation.reservation_date == start.date()).all()
    vehicle_intervals = [(r.starts_at, r.ends_at) for r in bookings if vehicle and r.vehicle_number == vehicle]
    schedules, reasons = {}, {}
    for slot in slots:
        if not slot.enabled or slot.status == 'disabled':
            reasons[slot.id] = 'Disabled by administrator'
        elif slot.sensor_health == 'fault':
            reasons[slot.id] = 'Sensor fault'
        elif slot.sensor_occupied or slot.status == 'occupied' or slot.id in busy_slots:
            reasons[slot.id] = 'Currently occupied or allocated; departure is unknown'
        else:
            schedules[slot.id] = [(r.starts_at, r.ends_at) for r in bookings if r.slot_id == slot.id] + vehicle_intervals
            if any(a < end and b > start for a, b in vehicle_intervals):
                reasons[slot.id] = 'This vehicle already has a reservation for that time'
            elif not containing_gap(start, end, schedules[slot.id], lower, upper):
                reasons[slot.id] = 'Reserved for this time'
    ranked = ranked_slots(schedules, start, end, lower, upper)
    gaps = dict(ranked)
    recommended = ranked[0][0] if ranked else None
    details = []
    for slot in slots:
        gap = gaps.get(slot.id)
        details.append({
            'id': slot.id, 'slot': slot.slot_number, 'available': gap is not None,
            'recommended': slot.id == recommended,
            'reason': reasons.get(slot.id, 'Available'),
            'free_before_minutes': int((start - gap[0]).total_seconds() / 60) if gap else None,
            'free_after_minutes': int((gap[1] - end).total_seconds() / 60) if gap else None,
            'gap_minutes': int((gap[1] - gap[0]).total_seconds() / 60) if gap else None,
        })
    alternatives = []
    if not ranked:
        duration = end - start
        latest = min(start + timedelta(hours=3), upper - duration)
        # Earliest feasible delayed start must lie at a blocking interval's end.
        starts = sorted({b for intervals in schedules.values() for _, b in intervals if start < b <= latest})
        for alternative_start in starts:
            choices = ranked_slots(schedules, alternative_start, alternative_start + duration, lower, upper)
            if choices:
                sid = choices[0][0]
                alternatives.append({'slot_id': sid, 'slot': next(s.slot_number for s in slots if s.id == sid),
                                     'start': alternative_start, 'end': alternative_start + duration,
                                     'delay_minutes': int((alternative_start - start).total_seconds() / 60)})
                if len(alternatives) == 3:
                    break
    return {'recommended_slot_id': recommended, 'slots': details, 'alternatives': alternatives,
            'strategy': 'Smallest containing free gap, with slot ID as tie-break',
            'explanation': ('Fits your visit into the smallest available gap, preserving longer continuous windows for other drivers.'
                            if ranked else 'No slot can fit the full requested window. Later options keep the same duration.'),
            'notice': 'Advice uses current sensor state and confirmed bookings. It does not hold a space; confirmation rechecks availability.'}


def allocation_experiment(scenario='fragmentation', seed=42, slot_count=4, request_count=80):
    """Replay identical synthetic requests for two online policies; never write DB."""
    if scenario not in {'fragmentation', 'random'}:
        raise ValueError('Select a valid workload.')
    if not 0 <= seed <= 2147483647 or not 2 <= slot_count <= 16 or not 2 <= request_count <= 500:
        raise ValueError('Use seed 0–2147483647, 2–16 slots, and 2–500 requests.')
    horizon = 480
    if scenario == 'fragmentation':
        # Fixed teaching counterexample: the policies receive identical requests,
        # but best-fit keeps the small late gap available for a later short visit.
        schedules = {0: [(90, 150)], 1: [(330, 360), (210, 240)]}
        requests = [(330, 360), (30, 120), (240, 330), (0, 150),
                    (330, 360), (150, 300), (0, 150), (60, 210)]
        slot_count = 2
    else:
        rng = random.Random(seed)
        schedules = {}
        for sid in range(slot_count):
            busy_start = rng.randrange(12, 27) * 15
            schedules[sid] = [(busy_start, min(horizon, busy_start + rng.choice([60, 90, 120])))]
        requests = []
        for _ in range(request_count):
            start = rng.randrange(0, 25) * 15
            end = min(horizon, start + rng.choice([30, 60, 90, 120, 180, 240]))
            requests.append((start, end))
    results = {}
    for strategy in ('first_fit', 'best_fit'):
        replay = {sid: list(intervals) for sid, intervals in schedules.items()}
        trace, accepted_minutes = [], 0
        for index, (start, end) in enumerate(requests, 1):
            candidates = ranked_slots(replay, start, end, 0, horizon, strategy)
            sid, gap = candidates[0] if candidates else (None, None)
            if sid is not None:
                replay[sid].append((start, end))
                accepted_minutes += end - start
            trace.append({'request': index, 'start': start, 'end': end,
                          'slot': f'S{sid + 1:02d}' if sid is not None else None,
                          'gap_minutes': gap[1] - gap[0] if gap else None})
        accepted = sum(row['slot'] is not None for row in trace)
        results[strategy] = {'accepted': accepted, 'rejected': len(requests) - accepted,
                             'acceptance_rate': round(100 * accepted / len(requests), 1),
                             'accepted_minutes': accepted_minutes,
                             'added_utilization': round(100 * accepted_minutes / (slot_count * horizon), 1),
                             'trace': trace}
    return {'scenario': scenario, 'seed': seed, 'slot_count': slot_count, 'request_count': len(requests),
            'horizon_minutes': horizon, 'initial': [{'slot': f'S{sid + 1:02d}', 'intervals': intervals}
                                                  for sid, intervals in schedules.items()],
            'results': results, 'accepted_delta': results['best_fit']['accepted'] - results['first_fit']['accepted']}
