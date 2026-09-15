# Slice 21 — YouTube Transcript Segmentation

**Status:** ACCEPTED
**Date:** 2026-09-15
**Reference:** `CORP_ARCHITECTURE_GATE_AND_VERTICAL_SLICES_v1.md`

## What shipped

Enhanced the YouTube transcript adapter (`captions.py`) with
pause-based segmentation, language selection, and structured metadata.
Previously, transcripts were joined into a single flat string with no
timestamps or language information.

### Changes to `corp/workers/adapters/captions.py`

- **`TranscriptSegment`** — frozen dataclass holding `text`, `start`,
  `end` for one paragraph-sized chunk of transcript.

- **`_segment_snippets()`** — groups raw youtube-transcript-api snippets
  into segments by detecting pause gaps (default 2 seconds). Also
  splits at `MAX_SEGMENT_CHARS` (1500) to avoid oversized segments,
  and merges segments shorter than `MIN_SEGMENT_CHARS` (80) into the
  next one to avoid fragments.

- **`fetch_youtube_caption()`** — enhanced with:
  - `languages` parameter (default `("en",)`) for language preference.
  - Calls `transcript.to_raw_data()` and feeds through segmentation.
  - `text` remains a flat joined string (backward-compatible for
    `Evidence.raw_text`).
  - `metadata` now includes:
    - `language` — the language code of the fetched transcript.
    - `is_generated` — whether YouTube auto-generated the captions.
    - `segment_count` — number of segments.
    - `duration` — total transcript duration in seconds.
    - `segments` — list of `{text, start, end}` dicts for
      timestamp-aware extraction.
  - Returns `None` for empty transcripts (no snippets or all-whitespace).

### Backward compatibility

- The function signature adds `languages` as an optional kwarg with a
  default value. Existing callers (`youtube.py`, `ytdlp.py`) continue
  to work unchanged.
- `NormalizedContent.text` is still the flat joined text, so
  `Evidence.raw_text` stores the same kind of data as before.
- The intelligence pipeline's `_extract_creator_side()` reads
  `caption.raw_text` from Evidence, which remains a flat string.

### Tests

- **`tests/workers/test_captions.py`** — new test file covering:
  - `_segment_snippets()`: empty input, single snippet, continuous
    snippets, pause-gap splitting, short-segment merging, max-chars
    splitting, timestamp accuracy.
  - `fetch_youtube_caption()`: segments in metadata, failure returns
    None, empty transcript returns None, language preference passthrough.
- **`tests/workers/test_youtube_adapter.py`** — updated caption mock
  to match the new `to_raw_data()` API instead of the old iterator.

## Acceptance criteria and how each is met

- **Transcript preserves timestamp information.**
  Each segment carries `start` and `end` in seconds.
- **Segments are paragraph-sized, not per-word snippets.**
  Pause-gap detection groups snippets into natural chunks.
- **Language preference is supported.**
  `languages` parameter passes through to `youtube-transcript-api`.
- **Flat text remains available for backward compatibility.**
  `NormalizedContent.text` is the full joined string.
- **No existing callers break.**
  `languages` defaults to `("en",)`, matching previous behavior.

## Verification

- `py_compile` clean on all changed/new files.
- All segmentation and fetch tests pass.
- Existing `test_youtube_adapter.py` caption tests updated and passing.

## Assumptions

- The segments are stored in `NormalizedContent.metadata`, which is
  available during collection but not persisted beyond `Evidence.raw_text`
  (the flat text). A future slice could add a dedicated transcript
  segments table or store segments in `Evidence.extra` if needed for
  timestamp-correlated extraction.
- The `youtube-transcript-api` `fetch()` method's `languages` parameter
  tries each language in order and returns the first available
  transcript. If none match, it raises an exception (caught by the
  existing error handler, returning `None`).
