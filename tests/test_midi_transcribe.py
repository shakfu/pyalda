"""Tests for MIDI transcription functionality."""

import pytest

from aldakit.midi.transcriber import (
    TranscribeSession,
    PendingNote,
    RecordedNote,
    list_input_ports,
)
from aldakit.compose.core import Note, Rest, Cram, Chord


# =============================================================================
# TranscribeSession Unit Tests
# =============================================================================


class TestTranscribeSession:
    """Tests for TranscribeSession internal logic."""

    def test_init_defaults(self):
        """Session initializes with correct defaults."""
        session = TranscribeSession()
        assert session.port_name is None
        assert session.quantize_grid == 0.25
        assert session.default_tempo == 120.0
        assert not session._running

    def test_notes_to_seq_empty(self):
        """Empty notes produce empty Seq."""
        session = TranscribeSession()
        session._recorded_notes = []
        seq = session._notes_to_seq()
        assert len(seq.elements) == 0

    def test_notes_to_seq_single_note(self):
        """Single note converts correctly."""
        session = TranscribeSession(default_tempo=120.0)
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.5)
        ]
        seq = session._notes_to_seq()
        assert len(seq.elements) == 1
        note = seq.elements[0]
        assert isinstance(note, Note)
        assert note.pitch == "c"
        assert note.octave == 4
        assert note.duration == 4  # quarter note
        assert note.dots == 0

    def test_notes_to_seq_multiple_notes(self):
        """Multiple notes convert correctly."""
        session = TranscribeSession(default_tempo=120.0)
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.5),
            RecordedNote(pitch=62, velocity=100, start_time=0.5, duration=0.5),
            RecordedNote(pitch=64, velocity=100, start_time=1.0, duration=0.5),
        ]
        seq = session._notes_to_seq()
        assert len(seq.elements) == 3
        assert all(isinstance(e, Note) for e in seq.elements)
        assert seq.elements[0].pitch == "c"
        assert seq.elements[1].pitch == "d"
        assert seq.elements[2].pitch == "e"

    def test_notes_to_seq_with_gap_inserts_rest(self):
        """Gap between notes inserts a rest."""
        session = TranscribeSession(default_tempo=120.0)
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.5),
            # 0.5 second gap (one beat at 120 BPM)
            RecordedNote(pitch=62, velocity=100, start_time=1.5, duration=0.5),
        ]
        seq = session._notes_to_seq()
        # Should have: note, rest, note
        assert len(seq.elements) == 3
        assert isinstance(seq.elements[0], Note)
        assert isinstance(seq.elements[1], Rest)
        assert isinstance(seq.elements[2], Note)

    def test_notes_to_seq_accidentals(self):
        """Sharps are correctly detected."""
        session = TranscribeSession(default_tempo=120.0)
        session._recorded_notes = [
            RecordedNote(pitch=61, velocity=100, start_time=0.0, duration=0.5),  # C#
        ]
        seq = session._notes_to_seq()
        assert len(seq.elements) == 1
        note = seq.elements[0]
        assert note.pitch == "c"
        assert note.accidental == "+"

    def test_notes_to_seq_dotted_values(self):
        """Durations that fall on dotted grid emit dot counts."""
        session = TranscribeSession(default_tempo=120.0)
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.375)
        ]
        seq = session._notes_to_seq()
        note = seq.elements[0]
        assert note.duration == 8
        assert note.dots == 1

    def test_notes_to_seq_creates_ties(self):
        """Durations longer than catalog split into tied notes."""
        session = TranscribeSession(default_tempo=120.0)
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=1.25)
        ]  # 2.5 beats
        seq = session._notes_to_seq()
        assert len(seq.elements) == 2
        first, second = seq.elements
        assert isinstance(first, Note) and isinstance(second, Note)
        assert first.slurred is True
        assert second.slurred is False
        assert first.duration == 2  # half note
        assert second.duration == 8  # followed by eighth note

    def test_triplet_feel_quantizes_triplet_eighths(self):
        """Triplet feel produces twelfth-note durations."""
        session = TranscribeSession(default_tempo=120.0, feel="triplet")
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.1667)
        ]
        seq = session._notes_to_seq()
        assert isinstance(seq.elements[0], Note)
        assert seq.elements[0].duration == 12

    def test_quintuplet_feel_quantizes(self):
        """Quintuplet feel produces twentieth-note durations."""
        session = TranscribeSession(default_tempo=120.0, feel="quintuplet")
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.1)
        ]
        seq = session._notes_to_seq()
        assert isinstance(seq.elements[0], Note)
        assert seq.elements[0].duration == 20

    def test_swing_feel_alternates_ratios(self):
        """Swing feel alternates long/short subdivisions."""
        session = TranscribeSession(default_tempo=120.0, feel="swing")
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.25),
            RecordedNote(pitch=62, velocity=100, start_time=0.25, duration=0.25),
        ]
        seq = session._notes_to_seq()
        assert isinstance(seq.elements[0], Note)
        assert seq.elements[0].duration == 6  # two-thirds beat
        assert isinstance(seq.elements[1], Note)
        assert seq.elements[1].duration == 12  # one-third beat

    def test_seq_metadata_includes_feel(self):
        """Seq metadata exposes feel and swing ratio."""
        session = TranscribeSession(default_tempo=120.0, feel="swing", swing_ratio=0.62)
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.25)
        ]
        seq = session._notes_to_seq()
        assert seq.metadata["feel"] == "swing"
        assert seq.metadata["swing_ratio"] == pytest.approx(0.62)

    def test_seq_metadata_includes_tuplet_division(self):
        """Tuplet feels record their division."""
        session = TranscribeSession(default_tempo=120.0, feel="quintuplet")
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.1)
        ]
        seq = session._notes_to_seq()
        assert seq.metadata["feel"] == "quintuplet"
        assert seq.metadata["tuplet_division"] == 5

    def test_triplet_sequences_collapsed_to_cram(self):
        """Triplet subdivisions are wrapped in cram expressions."""
        session = TranscribeSession(default_tempo=120.0, feel="triplet")
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=0.1667),
            RecordedNote(pitch=62, velocity=100, start_time=0.1667, duration=0.1667),
            RecordedNote(pitch=64, velocity=100, start_time=0.3334, duration=0.1667),
        ]
        seq = session._notes_to_seq()
        assert isinstance(seq.elements[0], Cram)
        assert seq.elements[0].duration == 4
        assert len(seq.elements[0].elements) == 3

    def test_quintuplet_sequences_collapsed(self):
        """Quintuplet subdivisions collapse into cram expressions."""
        session = TranscribeSession(default_tempo=120.0, feel="quintuplet")
        base = 0.1
        session._recorded_notes = [
            RecordedNote(pitch=60 + i, velocity=100, start_time=i * base, duration=base)
            for i in range(5)
        ]
        seq = session._notes_to_seq()
        assert isinstance(seq.elements[0], Cram)
        assert len(seq.elements[0].elements) == 5

    def test_chord_tuplets_form_cram_chords(self):
        """Simultaneous notes stay as chords inside cram expressions."""
        session = TranscribeSession(default_tempo=120.0, feel="triplet")
        base = 0.1667
        session._recorded_notes = [
            RecordedNote(pitch=60, velocity=100, start_time=0.0, duration=base),
            RecordedNote(pitch=64, velocity=100, start_time=0.0, duration=base),
            RecordedNote(pitch=67, velocity=100, start_time=0.0, duration=base),
            RecordedNote(pitch=60, velocity=100, start_time=base, duration=base),
            RecordedNote(pitch=64, velocity=100, start_time=base, duration=base),
            RecordedNote(pitch=67, velocity=100, start_time=base, duration=base),
            RecordedNote(pitch=60, velocity=100, start_time=base * 2, duration=base),
            RecordedNote(pitch=64, velocity=100, start_time=base * 2, duration=base),
            RecordedNote(pitch=67, velocity=100, start_time=base * 2, duration=base),
        ]
        seq = session._notes_to_seq()
        assert isinstance(seq.elements[0], Cram)
        assert all(isinstance(elem, Chord) for elem in seq.elements[0].elements)

    def test_note_on_off_tracking(self):
        """Note on/off events are tracked correctly."""
        session = TranscribeSession()
        session._running = True
        session._start_time = 0.0

        # Note on
        session._note_on(60, 100, 0.0)
        assert 60 in session._pending_notes
        assert session._pending_notes[60].pitch == 60
        assert session._pending_notes[60].velocity == 100

        # Note off
        session._note_off(60, 0.5)
        assert 60 not in session._pending_notes
        assert len(session._recorded_notes) == 1
        assert session._recorded_notes[0].pitch == 60
        assert session._recorded_notes[0].duration == 0.5

    def test_note_on_callback(self):
        """Note on callback is invoked."""
        session = TranscribeSession()
        session._running = True

        notes_received = []

        def callback(pitch, velocity, is_on):
            notes_received.append((pitch, velocity, is_on))

        session.on_note(callback)

        session._note_on(60, 100, 0.0)
        session._note_off(60, 0.5)

        assert len(notes_received) == 2
        assert notes_received[0] == (60, 100, True)
        assert notes_received[1] == (60, 0, False)


class TestListInputPorts:
    """Tests for list_input_ports function."""

    def test_returns_list(self):
        """Function returns a list."""
        ports = list_input_ports()
        assert isinstance(ports, list)
        # Note: May be empty if no MIDI devices connected


class TestPendingNote:
    """Tests for PendingNote dataclass."""

    def test_creation(self):
        """PendingNote can be created."""
        note = PendingNote(pitch=60, velocity=100, start_time=0.5)
        assert note.pitch == 60
        assert note.velocity == 100
        assert note.start_time == 0.5


class TestRecordedNote:
    """Tests for RecordedNote dataclass."""

    def test_creation(self):
        """RecordedNote can be created."""
        note = RecordedNote(pitch=60, velocity=100, start_time=0.5, duration=1.0)
        assert note.pitch == 60
        assert note.velocity == 100
        assert note.start_time == 0.5
        assert note.duration == 1.0


# =============================================================================
# MidiIn Binding Tests
# =============================================================================


try:
    import aldakit._libremidi as _libremidi  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - depends on build features
    _libremidi = None


@pytest.mark.skipif(_libremidi is None, reason="libremidi extension not available")
class TestMidiInBindings:
    """Tests for MidiIn C++ bindings."""

    def test_midi_in_creation(self):
        """MidiIn can be instantiated."""
        from aldakit._libremidi import MidiIn

        midi_in = MidiIn()
        assert midi_in is not None

    def test_midi_in_poll_empty(self):
        """Poll returns empty list when no messages."""
        from aldakit._libremidi import MidiIn

        midi_in = MidiIn()
        messages = midi_in.poll()
        assert isinstance(messages, list)
        assert len(messages) == 0

    def test_midi_in_has_messages(self):
        """has_messages returns False when empty."""
        from aldakit._libremidi import MidiIn

        midi_in = MidiIn()
        assert not midi_in.has_messages()

    def test_midi_in_is_port_open(self):
        """is_port_open returns False before opening."""
        from aldakit._libremidi import MidiIn

        midi_in = MidiIn()
        assert not midi_in.is_port_open()


@pytest.mark.skipif(_libremidi is None, reason="libremidi extension not available")
class TestMidiMessage:
    """Tests for MidiMessage binding."""

    def test_midi_message_creation(self):
        """MidiMessage can be instantiated."""
        from aldakit._libremidi import MidiMessage

        msg = MidiMessage()
        assert msg is not None
        assert hasattr(msg, "bytes")
        assert hasattr(msg, "timestamp")
