# Code Review

## Findings

1. **Compose/midi import never produce `PartNode`s, so instrumentation is ignored during playback**  
   - `Score._build_ast_from_elements` just appends bare `PartDeclarationNode` objects to the root (`src/aldakit/score.py:325-346`), and `midi_to_ast` mirrors the same pattern when importing a SMF (`src/aldakit/midi/midi_to_ast.py:235-303`). The MIDI generator only switches instruments when it sees a `PartNode` (`src/aldakit/midi/generator.py:119-172`), so those declarations are completely ignored. As a result, `Score.from_elements(part("violin"), note("c"))` or any score created via `Score.from_midi_file()` will always play on the implicit `_default` part (program 0) regardless of the declared instrument, and multi-part imports collapse into a single channel. This breaks the advertised compose API and makes MIDI→Alda→MIDI round-trips lose orchestration information.  
   - *Fix*: while building an AST outside the parser, wrap each declaration and its events in a `PartNode`, or teach `MidiGenerator` how to pair a standalone `PartDeclarationNode` with the following `EventSequenceNode`.

2. **`Score.to_alda()` drops part declarations altogether**  
   - `_ast_to_alda` never handles `PartNode`; it only has special logic for `PartDeclarationNode` and otherwise treats any object with an `.events` attribute as a plain sequence (`src/aldakit/score.py:58-105`). When you import a MIDI file (which should produce `PartNode`s once issue #1 is fixed) and call `score.to_alda()`, all `piano:`/`violin:` headers disappear, so the exported Alda is no longer part-aware.  
   - *Fix*: add an explicit branch that renders a `PartNode` as `<part decl>\n  <events>` so the part structure survives round-trips.

3. **`Score.to_alda()` crashes on chords imported from MIDI**  
   - The chord branch in `_ast_to_alda` appends `duration_to_str(node.duration)` (`src/aldakit/score.py:73-76`), but `ChordNode` does not expose a `duration` attribute (only its individual `NoteNode`s carry durations). Any imported score that contains a chord will therefore raise `AttributeError: 'ChordNode' object has no attribute 'duration'` when converted back to Alda, making the advertised MIDI→Alda workflow unusable in that common case.  
   - *Fix*: derive the chord duration from the first note (matching Alda syntax) instead of referencing a non-existent field.

4. **Variable definitions are executed immediately instead of being declarative**  
   - `_process_variable_definition` stores the events *and* immediately replays them (`src/aldakit/midi/generator.py:386-394`). In Alda (and in your README example under “Variables”), `riff = c8 d e f` should not emit sound until the variable is referenced. With the current implementation every definition doubles the material (definition + each reference) and there is no way to create library/helper variables.  
   - *Fix*: record the `EventSequenceNode` in `self.state.variables` but do not process it until a `VariableReferenceNode` is visited. Add tests that assert `parse("theme = c d e").children` produces zero notes.

5. **Tempo maps are mangled when writing MIDI files**  
   - `_build_tempo_track` calls `_seconds_to_ticks(tc.time, ..., current_tempo_us)` while *also* mutating `current_tempo_us` before the next event (`src/aldakit/midi/smf.py:112-140`). This converts an absolute timestamp using the *post-change* tempo, so every tempo change after the first is scheduled at the wrong tick.  
   - `_build_channel_track` converts note/program/control times using a single `default_tempo_us` (`src/aldakit/midi/smf.py:143-197`), so channel events never line up with the tempo changes written to track 0—any ritardando/accelerando is flattened back into the initial BPM.  
   - *Fix*: accumulate ticks by measuring the delta between successive tempo-change times with the tempo that was in effect for that span, and apply the exact same timeline when translating note start/end times so channel tracks stay synchronized with track 0. Add regression tests that write/read a MIDI with multiple tempi.

## Suggested Next Steps
- Decide whether to fix the AST shape (preferred) or teach the MIDI generator to accept a “loose” representation so compose/imported content can honor parts/instruments.
- Extend `_ast_to_alda` to cover `PartNode` explicitly and to derive chord durations from note data; add round-trip tests with chords and multiple parts.
- Adjust the MIDI generator and writer logic per the findings above and add tests for variable declarations and tempo-changing files to prevent regressions.
