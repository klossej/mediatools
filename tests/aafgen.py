"""Synthetic AAF fixture builder used by the tests.

Builds small AAF files with pyaaf2 that mimic the structure of Avid Media
Composer exports: a top-level CompositionMob with a timecode track and sound
tracks whose SourceClips reference MasterMobs, which reference file SourceMobs
carrying (embedded or external) PCM essence.
"""

from __future__ import annotations

import io
import struct
import wave
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import aaf2
import numpy as np


@dataclass
class Media:
    samples: np.ndarray            # shape (n,) mono or (n, ch)
    sample_rate: int = 48000
    bits: int = 24
    kind: str = "pcm"              # pcm | wave | aiff | external
    external_path: Path | None = None
    mob_edit_rate: Fraction | int | None = None  # edit rate of master/file slots (default: sample rate)
    channel: int = 1               # PhysicalTrackNumber on the file slot for multichannel media


@dataclass
class Clip:
    media: str
    src_start: int                 # in master-slot edit units
    length: int                    # in composition track edit units


@dataclass
class Gap:
    length: int


@dataclass
class Effect:
    """Wrap a clip in an OperationGroup."""
    clip: Clip
    operation: str = "gain"        # gain | pan | other
    value: object = 1


@dataclass
class Track:
    number: int | None
    name: str = ""
    items: list = field(default_factory=list)


def sine(n: int, freq: float = 1000.0, rate: int = 48000, bits: int = 24, amp: float = 0.5, seed: int | None = None):
    full = (1 << (bits - 1)) - 1
    if seed is not None:
        rng = np.random.default_rng(seed)
        return rng.integers(-full, full, size=n, dtype=np.int64).astype(np.int32)
    t = np.arange(n)
    return np.round(np.sin(2 * np.pi * freq * t / rate) * amp * full).astype(np.int32)


def ramp(n: int, start: int = 0, bits: int = 24):
    """Unique sample values so offsets can be verified exactly."""
    lim = 1 << (bits - 1)
    vals = (np.arange(n, dtype=np.int64) + start) % (2 * lim) - lim
    return vals.astype(np.int32)


def pcm_bytes(samples: np.ndarray, bits: int, big_endian: bool = False) -> bytes:
    arr = samples.astype(np.int32)
    if arr.ndim == 1:
        arr = arr[:, None]
    width = bits // 8
    le = arr.astype("<i4").view(np.uint8).reshape(arr.shape[0], arr.shape[1], 4)[:, :, :width]
    if big_endian:
        le = le[:, :, ::-1]
    return np.ascontiguousarray(le).tobytes()


def wav_bytes(samples: np.ndarray, rate: int, bits: int) -> bytes:
    buf = io.BytesIO()
    ch = 1 if samples.ndim == 1 else samples.shape[1]
    with wave.open(buf, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(bits // 8)
        w.setframerate(rate)
        w.writeframes(pcm_bytes(samples, bits))
    return buf.getvalue()


def _ieee_extended(value: int) -> bytes:
    import math
    if value == 0:
        return b"\0" * 10
    exp = int(math.floor(math.log2(value)))
    mant = int(value * 2 ** (63 - exp))
    return struct.pack(">HQ", exp + 16383, mant)


def aiff_bytes(samples: np.ndarray, rate: int, bits: int) -> bytes:
    ch = 1 if samples.ndim == 1 else samples.shape[1]
    data = pcm_bytes(samples, bits, big_endian=True)
    frames = len(data) // (ch * bits // 8)
    comm = struct.pack(">hIh", ch, frames, bits) + _ieee_extended(rate)
    ssnd = struct.pack(">II", 0, 0) + data
    body = b"AIFF" + b"COMM" + struct.pack(">I", len(comm)) + comm
    body += b"SSND" + struct.pack(">I", len(ssnd)) + ssnd
    if len(ssnd) & 1:
        body += b"\0"
    return b"FORM" + struct.pack(">I", len(body)) + body


def _set(obj, key, value):
    obj[key].value = value


def _make_source(f, name: str, m: Media):
    """Create MasterMob + file SourceMob for one media item; return the MasterMob."""
    ch = 1 if m.samples.ndim == 1 else m.samples.shape[1]
    frames = m.samples.shape[0]
    rate = m.sample_rate
    er = Fraction(m.mob_edit_rate) if m.mob_edit_rate is not None else Fraction(rate)

    src = f.create.SourceMob(f"{name}.PHYS")
    f.content.mobs.append(src)

    if m.kind in ("pcm", "external"):
        desc = f.create.PCMDescriptor()
        _set(desc, "Channels", ch)
        _set(desc, "BlockAlign", ch * m.bits // 8)
        _set(desc, "SampleRate", rate)
        _set(desc, "AverageBPS", rate * ch * m.bits // 8)
        _set(desc, "QuantizationBits", m.bits)
        _set(desc, "AudioSamplingRate", rate)
    elif m.kind == "wave":
        desc = f.create.WAVEDescriptor()
        _set(desc, "SampleRate", rate)
        _set(desc, "Summary", wav_bytes(m.samples[:0], rate, m.bits)[:44])
    elif m.kind == "aiff":
        desc = f.create.AIFCDescriptor()
        _set(desc, "SampleRate", rate)
        _set(desc, "Summary", aiff_bytes(m.samples[:0], rate, m.bits))
    else:
        raise ValueError(m.kind)
    desc.length = frames
    src.descriptor = desc

    slot = src.create_empty_slot(edit_rate=er, media_kind="sound", slot_id=1)
    slot.segment.length = int(Fraction(frames) * er / rate)
    if ch > 1:
        slot["PhysicalTrackNumber"].value = m.channel

    if m.kind == "external":
        path = Path(m.external_path)
        path.write_bytes(wav_bytes(m.samples, rate, m.bits))
        loc = f.create.NetworkLocator()
        loc["URLString"].value = path.resolve().as_uri()
        desc["Locator"].append(loc)
    else:
        ed = f.create.EssenceData()
        ed.mob_id = src.mob_id
        f.content.essencedata.append(ed)
        stream = ed.open("w")
        if m.kind == "pcm":
            stream.write(pcm_bytes(m.samples, m.bits))
        elif m.kind == "wave":
            stream.write(wav_bytes(m.samples, rate, m.bits))
        else:
            stream.write(aiff_bytes(m.samples, rate, m.bits))

    master = f.create.MasterMob(name)
    f.content.mobs.append(master)
    mslot = master.create_timeline_slot(edit_rate=er)
    mslot.segment = src.create_source_clip(1, media_kind="sound")
    mslot.segment.length = slot.segment.length
    return master


def _add_items(f, seq, items, masters):
    for item in items:
        if isinstance(item, Gap):
            seq.components.append(f.create.Filler("sound", item.length))
        elif isinstance(item, Clip):
            seq.components.append(_clip(f, item, masters))
        elif isinstance(item, Effect):
            seq.components.append(_effect(f, item, masters))
        elif isinstance(item, str) and item == "transition":
            tr = f.create.Transition("sound", 10)
            opdef = f.create.OperationDef("0c3bea41-fc05-11d2-8a29-0050040ef7d2", "Mono Audio Dissolve")
            opdef.media_kind = "sound"
            opdef["NumberInputs"].value = 2
            f.dictionary.register_def(opdef)
            tr["OperationGroup"].value = f.create.OperationGroup(opdef, 10, "sound")
            tr["CutPoint"].value = 5
            seq.components.append(tr)
        else:
            raise ValueError(item)


def _clip(f, item: Clip, masters):
    master = masters[item.media]
    return master.create_source_clip(slot_id=1, start=item.src_start, length=item.length, media_kind="sound")


def _effect(f, item: Effect, masters):
    clip = _clip(f, item.clip, masters)
    if item.operation == "gain":
        opdef = f.create.OperationDef("9d2ea893-0968-11d3-8a38-0050040ef7d2", "Mono Audio Gain")
        opdef.media_kind = "sound"
        opdef["NumberInputs"].value = 1
        f.dictionary.register_def(opdef)
        pdef = f.create.ParameterDef("e4962320-2267-11d3-8a4c-0050040ef7d2", "Amplitude", "", "Rational")
        f.dictionary.register_def(pdef)
        opdef["ParametersDefined"].append(pdef)
        og = f.create.OperationGroup(opdef, item.clip.length, "sound")
        og.segments.append(clip)
        p = f.create.ConstantValue(pdef, item.value)
        og.parameters.append(p)
    else:
        opdef = f.create.OperationDef("11111111-2222-3333-4444-555555555555", "Audio EQ Multiband")
        opdef.media_kind = "sound"
        opdef["NumberInputs"].value = 1
        f.dictionary.register_def(opdef)
        og = f.create.OperationGroup(opdef, item.clip.length, "sound")
        og.segments.append(clip)
    return og


def build_aaf(path, tracks: list[Track], media: dict[str, Media], *, name: str = "TEST SEQ",
              edit_rate=25, tc_start: int | None = 0, tc_fps: int = 25, drop: bool = False,
              tc_edit_rate=None, picture_length: int | None = None, toplevel: bool = True,
              extra_sequences: int = 0):
    path = Path(path)
    edit_rate = Fraction(edit_rate)
    with aaf2.open(str(path), "w") as f:
        masters = {key: _make_source(f, f"{key}", m) for key, m in media.items()}
        for n in range(1 + extra_sequences):
            seq_name = name if n == 0 else f"{name} ALT {n}"
            comp = f.create.CompositionMob(seq_name)
            if toplevel:
                comp.usage = "Usage_TopLevel"
            f.content.mobs.append(comp)

            if picture_length:
                pslot = comp.create_picture_slot(edit_rate)
                pslot.segment.components.append(f.create.Filler("picture", picture_length))
                pslot.segment.length = picture_length
                pslot.name = "V1"
            if tc_start is not None:
                tslot = comp.create_timeline_slot(Fraction(tc_edit_rate or edit_rate))
                tslot.segment = f.create.Timecode(tc_fps, drop, length=picture_length or 1000)
                tslot.segment.start = tc_start + n * 1000
                tslot.name = "TC1"
                tslot["PhysicalTrackNumber"].value = 1
            for t in tracks:
                slot = comp.create_sound_slot(edit_rate)
                if t.number is not None:
                    slot["PhysicalTrackNumber"].value = t.number
                if t.name:
                    slot.name = t.name
                _add_items(f, slot.segment, t.items, masters)
                slot.segment.length = sum(c.length for c in slot.segment.components
                                          if not isinstance(c, aaf2.components.Transition)) - sum(
                    c.length for c in slot.segment.components if isinstance(c, aaf2.components.Transition))
    return path
