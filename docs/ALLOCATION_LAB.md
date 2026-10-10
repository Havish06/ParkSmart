# Allocation lab notes

## Problem

Choosing the first available slot is easy to implement, but it can consume a large continuous free interval with a short booking. That can make a later long booking fail even when the parking area still has enough total free time.

## Policy

For every slot, ParkSmart builds a list of confirmed reservation intervals and rejects intervals that overlap the requested window. It then ranks the remaining slots by the size of the containing free gap:

1. **Best-fit**: choose the smallest gap that contains the complete booking.
2. **Slot ID tie-break**: choose the lower slot ID when gaps are equal.

The planner is advisory. `create_reservation()` still performs the authoritative availability check while holding the lifecycle lock, so a browser recommendation cannot bypass a concurrent booking.

## Reproducible evaluation

The admin Allocation lab replays identical requests against:

- **First-fit baseline** — lowest numbered eligible slot.
- **Best-fit gap packing** — smallest eligible containing gap.

The `fragmentation` workload is a fixed teaching case. The `random` workload uses a displayed integer seed, so changing the seed creates a new scenario that can still be reproduced exactly. Metrics include accepted requests, rejected requests, acceptance rate, accepted minutes, and added utilization. The decision trace records the assigned slot or rejection for every request. CSV export makes the experiment inspectable outside the application.

## Demo script

1. Sign in as `admin@parksmart.local` / `Admin@123`.
2. Open **Allocation lab**.
3. Run **Fragmentation teaching case** and compare the two cards.
4. Change the seed or choose **Seeded random workload**, then replay it.
5. Download the CSV and explain that both policies saw the same ordered requests.
6. Open **Reserve**, fill in a future window, and observe the live explanation before confirming.

This gives the project an algorithmic design decision, a correctness boundary, and an evidence-based evaluation rather than only another screen.
