# TODO

## Future Features

### Transcription Expressiveness

- [x] Implemented real-time ties, swing/triplet/quintuplet quantization, and per-track tempo events.
- [x] Surface tuplets and swing metadata back through the compose API so callers can tweak ratios post-recording.
- [x] Teach the quantizer how to collapse tied tuplets into `{ ... }` cram expressions for denser notation.
- [x] Extend chord transcription so block chords inherit ties/tuplets rather than reverting to the nearest straight duration.

### CLI & UX Enhancements

Improve ergonomics for live workflows:
- [x] Added regression tests that execute key CLI paths (stdin streaming, version flag) with mocked backends.
- [ ] Provide `--monitor` and `--metronome` helpers when transcribing to keep performers on grid.

### Conditional Full Bindings

The bundled `_libremidi` extension defaults to the minimal feature set. Add conditional build logic to detect optional dependencies and enable the richer polling/observer APIs when available:

- Check for `boost` and `readerwriterqueue` availability in CMake
- On macOS: `brew install boost readerwriterqueue`
- Define `LIBREMIDI_FULL_BINDINGS` preprocessor macro when deps found
- Use `#ifdef` in `_libremidi.cpp` to conditionally compile full vs minimal bindings

This keeps zero-dependency wheels lean, yet unlocks responsive MIDI I/O for contributors who install the optional toolchain.
