import random

from clipper.detector import DetectorConfig, SpikeDetector

T0 = 1_000_000.0


def feed(det, rng, start, end, rate, users=5000):
    for sec in range(start, end):
        for _ in range(rate):
            det.add(f"u{rng.randint(0, users)}", T0 + sec + rng.random())


def test_fires_on_explosion_with_correct_onset():
    rng = random.Random(1)
    det = SpikeDetector(DetectorConfig())
    feed(det, rng, 0, 200, 5)
    assert all(det.check(T0 + s) is None for s in range(61, 201))
    feed(det, rng, 200, 210, 60)
    spikes = [sp for s in range(201, 211) if (sp := det.check(T0 + s))]
    assert len(spikes) == 1
    assert spikes[0].onset == T0 + 200
    assert spikes[0].baseline < 7


def test_no_false_alarm_on_steady_busy_chat():
    rng = random.Random(2)
    det = SpikeDetector(DetectorConfig())
    for sec in range(900):
        feed(det, rng, sec, sec + 1, rng.randint(30, 50))
        assert det.check(T0 + sec + 1) is None


def test_single_spammer_does_not_trigger():
    rng = random.Random(3)
    det = SpikeDetector(DetectorConfig())
    feed(det, rng, 0, 200, 3)
    for sec in range(200, 210):
        for i in range(100):
            det.add("spammer", T0 + sec + i / 100)
    assert all(det.check(T0 + s) is None for s in range(201, 211))


def test_cooldown_and_warmup():
    rng = random.Random(4)
    cfg = DetectorConfig(cooldown=90, warmup=60)
    det = SpikeDetector(cfg)
    feed(det, rng, 0, 30, 2)
    feed(det, rng, 30, 40, 50)
    assert all(det.check(T0 + s) is None for s in range(31, 41))  # still warming up
    feed(det, rng, 40, 200, 2)
    feed(det, rng, 200, 205, 50)
    assert det.check(T0 + 205) is not None
    feed(det, rng, 205, 240, 2)
    feed(det, rng, 240, 245, 50)
    assert det.check(T0 + 245) is None  # inside cooldown


def test_detects_relative_spike_on_huge_channel():
    rng = random.Random(5)
    det = SpikeDetector(DetectorConfig())
    feed(det, rng, 0, 300, 80, users=200000)
    feed(det, rng, 300, 306, 400, users=200000)
    assert any(det.check(T0 + s) for s in range(301, 307))
