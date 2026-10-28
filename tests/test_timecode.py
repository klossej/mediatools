from fractions import Fraction

import pytest

from aaf_extractor.timecode import (TimecodeError, TimecodeRate, frames_to_label, label_to_frames,
                                    round_half_up, timecode_to_time_reference, units_to_samples)

R25 = TimecodeRate.from_nominal(25)
R24 = TimecodeRate.from_nominal(24)
R23976 = TimecodeRate.from_nominal(24, False, pulldown=True)
R2997DF = TimecodeRate.from_nominal(30, True)
R2997NDF = TimecodeRate.from_nominal(30, False, pulldown=True)
R30 = TimecodeRate.from_nominal(30)


@pytest.mark.parametrize("rate,label,frames", [
    (R25, "10:00:00:00", 900000),
    (R25, "00:00:00:24", 24),
    (R24, "01:00:00:00", 86400),
    (R23976, "01:00:00:00", 86400),
    (R30, "01:00:00:00", 108000),
    (R2997NDF, "01:00:00:00", 108000),
    (R2997DF, "01:00:00;00", 107892),
    (R2997DF, "10:00:00;00", 1078920),
    (R2997DF, "00:01:00;02", 1800),
    (R2997DF, "00:10:00;00", 17982),
    (R2997DF, "23:59:59;29", 2589407),
])
def test_label_roundtrip(rate, label, frames):
    assert label_to_frames(label, rate) == frames
    assert frames_to_label(frames, rate) == label


def test_drop_frame_every_frame_roundtrips():
    for f in range(0, 20000):
        assert label_to_frames(frames_to_label(f, R2997DF), R2997DF) == f


def test_dropped_labels_rejected():
    with pytest.raises(TimecodeError):
        label_to_frames("00:01:00;00", R2997DF)
    with pytest.raises(TimecodeError):
        label_to_frames("00:00:00:25", R25)
    with pytest.raises(TimecodeError):
        TimecodeRate.from_nominal(25, True)


@pytest.mark.parametrize("rate,frames,expected", [
    (R25, 900000, 1_728_000_000),            # 10:00:00:00 @25 -> 36000 s * 48000
    (R24, 86400, 172_800_000),
    (R30, 108000, 172_800_000),
    (R23976, 86400, 172_972_800),            # 86400 * 1001/24000 s
    (R2997NDF, 108000, 172_972_800),
    (R2997DF, 107892, 172_799_827),          # 107892 * 1601.6 = 172799827.2
])
def test_time_reference(rate, frames, expected):
    assert timecode_to_time_reference(frames, rate, 48000) == expected


def test_time_reference_last_frame_of_day():
    # A full day at 48 kHz (4.147e9 samples) still fits 32 bits; the 64-bit
    # high word is exercised in test_bwf.test_bext_layout_offsets.
    frames = label_to_frames("23:59:59:24", R25)
    tr = timecode_to_time_reference(frames, R25, 48000)
    assert frames == 2_159_999
    assert tr == frames * 1920
    assert tr < 2 ** 32


def test_exact_rational_rounding():
    assert round_half_up(Fraction(1, 2)) == 1
    assert round_half_up(Fraction(-1, 2)) == -1
    # 29.97 frames are 1601.6 samples; boundaries must be monotonic and contiguous
    er = Fraction(30000, 1001)
    edges = [units_to_samples(u, er, 48000) for u in range(0, 3001)]
    assert all(b > a for a, b in zip(edges, edges[1:]))
    assert edges[3000] == round_half_up(Fraction(3000) * 48000 / er)
