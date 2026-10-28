"""Compare an exported BWF against reference mono/stereo WAVs (critical acceptance test).

Usage (from the project folder, with the virtual environment):
    .venv\\Scripts\\python tools\\compare_reference.py OUTPUT.wav --left REF_L.wav --right REF_R.wav
    .venv\\Scripts\\python tools\\compare_reference.py OUTPUT.wav --stereo REF_STEREO.wav [--ref-offset SAMPLES]

Reports, per channel: sample count, first mismatch, number of differing samples
and the offset at which the first non-silent audio starts in each file, so a
timing error is distinguishable from a content error. Also prints the BWF
TimeReference of both files when present. Exit code 0 means sample-identical.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aaf_extractor.media.containers import parse_wave  # noqa: E402
from aaf_extractor.media.reader import PCMReader  # noqa: E402

BLOCK = 48000 * 10


def _open(path: str, channel: int):
    fh = open(path, "rb")
    fmt = parse_wave(fh, Path(path).stat().st_size)
    return PCMReader(fh, fmt, channel, owns_handle=True), fmt


def _time_reference(path: str):
    try:
        from aaf_extractor.bwf.reader import read_bwf
        bext = read_bwf(path).bext
        return bext["time_reference"] if bext else None
    except Exception:
        return None


def _first_sound(reader: PCMReader) -> int | None:
    pos = 0
    while pos < reader.frames:
        n = min(BLOCK, reader.frames - pos)
        nz = np.flatnonzero(reader.read(pos, n))
        if nz.size:
            return pos + int(nz[0])
        pos += n
    return None


def compare(out_path, out_ch, ref_path, ref_ch, ref_offset=0) -> bool:
    out, ofmt = _open(out_path, out_ch)
    ref, rfmt = _open(ref_path, ref_ch)
    label = f"{'LR'[out_ch]} vs {Path(ref_path).name} ch{ref_ch + 1}"
    print(f"\n{label}")
    print(f"  output:    {out.frames} samples, {ofmt.sample_rate} Hz, {ofmt.bits}-bit")
    print(f"  reference: {ref.frames} samples, {rfmt.sample_rate} Hz, {rfmt.bits}-bit (offset {ref_offset})")
    if ofmt.sample_rate != rfmt.sample_rate:
        print("  FAIL: sample rates differ")
        return False
    first_o, first_r = _first_sound(out), _first_sound(ref)
    print(f"  first non-silent sample: output {first_o}, reference {first_r}"
          + (f" (difference {first_o - first_r - ref_offset})" if first_o is not None and first_r is not None else ""))
    n = min(out.frames, ref.frames - ref_offset)
    diffs = 0
    first_diff = None
    pos = 0
    while pos < n:
        k = min(BLOCK, n - pos)
        a = out.read(pos, k)
        b = ref.read(pos + ref_offset, k)
        bad = np.flatnonzero(a != b)
        if bad.size:
            diffs += int(bad.size)
            if first_diff is None:
                first_diff = pos + int(bad[0])
        pos += k
    ok = diffs == 0 and out.frames == ref.frames - ref_offset
    if out.frames != ref.frames - ref_offset:
        print(f"  length differs by {out.frames - (ref.frames - ref_offset)} samples")
    if diffs:
        print(f"  {diffs} differing samples; first at output sample {first_diff}")
    print("  RESULT: " + ("IDENTICAL" if ok else "DIFFERENT"))
    out.close()
    ref.close()
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output")
    ap.add_argument("--left")
    ap.add_argument("--right")
    ap.add_argument("--stereo")
    ap.add_argument("--ref-offset", type=int, default=0,
                    help="samples to skip at the start of the reference (e.g. if it was exported with pre-roll)")
    args = ap.parse_args(argv)
    print(f"Output TimeReference: {_time_reference(args.output)}")
    results = []
    if args.stereo:
        print(f"Reference TimeReference: {_time_reference(args.stereo)}")
        results.append(compare(args.output, 0, args.stereo, 0, args.ref_offset))
        results.append(compare(args.output, 1, args.stereo, 1, args.ref_offset))
    else:
        if args.left:
            print(f"Left reference TimeReference: {_time_reference(args.left)}")
            results.append(compare(args.output, 0, args.left, 0, args.ref_offset))
        if args.right:
            print(f"Right reference TimeReference: {_time_reference(args.right)}")
            results.append(compare(args.output, 1, args.right, 0, args.ref_offset))
    if not results:
        ap.error("give --left/--right or --stereo")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
