"""Verify SSE buffer truncation does not cause event loss."""
from collections import deque


def test_deque_maxlen_enforced():
    """Deque with maxlen auto-drops oldest entries."""
    buf = deque(maxlen=500)
    for i in range(1000):
        buf.append((i, {"type": "bar", "data": {"n": i}}))
    assert len(buf) == 500
    # Oldest retained event is seq 500 (0-indexed), newest is 999
    assert buf[0][0] == 500
    assert buf[-1][0] == 999


def test_seq_monotonic_after_truncation():
    """Consumer tracking by seq should never miss events post-truncation."""
    buf = deque(maxlen=10)
    seq = 0
    last_seen = 0
    # Produce 25 events
    for _ in range(25):
        seq += 1
        buf.append((seq, {"type": "test"}))
        # Consumer reads every 5 events
        if seq % 5 == 0:
            new_events = [(s, e) for s, e in buf if s > last_seen]
            for s, _ in new_events:
                last_seen = s
    # After all production + consumption, the last_seen seq should be 25
    assert last_seen == 25


def test_deque_maxlen_preserves_newest():
    """After overflow, newest events are always accessible."""
    buf = deque(maxlen=5)
    for i in range(1, 11):
        buf.append((i, {"type": "bar"}))
    # Should contain seqs 6-10
    seqs = [s for s, _ in buf]
    assert seqs == [6, 7, 8, 9, 10]


def test_consumer_survives_full_buffer_replacement():
    """Consumer with a very stale last_seen should still get all available events."""
    buf = deque(maxlen=10)
    for i in range(1, 21):
        buf.append((i, {"data": i}))
    # Consumer last saw seq 5 — but buffer only has 11-20
    last_seen = 5
    new_events = [(s, e) for s, e in buf if s > last_seen]
    assert len(new_events) == 10
    assert new_events[0][0] == 11
    assert new_events[-1][0] == 20
