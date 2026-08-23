import os

import pytest
from conftest import DATA

from subtitle_tool.audio import SAMPLE_RATE, decode_track, probe_tracks

MULTITRACK = os.path.join(DATA, "multitrack.mkv")


def test_probes_single_track_file():
    tracks = probe_tracks(os.path.join(DATA, "jfk.flac"))
    assert len(tracks) == 1
    assert tracks[0].codec == "flac"


@pytest.mark.skipif(not os.path.exists(MULTITRACK), reason="需先运行 scripts/make_fixture.py")
def test_probes_every_track_and_reads_language_tag():
    tracks = probe_tracks(MULTITRACK)
    assert len(tracks) == 2
    assert tracks[0].language_tag == "eng"
    assert "英语" in tracks[0].label


def test_decodes_to_16k_mono_float32():
    audio = decode_track(os.path.join(DATA, "jfk.flac"))
    assert audio.dtype.name == "float32"
    assert audio.ndim == 1
    assert 10.5 < len(audio) / SAMPLE_RATE < 11.5
    assert abs(audio).max() <= 1.0


@pytest.mark.skipif(not os.path.exists(MULTITRACK), reason="需先运行 scripts/make_fixture.py")
def test_selects_the_requested_track():
    # 两条音轨内容不同，选轨生效的话解出的波形也应不同
    first = decode_track(MULTITRACK, 0)
    second = decode_track(MULTITRACK, 1)
    assert len(first) != len(second) or not (first[:16000] == second[:16000]).all()


def test_reports_decode_progress_monotonically():
    seen = []
    decode_track(os.path.join(DATA, "jfk.flac"), progress=seen.append)
    assert seen[-1] == 1.0
    assert seen == sorted(seen)


def test_missing_track_fails_loudly():
    with pytest.raises(ValueError, match="音轨"):
        decode_track(os.path.join(DATA, "jfk.flac"), 5)
