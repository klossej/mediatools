"""Read an AAF file into :mod:`aaf_extractor.aaf.model` objects.

Only the structures needed for premixed audio extraction are interpreted.
Anything that could change the sound of a track (effects, transitions, gain
other than unity, nested compositions) is reported as an error on that track
instead of being ignored.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from typing import Iterator

import aaf2
from aaf2 import components as C
from aaf2 import essence as E
from aaf2 import mobs as M

from ..media.containers import ContainerError, parse_aiff, parse_wave, sniff
from ..timecode import TimecodeError, TimecodeRate
from .model import (AAFInspection, AudioTrack, EssenceFormat, MediaRef, RecordTimecode,
                    SequenceInfo, TrackSegment)

log = logging.getLogger(__name__)

# AAF standard operation definitions (AAF Edit Protocol / AAF Object Spec).
OPDEF_MONO_AUDIO_GAIN = "9d2ea893-0968-11d3-8a38-0050040ef7d2"
OPDEF_MONO_AUDIO_PAN = "9d2ea894-0968-11d3-8a38-0050040ef7d2"
PARAMDEF_AMPLITUDE = "e4962320-2267-11d3-8a4c-0050040ef7d2"

MAX_RESOLVE_DEPTH = 16


class UnsupportedStructure(Exception):
    pass


def _rational(value) -> Fraction:
    return Fraction(value.numerator, value.denominator) if value is not None else Fraction(0)


def _prop(obj, key, default=None):
    try:
        return obj[key].value if key in obj.keys() else default
    except Exception:  # pragma: no cover - defensive against malformed properties
        return default


def _class_name(obj) -> str:
    return type(obj).__name__


def _media_kind(slot_or_segment) -> str:
    try:
        return (slot_or_segment.media_kind or "").lower()
    except Exception:
        return ""


def _slot_name(slot) -> str:
    return (_prop(slot, "SlotName") or "").strip()


def _opdef_auid(op) -> str:
    try:
        return str(op.auid).lower()
    except Exception:
        return ""


def _is_zero_mob_id(mob_id) -> bool:
    try:
        return int(mob_id) == 0
    except Exception:
        return False


# --- media -----------------------------------------------------------------

def _declared_format(desc) -> EssenceFormat | None:
    rate = _prop(desc, "SampleRate") or _prop(desc, "AudioSamplingRate")
    channels = _prop(desc, "Channels")
    bits = _prop(desc, "QuantizationBits")
    if rate is None or channels is None or bits is None:
        return None
    rate = _rational(rate) if not isinstance(rate, (int, float)) else Fraction(rate)
    if rate.denominator != 1:
        return None
    return EssenceFormat(int(rate), int(channels), int(bits))


def _summary_format(desc) -> EssenceFormat | None:
    """WAVE/AIFC descriptors carry the original file header in ``Summary``."""
    import io
    summary = _prop(desc, "Summary")
    if not summary:
        return None
    buf = io.BytesIO(bytes(summary))
    try:
        if isinstance(desc, E.WAVEDescriptor):
            fmt = parse_wave(buf) if sniff(buf) == "wave" else None
        else:
            fmt = parse_aiff(buf) if sniff(buf) == "aiff" else None
    except ContainerError:
        return None
    return fmt


def embedded_stream_format(desc, stream, declared: EssenceFormat | None) -> EssenceFormat:
    """Work out where samples are inside an embedded essence stream."""
    size = stream.dir.byte_size
    if isinstance(desc, (E.WAVEDescriptor, E.AIFCDescriptor)):
        kind = sniff(stream) if size >= 12 else None
        if kind == "wave":
            return parse_wave(stream, size)
        if kind == "aiff":
            return parse_aiff(stream, size)
        # Headerless stream: format comes from the Summary header.
        summary = _summary_format(desc)
        if summary is None:
            raise ContainerError("embedded WAVE/AIFC essence has neither a header nor a usable Summary")
        return EssenceFormat(summary.sample_rate, summary.channels, summary.bits,
                             summary.big_endian, 0, size)
    if isinstance(desc, E.PCMDescriptor):
        if declared is None:
            raise ContainerError("PCMDescriptor lacks SampleRate/Channels/QuantizationBits")
        return EssenceFormat(declared.sample_rate, declared.channels, declared.bits, False, 0, size)
    raise ContainerError(f"{_class_name(desc)} essence is not supported")


def _locators(desc) -> list[str]:
    urls = []
    try:
        locs = desc["Locator"].value if "Locator" in desc.keys() else []
    except Exception:
        locs = []
    for loc in locs or []:
        url = _prop(loc, "URLString") or _prop(loc, "Name")
        if url:
            urls.append(str(url))
    return urls


def _media_ref(f, source_mob, source_slot) -> MediaRef:
    desc = source_mob.descriptor
    mob_id = str(source_mob.mob_id)
    name = source_mob.name or ""
    dname = _class_name(desc) if desc is not None else "None"
    ref = MediaRef(mob_id=mob_id, mob_name=name, descriptor=dname, channel_index=0,
                   declared=None, length_samples=None, embedded=False)
    if desc is None:
        ref.problem = "source mob has no essence descriptor"
        return ref
    if isinstance(desc, E.MultipleDescriptor):
        ref.problem = "multi-descriptor (multi-essence) source media is not supported"
        return ref
    if not isinstance(desc, (E.PCMDescriptor, E.WAVEDescriptor, E.AIFCDescriptor)):
        if isinstance(desc, E.SoundDescriptor):
            ref.problem = f"{dname}: compressed or unknown sound coding is not supported"
        else:
            ref.problem = f"{dname} is not an audio file descriptor"
        return ref

    ref.declared = _declared_format(desc) or _summary_format(desc)
    length = _prop(desc, "Length")
    ref.length_samples = int(length) if length is not None else None
    ref.locators = _locators(desc)

    channels = ref.declared.channels if ref.declared else 1
    if channels > 1:
        track_no = _prop(source_slot, "PhysicalTrackNumber")
        if track_no is None or not (1 <= int(track_no) <= channels):
            ref.problem = (f"media has {channels} channels but the referenced slot does not "
                           "identify which channel to use")
        else:
            ref.channel_index = int(track_no) - 1

    essence = f.content.essencedata.get(source_mob.mob_id, None)
    if essence is not None:
        ref.embedded = True
        try:
            stream = essence.open("r")
            ref.embedded_format = embedded_stream_format(desc, stream, ref.declared)
        except ContainerError as exc:
            ref.problem = f"embedded essence unreadable: {exc}"
        except Exception as exc:  # pyaaf2 raises assorted errors on damaged streams
            ref.problem = f"embedded essence unreadable: {exc}"
    return ref


# --- segment resolution ---------------------------------------------------

def _component_at(sequence, position: int):
    """Return (component, component_start) covering ``position`` within a Sequence."""
    pos = 0
    for comp in sequence.components:
        if isinstance(comp, C.Transition):
            pos -= comp.length
            continue
        if pos <= position < pos + comp.length:
            return comp, pos
        pos += comp.length
    return None, pos


def _resolve_source(f, clip, offset: Fraction, depth: int = 0):
    """Follow a SourceClip down to a file SourceMob.

    ``offset`` is the time in seconds from the clip's start that we are
    interested in (always 0 for us; kept for clarity). Returns
    (MediaRef, seconds_into_media).
    """
    if depth > MAX_RESOLVE_DEPTH:
        raise UnsupportedStructure("source reference chain is too deep")
    mob = clip.mob
    if mob is None:
        raise UnsupportedStructure(f"clip references missing mob {clip.mob_id}")
    if isinstance(mob, M.CompositionMob):
        raise UnsupportedStructure(f"clip references nested composition '{mob.name}' (nested sequences are not supported)")
    slot_id = _prop(clip, "SourceMobSlotID")
    try:
        slot = mob.slot_at(slot_id)
    except IndexError:
        raise UnsupportedStructure(f"mob '{mob.name}' has no slot {slot_id}")
    edit_rate = _rational(slot.edit_rate)
    start = Fraction(clip.start or 0) / edit_rate + offset

    if isinstance(mob, M.SourceMob):
        desc = mob.descriptor
        if isinstance(desc, E.FileDescriptor):
            return _media_ref(f, mob, slot), start
        if desc is None or isinstance(desc, (E.TapeDescriptor, E.PhysicalDescriptor)):
            raise UnsupportedStructure(f"clip resolves to physical source '{mob.name}' without file media (offline)")
        raise UnsupportedStructure(f"unsupported source descriptor {_class_name(desc)}")

    # MasterMob (or other non-composition mob): look inside its slot.
    segment = slot.segment
    position_units = start * edit_rate
    if position_units.denominator != 1:
        position_units = Fraction(int(position_units))  # floor; sub-unit precision kept below
    inner_offset = start - position_units / edit_rate
    return _resolve_segment_source(f, segment, int(position_units), edit_rate, inner_offset, depth + 1, mob.name)


def _resolve_segment_source(f, segment, position: int, edit_rate: Fraction, inner_offset: Fraction,
                            depth: int, owner: str):
    if isinstance(segment, C.Sequence):
        comp, comp_start = _component_at(segment, position)
        if comp is None:
            raise UnsupportedStructure(f"'{owner}': reference falls outside the source track")
        return _resolve_segment_source(f, comp, position - comp_start, edit_rate, inner_offset, depth, owner)
    if isinstance(segment, C.SourceClip):
        if _is_zero_mob_id(segment.mob_id):
            raise UnsupportedStructure(f"'{owner}': source track is empty at this position (offline media)")
        return _resolve_source(f, segment, Fraction(position) / edit_rate + inner_offset, depth + 1)
    if isinstance(segment, C.EssenceGroup):
        choices = list(segment["Choices"].value or [])
        if len(choices) != 1:
            raise UnsupportedStructure(f"'{owner}': essence group with {len(choices)} choices is not supported")
        return _resolve_segment_source(f, choices[0], position, edit_rate, inner_offset, depth, owner)
    if isinstance(segment, C.Filler):
        raise UnsupportedStructure(f"'{owner}': source track is filler at this position (offline media)")
    raise UnsupportedStructure(f"'{owner}': {_class_name(segment)} inside source mob is not supported")


def _parameter_value(param):
    if isinstance(param, aaf2.misc.VaryingValue):
        return "varying"
    try:
        return param.value
    except Exception:
        return None


def _is_unity_gain(value) -> bool:
    try:
        return Fraction(value) == 1
    except (TypeError, ValueError):
        try:
            return float(value) == 1.0
        except (TypeError, ValueError):
            return False


def _operation_passthrough(op_group, track: AudioTrack):
    """Return the single input of an OperationGroup that does not change mono samples.

    Raises UnsupportedStructure for everything else.
    """
    op = op_group.operation
    op_name = (op.name if op is not None else "") or "unnamed operation"
    auid = _opdef_auid(op) if op is not None else ""
    inputs = list(op_group.segments or [])
    lname = op_name.lower()

    is_gain = auid == OPDEF_MONO_AUDIO_GAIN or ("gain" in lname and "audio" in lname)
    is_pan = auid == OPDEF_MONO_AUDIO_PAN or ("pan" in lname and "audio" in lname)
    if len(inputs) != 1 or not (is_gain or is_pan):
        raise UnsupportedStructure(f"effect '{op_name}' is applied (audio effects are not supported)")

    params = list(op_group.parameters or [])
    if is_gain:
        if not params:
            raise UnsupportedStructure(f"'{op_name}' has no amplitude parameter; cannot verify unity gain")
        for p in params:
            value = _parameter_value(p)
            if value == "varying":
                raise UnsupportedStructure(f"'{op_name}' carries volume automation (not supported)")
            if not _is_unity_gain(value):
                raise UnsupportedStructure(f"'{op_name}' applies non-unity gain ({value}); "
                                           "gain changes are not supported")
        track.warnings.append(f"'{op_name}' at unity gain treated as pass-through")
    else:
        for p in params:
            if _parameter_value(p) == "varying":
                raise UnsupportedStructure(f"'{op_name}' carries pan automation (not supported)")
        track.warnings.append(f"'{op_name}' ignored: pan does not alter the samples of an extracted mono track")
    return inputs[0]


def _flatten(f, segment, position: int, track: AudioTrack, depth: int = 0) -> Iterator[TrackSegment]:
    """Yield TrackSegments for a composition track segment placed at ``position``."""
    if depth > MAX_RESOLVE_DEPTH:
        raise UnsupportedStructure("track structure is nested too deeply")
    edit_rate = track.edit_rate
    if isinstance(segment, C.Sequence):
        pos = position
        for comp in segment.components:
            if isinstance(comp, C.Transition):
                if comp.length:
                    raise UnsupportedStructure(f"transition of {comp.length} units at position {pos} (transitions are not supported)")
                continue
            yield from _flatten(f, comp, pos, track, depth + 1)
            pos += comp.length
        return
    length = segment.length or 0
    if length == 0:
        return
    if isinstance(segment, C.Filler):
        yield TrackSegment(position, length, "silence", description="filler")
        return
    if isinstance(segment, C.SourceClip):
        if _is_zero_mob_id(segment.mob_id):
            yield TrackSegment(position, length, "silence", description="empty source clip")
            return
        media, start_seconds = _resolve_source(f, segment, Fraction(0))
        yield TrackSegment(position, length, "audio", media=media, source_start=start_seconds,
                           description=f"clip '{segment.mob.name if segment.mob else ''}'")
        return
    if isinstance(segment, C.OperationGroup):
        inner = _operation_passthrough(segment, track)
        yield from _flatten(f, inner, position, track, depth + 1)
        return
    raise UnsupportedStructure(f"{_class_name(segment)} at position {position} is not supported")


def _inspect_track(f, slot) -> AudioTrack:
    track_no = _prop(slot, "PhysicalTrackNumber")
    track = AudioTrack(
        slot_id=int(slot.slot_id),
        track_number=int(track_no) if track_no is not None else None,
        name=_slot_name(slot),
        edit_rate=_rational(slot.edit_rate),
        length=int(slot.segment.length or 0) if slot.segment is not None else 0,
    )
    origin = _prop(slot, "Origin") or 0
    if origin:
        track.errors.append(f"track origin {origin} is non-zero (not supported)")
        return track
    try:
        track.segments = list(_flatten(f, slot.segment, 0, track))
    except UnsupportedStructure as exc:
        track.errors.append(str(exc))
        track.segments = []
    for seg in track.segments:
        if seg.media is not None and seg.media.problem:
            msg = f"media '{seg.media.mob_name or seg.media.short_id}': {seg.media.problem}"
            if msg not in track.errors:
                track.errors.append(msg)
    return track


# --- timecode ---------------------------------------------------------------

def _timecode_components(slot):
    seg = slot.segment
    if isinstance(seg, C.Timecode):
        yield 0, seg
    elif isinstance(seg, C.Sequence):
        pos = 0
        for comp in seg.components:
            if isinstance(comp, C.Timecode):
                yield pos, comp
            pos += comp.length or 0


def _timecode_rate(fps: int, drop: bool, slot_rate: Fraction) -> TimecodeRate:
    if drop:
        return TimecodeRate(fps, True, Fraction(fps * 1000, 1001))
    if slot_rate == Fraction(fps * 1000, 1001):
        return TimecodeRate(fps, False, slot_rate)
    return TimecodeRate(fps, False, Fraction(fps))


def _find_record_timecode(mob) -> tuple[RecordTimecode | None, str | None, list[str]]:
    warnings: list[str] = []
    candidates = []
    for slot in mob.slots:
        comps = list(_timecode_components(slot))
        if not comps:
            continue
        pos, tc = comps[0]
        if pos != 0:
            warnings.append(f"timecode slot {slot.slot_id} does not start at the sequence start")
            continue
        slot_rate = _rational(slot.edit_rate)
        try:
            fps = int(tc.fps)
            rate = _timecode_rate(fps, bool(tc.drop), slot_rate)
        except (TimecodeError, TypeError, ValueError) as exc:
            warnings.append(f"timecode slot {slot.slot_id}: {exc}")
            continue
        if slot_rate not in (Fraction(fps), Fraction(fps * 1000, 1001)):
            warnings.append(f"timecode slot {slot.slot_id} edit rate {slot_rate} does not match "
                            f"{fps} fps; assuming {rate.label}")
        origin = _prop(slot, "Origin") or 0
        start = int(tc.start) + int(origin)
        label = _slot_name(slot) or f"slot {slot.slot_id}"
        candidates.append((slot, RecordTimecode(start, rate, f"composition timecode track '{label}'")))

    if not candidates:
        return None, "the sequence has no timecode track", warnings
    if len(candidates) == 1:
        return candidates[0][1], None, warnings
    distinct = {(c.start_frames, c.rate) for _, c in candidates}
    if len(distinct) == 1:
        return candidates[0][1], None, warnings
    # Prefer the primary timecode track (TC1) when there are several.
    primary = [c for s, c in candidates
               if _prop(s, "PhysicalTrackNumber") == 1 or _slot_name(s).upper() == "TC1"]
    if len(primary) == 1:
        warnings.append("several timecode tracks found; using TC1")
        return primary[0], None, warnings
    return None, "several timecode tracks disagree on the record start", warnings


# --- sequences ---------------------------------------------------------------

def _sequence_duration(mob) -> tuple[Fraction, Fraction | None]:
    longest = Fraction(0)
    picture_rate = None
    sound_rate = None
    for slot in mob.slots:
        kind = _media_kind(slot)
        if kind not in ("picture", "sound"):
            continue
        if not isinstance(slot, aaf2.mobslots.TimelineMobSlot):
            continue
        rate = _rational(slot.edit_rate)
        length = slot.segment.length if slot.segment is not None else 0
        longest = max(longest, Fraction(length or 0) / rate)
        if kind == "picture" and picture_rate is None:
            picture_rate = rate
        if kind == "sound" and sound_rate is None:
            sound_rate = rate
    return longest, picture_rate or sound_rate


def _inspect_sequence(f, mob, toplevel: bool) -> SequenceInfo:
    duration, edit_rate = _sequence_duration(mob)
    tc, tc_problem, tc_warnings = _find_record_timecode(mob)
    seq = SequenceInfo(mob_id=str(mob.mob_id), name=mob.name or "(unnamed sequence)",
                       edit_rate=edit_rate, duration=duration, timecode=tc,
                       timecode_problem=tc_problem, toplevel=toplevel)
    for slot in mob.slots:
        if _media_kind(slot) != "sound":
            continue
        if not isinstance(slot, aaf2.mobslots.TimelineMobSlot):
            continue
        seq.tracks.append(_inspect_track(f, slot))
    seq.warnings.extend(tc_warnings)
    return seq


def _candidate_sequences(f) -> list[tuple[object, bool]]:
    comps = list(f.content.compositionmobs())
    toplevel = [m for m in comps if m.usage == "Usage_TopLevel"]
    if toplevel:
        return [(m, True) for m in toplevel]
    # No usage codes: take compositions that are not referenced by another composition.
    referenced = set()
    for m in comps:
        for slot in m.slots:
            seg = slot.segment
            stack = [seg]
            while stack:
                s = stack.pop()
                if isinstance(s, C.Sequence):
                    stack.extend(s.components)
                elif isinstance(s, C.SourceClip):
                    referenced.add(str(s.mob_id))
                elif isinstance(s, C.OperationGroup):
                    stack.extend(s.segments or [])
    roots = [m for m in comps if str(m.mob_id) not in referenced]
    with_audio = [m for m in roots if any(_media_kind(s) == "sound" for s in m.slots)]
    return [(m, False) for m in with_audio]


def inspect_aaf(path: str) -> AAFInspection:
    result = AAFInspection(path=str(path))
    try:
        with aaf2.open(str(path), "r") as f:
            candidates = _candidate_sequences(f)
            if not candidates:
                result.error = "no edited sequence (CompositionMob) with audio tracks was found"
                return result
            for mob, toplevel in candidates:
                try:
                    result.sequences.append(_inspect_sequence(f, mob, toplevel))
                except Exception as exc:  # keep other sequences usable
                    log.exception("sequence inspection failed: %s", mob.name)
                    result.warnings.append(f"sequence '{mob.name}' could not be read: {exc}")
            if not result.sequences:
                result.error = "no readable sequence"
    except FileNotFoundError:
        result.error = "file not found"
    except Exception as exc:
        log.warning("AAF open failed: %s: %s", path, exc)
        log.debug("AAF open failure details", exc_info=True)
        result.error = f"cannot open AAF: {exc}"
    return result
