"""Real-time MIDI input transcription."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Callable, Literal

from .._libremidi import (  # type: ignore[import-not-found]
    MidiIn,
    MidiMessage,
    Observer,
)
from ..compose.attributes import Tempo
from ..compose.core import Note, Rest, Seq, Cram, Chord
from ..compose.part import Part
from ..score import Score
from .midi_to_ast import (
    beats_to_duration,
    duration_value_to_beats,
    midi_pitch_to_note,
)

if TYPE_CHECKING:
    from ..score import Score

# -----------------------------------------------------------------------------
# Transcription timing constants
# -----------------------------------------------------------------------------

# Maximum time difference (seconds) for notes to be grouped into a chord.
# Notes starting within this window are considered simultaneous.
CHORD_GROUPING_TOLERANCE_SECONDS = 0.002

# Minimum gap (seconds) between notes before inserting a rest.
# Gaps smaller than this are absorbed into the preceding note.
MIN_REST_GAP_SECONDS = 0.05

# Swing detection range (beats). Notes with durations in this range
# are candidates for swing quantization (long/short alternation).
SWING_DETECTION_MIN_BEATS = 0.15
SWING_DETECTION_MAX_BEATS = 0.85


@dataclass
class PendingNote:
    """A note that has been started but not yet released."""

    pitch: int
    velocity: int
    start_time: float  # In seconds


@dataclass
class RecordedNote:
    """A completed note with start time and duration."""

    pitch: int
    velocity: int
    start_time: float
    duration: float


@dataclass
class TranscribeSession:
    """A real-time MIDI transcription session.

    Records incoming MIDI notes and converts them to aldakit compose elements.

    Example:
        >>> session = TranscribeSession()
        >>> session.start()  # Opens MIDI input
        >>> # Play some notes on your MIDI keyboard...
        >>> time.sleep(5)
        >>> score = session.stop()  # Returns a Score with recorded notes
        >>> print(score.to_alda())
    """

    port_name: str | None = None
    quantize_grid: float = 0.25  # Quantize to 16th notes
    default_tempo: float = 120.0
    feel: Literal["straight", "swing", "triplet", "quintuplet"] = "straight"
    swing_ratio: float = 2.0 / 3.0  # Portion of beat for the long swing note

    # Internal state
    _midi_in: MidiIn | None = field(default=None, repr=False)
    _pending_notes: dict[int, PendingNote] = field(default_factory=dict, repr=False)
    _recorded_notes: list[RecordedNote] = field(default_factory=list, repr=False)
    _start_time: float = field(default=0.0, repr=False)
    _running: bool = field(default=False, repr=False)
    _on_note: Callable[[int, int, bool], None] | None = field(default=None, repr=False)
    _swing_next_is_long: bool = field(default=True, repr=False)

    def list_input_ports(self) -> list[str]:
        """List available MIDI input ports."""
        observer = Observer()
        return [p.display_name for p in observer.get_input_ports()]

    def start(self, port_name: str | None = None) -> None:
        """Start recording MIDI input.

        Args:
            port_name: MIDI input port name. If None, uses the first available port.

        Raises:
            RuntimeError: If no MIDI input ports are available.
        """
        if self._running:
            return

        self._midi_in = MidiIn()
        observer = Observer()
        input_ports = observer.get_input_ports()

        if not input_ports:
            raise RuntimeError("No MIDI input ports available")

        # Find the requested port or use the first one
        target_port = None
        if port_name:
            for port in input_ports:
                if port_name.lower() in port.display_name.lower():
                    target_port = port
                    break
            if target_port is None:
                raise RuntimeError(f"MIDI input port '{port_name}' not found")
        else:
            target_port = input_ports[0]

        err = self._midi_in.open_port(target_port)
        if err:
            raise RuntimeError(f"Failed to open MIDI port: {err}")

        self._pending_notes = {}
        self._recorded_notes = []
        self._start_time = time.time()
        self._running = True
        self._swing_next_is_long = True

    def stop(self) -> Seq:
        """Stop recording and return the recorded notes as a Seq.

        Returns:
            A Seq containing the recorded notes.
        """
        if not self._running:
            return Seq()

        # Process any remaining messages
        self.poll()

        # Close any pending notes
        end_time = time.time() - self._start_time
        for pitch, pending in self._pending_notes.items():
            duration = end_time - pending.start_time
            self._recorded_notes.append(
                RecordedNote(
                    pitch=pending.pitch,
                    velocity=pending.velocity,
                    start_time=pending.start_time,
                    duration=max(0.1, duration),
                )
            )

        self._running = False
        if self._midi_in:
            self._midi_in.close_port()
            self._midi_in = None
        self._swing_next_is_long = True

        # Convert recorded notes to Seq
        return self._notes_to_seq()

    def poll(self) -> None:
        """Poll for incoming MIDI messages. Call this periodically."""
        if not self._running or not self._midi_in:
            return

        current_time = time.time() - self._start_time
        messages = self._midi_in.poll()

        for msg in messages:
            self._process_message(msg, current_time)

    def _process_message(self, msg: MidiMessage, current_time: float) -> None:
        """Process a single MIDI message."""
        if len(msg.bytes) < 2:
            return

        status = msg.bytes[0]
        msg_type = status & 0xF0

        if msg_type == 0x90 and len(msg.bytes) >= 3:
            # Note On
            pitch = msg.bytes[1]
            velocity = msg.bytes[2]

            if velocity == 0:
                # Note On with velocity 0 = Note Off
                self._note_off(pitch, current_time)
            else:
                self._note_on(pitch, velocity, current_time)

        elif msg_type == 0x80 and len(msg.bytes) >= 3:
            # Note Off
            pitch = msg.bytes[1]
            self._note_off(pitch, current_time)

    def _note_on(self, pitch: int, velocity: int, time: float) -> None:
        """Handle a note on event."""
        # If there's already a pending note at this pitch, end it first
        if pitch in self._pending_notes:
            self._note_off(pitch, time)

        self._pending_notes[pitch] = PendingNote(
            pitch=pitch, velocity=velocity, start_time=time
        )

        if self._on_note:
            self._on_note(pitch, velocity, True)

    def _note_off(self, pitch: int, time: float) -> None:
        """Handle a note off event."""
        if pitch not in self._pending_notes:
            return

        pending = self._pending_notes.pop(pitch)
        duration = time - pending.start_time

        self._recorded_notes.append(
            RecordedNote(
                pitch=pending.pitch,
                velocity=pending.velocity,
                start_time=pending.start_time,
                duration=max(0.01, duration),  # Minimum duration
            )
        )

        if self._on_note:
            self._on_note(pitch, 0, False)

    def _notes_to_seq(self) -> Seq:
        """Convert recorded notes to a Seq."""
        if not self._recorded_notes:
            return Seq()

        sorted_notes = sorted(self._recorded_notes, key=lambda n: n.start_time)
        groups = self._group_notes(sorted_notes)
        elements: list = []
        current_time = 0.0

        for group in groups:
            start_time = group[0].start_time
            gap_seconds = start_time - current_time
            if gap_seconds > MIN_REST_GAP_SECONDS:
                gap_beats = self._seconds_to_beats(gap_seconds)
                rest_segments = self._segments_for_beats(gap_beats, kind="rest")
                gained = self._append_rest_segments(rest_segments, elements)
                current_time += self._beats_to_seconds(gained)

            duration_seconds = max(n.duration for n in group)
            duration_beats = self._seconds_to_beats(duration_seconds)
            note_segments = self._segments_for_beats(duration_beats, kind="note")
            if not note_segments:
                continue

            gained = self._append_group_segments(group, note_segments, elements)
            current_time = start_time + duration_seconds

        metadata: dict[str, object] = {
            "feel": self.feel,
            "quantize_grid": self.quantize_grid,
        }
        if self.feel == "swing":
            metadata["swing_ratio"] = self.swing_ratio
        elif self.feel == "triplet":
            metadata["tuplet_division"] = 3
        elif self.feel == "quintuplet":
            metadata["tuplet_division"] = 5

        collapsed_elements = self._collapse_tuplets(elements, metadata)
        return Seq(elements=collapsed_elements, metadata=metadata)

    def _group_notes(self, notes: list[RecordedNote]) -> list[list[RecordedNote]]:
        groups: list[list[RecordedNote]] = []
        current_group: list[RecordedNote] = []
        current_start: float | None = None

        for note in notes:
            if (
                current_group
                and current_start is not None
                and abs(note.start_time - current_start)
                > CHORD_GROUPING_TOLERANCE_SECONDS
            ):
                groups.append(current_group)
                current_group = []
                current_start = None

            if not current_group:
                current_start = note.start_time
            current_group.append(note)

        if current_group:
            groups.append(current_group)

        return groups

    def _seconds_to_beats(self, seconds: float) -> float:
        return seconds * self.default_tempo / 60.0

    def _beats_to_seconds(self, beats: float) -> float:
        return beats * 60.0 / self.default_tempo

    def _grid_value(self) -> float:
        if self.feel == "triplet":
            return 1.0 / 3.0
        if self.feel == "quintuplet":
            return 0.2
        return self.quantize_grid

    def _quantize_beats(self, beats: float, *, kind: str) -> float:
        beats = max(beats, 0.0)
        grid = self._grid_value()

        if kind == "note" and self.feel == "swing":
            if SWING_DETECTION_MIN_BEATS < beats < SWING_DETECTION_MAX_BEATS:
                long = max(0.0, min(1.0, self.swing_ratio))
                short = max(0.0, 1.0 - long)
                target = long if self._swing_next_is_long else short
                self._swing_next_is_long = not self._swing_next_is_long
                return target
            self._swing_next_is_long = True

        if grid > 0:
            return round(beats / grid) * grid
        return beats

    def _segments_for_beats(
        self, beats: float, *, kind: str
    ) -> list[tuple[int, int, float]]:
        quantized = self._quantize_beats(beats, kind=kind)
        return self._segment_beats(max(quantized, 0.0))

    def _segment_beats(self, beats: float) -> list[tuple[int, int, float]]:
        segments: list[tuple[int, int, float]] = []
        remaining = beats
        grid = self._grid_value()
        tolerance = max(grid / 16.0 if grid else 0.005, 0.005)

        while remaining > tolerance:
            denom, dots = beats_to_duration(remaining)
            length = duration_value_to_beats(denom, dots)
            if length <= 0:
                break
            segments.append((denom, dots, length))
            remaining = max(0.0, remaining - length)

        return segments

    def _append_rest_segments(
        self, segments: list[tuple[int, int, float]], elements: list
    ) -> float:
        total = 0.0
        for denom, dots, length in segments:
            elements.append(Rest(duration=denom, dots=dots))
            total += length
        return total

    def _append_group_segments(
        self,
        group: list[RecordedNote],
        segments: list[tuple[int, int, float]],
        elements: list,
    ) -> float:
        total = 0.0
        is_chord = len(group) > 1
        note_infos = [
            midi_pitch_to_note(note.pitch) for note in group
        ]  # (letter, octave, accidentals)

        for idx, (denom, dots, length) in enumerate(segments):
            slur = idx < len(segments) - 1
            if is_chord:
                chord_notes = []
                for letter, octave, accidentals in note_infos:
                    accidental = accidentals[0] if accidentals else None
                    chord_notes.append(
                        Note(
                            pitch=letter,
                            duration=None,
                            dots=0,
                            octave=octave,
                            accidental=accidental,
                            slurred=slur,
                        )
                    )
                elements.append(
                    Chord(
                        notes=tuple(chord_notes),
                        duration=denom,
                        dots=dots,
                    )
                )
            else:
                letter, octave, accidentals = note_infos[0]
                accidental = accidentals[0] if accidentals else None
                elements.append(
                    Note(
                        pitch=letter,
                        duration=denom,
                        dots=dots,
                        octave=octave,
                        accidental=accidental,
                        slurred=slur,
                    )
                )
            total += length

        return total

    def _collapse_tuplets(self, elements: list, metadata: dict[str, object]) -> list:
        raw_division = metadata.get("tuplet_division")
        if not isinstance(raw_division, int):
            return elements

        if raw_division <= 1:
            return elements

        division = raw_division

        target_beats = 1.0 / division
        tolerance = target_beats / 8.0

        new_elements: list = []
        buffer: list = []
        buffer_beats = 0.0

        def flush_buffer() -> None:
            nonlocal buffer, buffer_beats
            if buffer:
                new_elements.extend(buffer)
            buffer = []
            buffer_beats = 0.0

        for elem in elements:
            beats = self._element_beats(elem)
            if beats is None or abs(beats - target_beats) > tolerance:
                flush_buffer()
                new_elements.append(elem)
                continue

            buffer.append(self._strip_slur(elem))
            buffer_beats += beats

            if len(buffer) == division:
                base_duration, base_dots = beats_to_duration(division * target_beats)
                if abs(buffer_beats - division * target_beats) <= tolerance * division:
                    new_elements.append(
                        Cram(
                            elements=list(buffer),
                            duration=base_duration,
                            dots=base_dots,
                        )
                    )
                else:
                    new_elements.extend(buffer)
                buffer = []
                buffer_beats = 0.0

        flush_buffer()
        return new_elements

    def _element_beats(self, element) -> float | None:
        if isinstance(element, Note) and element.duration is not None:
            return duration_value_to_beats(element.duration, element.dots)
        if isinstance(element, Rest) and element.duration is not None:
            return duration_value_to_beats(element.duration, element.dots)
        if isinstance(element, Chord) and element.duration is not None:
            return duration_value_to_beats(
                element.duration, getattr(element, "dots", 0)
            )
        return None

    @staticmethod
    def _strip_slur(element):
        if isinstance(element, Note) and element.slurred:
            return replace(element, slurred=False)
        if isinstance(element, Chord):
            stripped_notes = [
                replace(note, slurred=False) if note.slurred else note
                for note in element.notes
            ]
            return replace(element, notes=tuple(stripped_notes))
        return element

    def on_note(self, callback: Callable[[int, int, bool], None]) -> None:
        """Set a callback for note events.

        The callback receives (pitch, velocity, is_note_on).
        """
        self._on_note = callback


def transcribe(
    duration: float = 10.0,
    port_name: str | None = None,
    instrument: str = "piano",
    quantize_grid: float = 0.25,
    tempo: float = 120.0,
    feel: Literal["straight", "swing", "triplet", "quintuplet"] = "straight",
    swing_ratio: float = 2.0 / 3.0,
    on_note: Callable[[int, int, bool], None] | None = None,
    poll_interval: float = 0.01,
) -> "Score":  # noqa: F821
    """Record MIDI input and return a Score.

    This is a blocking function that records for the specified duration.

    Args:
        duration: Recording duration in seconds.
        port_name: MIDI input port name. If None, uses the first available port.
        instrument: Instrument name for the part.
        quantize_grid: Grid size in beats for quantization (0.25 = 16th notes).
        tempo: Tempo in BPM for duration calculations.
        feel: Quantization feel ("straight", "swing", "triplet", "quintuplet").
        swing_ratio: Portion of the beat allocated to the long swing note.
        on_note: Optional callback for note events (pitch, velocity, is_note_on).
        poll_interval: How often to poll for MIDI messages (seconds).

    Returns:
        A Score containing the recorded notes.

    Example:
        >>> from aldakit.midi.transcriber import transcribe
        >>> print("Recording for 10 seconds...")
        >>> score = transcribe(duration=10)
        >>> score.play()
    """

    session = TranscribeSession(
        port_name=port_name,
        quantize_grid=quantize_grid,
        default_tempo=tempo,
        feel=feel,
        swing_ratio=swing_ratio,
    )

    if on_note:
        session.on_note(on_note)

    session.start(port_name)

    # Record for the specified duration
    start = time.time()
    while time.time() - start < duration:
        session.poll()
        time.sleep(poll_interval)

    seq = session.stop()

    # Build a Score from the recorded notes

    elements = [Part(instruments=(instrument,)), Tempo(bpm=tempo)]
    elements.extend(seq.elements)

    return Score.from_elements(*elements)


def list_input_ports() -> list[str]:
    """List available MIDI input ports.

    Returns:
        List of port names.
    """
    observer = Observer()
    return [p.display_name for p in observer.get_input_ports()]
