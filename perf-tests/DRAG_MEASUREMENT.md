# Manual Drag Performance Measurement

Automated (headless Chromium) drag simulation could not be made to
reliably reproduce native HTML5 drag-and-drop's `dragover` firing rate —
see the note at the top of `browser_probe.py` for what was tried. This is
a step-by-step manual procedure using Chrome DevTools' own Performance
panel, which gives the real number rather than a synthetic approximation.

Takes about 3 minutes. Repeat once for "before" (current `main`/baseline)
and once for "after" each Tier 1/2 change that touches the drag path (items
1.6, 1.7, 2.2).

## Steps

1. Open the seeded board in a **real Chrome window** (not headless):
   `http://localhost/board.html?id=1`
   (adjust the id if your seeded board isn't 1 — `perf-tests/seed_board.py`
   prints the URL when it creates one)

2. Log in as `test-admin@localhost` / `TestAdmin123!` if not already
   authenticated.

3. Open DevTools (F12) → **Performance** tab.

4. Check the gear icon (⚙) in the Performance panel and confirm **CPU
   throttling is "No throttling"** and **Screenshots** is enabled (helps
   you see what was happening at a given point in the trace later).

5. Position the board so column 1's first ~5 cards and a spot ~15-20 cards
   down are both reachable by scrolling, or just pick a drag within the
   visible viewport (dragging within-viewport is enough to reproduce the
   `getDragAfterElement` cost — the DOM query scans the whole column
   regardless of how far you visually drag).

6. Click the **Record** button (●) in the Performance panel.

7. **Immediately** grab the first card in column 1 and drag it down past
   10-20 cards, moving the mouse in a natural continuous motion (not
   teleporting) — take about 2-3 seconds to do the drag, wiggling up and
   down a little partway through the way you would if hunting for the
   right drop spot. Drop it.

8. Wait ~1 second after drop (let the `card_updated` broadcast/board
   reload settle), then click **Stop** recording.

9. In the trace, use the **Summary** tab at the bottom (click on empty
   space in the main timeline first, or select the whole recorded range)
   to read off:
   - **Scripting** (ms)
   - **Rendering** (ms) — this is where forced layout/reflow time shows up
   - **Painting** (ms)
   - **Total** (ms)

10. Switch to the **Bottom-Up** or **Call Tree** tab, sort by Total Time,
    and look specifically for `getDragAfterElement` and `getDropOrderValue`
    — note their self time and invocation count if visible. (If names are
    minified/unclear, look for `Layout` entries clustered tightly together
    during the drag portion of the timeline — many `Layout` purple blocks
    in a short span is the layout-thrash signature described in the
    performance doc's items 1.6/2.2.)

11. Also note, from the timeline ruler directly: does the dragged card
    visually keep up with the mouse, or does it lag/stutter? This
    subjective read matters as much as the numbers — the whole point of
    this fix is that dragging *feels* smooth.

## What to record back

Paste (or describe) into the working doc / this session:
- Scripting / Rendering / Painting / Total ms from the Summary tab
- Approximate count of `Layout` purple blocks visible in the flame chart
  during the drag portion
- Whether the drag felt smooth or stuttery
- Screenshot of the Performance panel summary, if easy to grab (optional
  but useful for the PR description)

## Saving the trace (optional but recommended)

Right-click the recording → **Save profile...** saves a `.json` trace file.
Keep these under `perf-tests/results/traces/` (gitignored — traces can be
tens of MB, and open one anytime via DevTools → Performance → Load profile
to re-inspect without re-running).
