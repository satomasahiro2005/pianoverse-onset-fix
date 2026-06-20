# Pianoverse Onset Fix

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

A tool that removes the ~8 ms note-onset delay baked into IK Multimedia **Pianoverse**'s
samples, and evens out its note-to-note volume — by editing the `.pak` sample containers
directly, leaving the plugin, presets, mic mixes and velocity mapping untouched.

Measured on the YF3 Close mic, the head-trim brings the onset delay from **9.3 ms down to
2.3 ms** (the aligned notes go from σ 9.0 ms to 0.27 ms), and the per-note volume pass cuts
the systematic note-to-note deviation from **1.49 dB to 0.04 dB**.

> **No Pianoverse sample audio is included in this repository** — only analysis code,
> measurements, and figures. You need your own licensed copy to use it. This is an
> interoperability / analysis project and is not affiliated with IK Multimedia; respect the
> terms of your own license/EULA.

## Contents

- [Background](#background)
- [What the delay actually is](#what-the-delay-actually-is)
- [The IKMPAK `.pak` format](#the-ikmpak-pak-format)
- [How the fix works](#how-the-fix-works)
- [Volume correction](#volume-correction)
- [Requirements](#requirements)
- [Usage](#usage)
- [Applying it to Pianoverse](#applying-it-to-pianoverse)
- [Results](#results)
- [Repository layout](#repository-layout)
- [Limitations](#limitations)
- [License](#license)

## Background

Trigger a Pianoverse note with a fixed, mechanical key-press and there's still about 8 ms
between note-on and the note actually speaking. That delay is not audio-buffer or driver
latency — it is baked into the sample data itself.

Normally you would compensate for this inside the instrument, but Pianoverse exposes no
sample-start or playback-offset control (an amplitude attack envelope only shapes the volume;
it can't move the recorded content earlier). So it can't be fixed from the plugin UI.

The sample containers (`.pak`), however, are not encrypted and hold plain WAV audio. That
makes it possible to trim the dead head off each sample and write the container back, which
fixes the delay while keeping everything else about the instrument intact.

## What the delay actually is

Onset times were measured across the YF3 Close mic for every key and all 14 velocity layers
(see `onset.csv`).

In the raw waveform, the note simply stays quiet for the first several milliseconds after
note-on (top: original; bottom: after the head-trim):

![Onset delay visible in the waveform](assets/onset_waveform.png)

Looking closer, each sample has a two-stage start:

![Attack onset structure](assets/onset_structure.png)

- For the first ~7 ms there is only a low-level (~-40 dBFS) touch/mechanical noise floor.
- At ~7–9 ms the hammer/string tone comes in. Even a treble note (A6, whose tone would
  develop in under 1 ms) has that 7 ms floor first — so it's a genuine noise lead-in, not a
  slowly-developing tone.
- The ~8 ms offset is consistent across the whole keyboard, which is what confirms it lives
  in the sample data rather than the buffer.

The delay also varies from note to note, which is what makes playing feel uneven:

![Onset vs velocity and pitch](assets/onset_dependence.png)

| Metric (time to cross, relative to the window peak) | Mean | Range |
|---|---|---|
| First content (-40 dB) | ~2 ms (≈ t0) | 0–21 ms |
| Tone onset (-20 dB) | 7.5 ms | 0.02–68 ms |
| Near peak (-12 dB) | 9.6 ms | up to 85 ms |
| Peak | 37.7 ms | 4.7–216 ms |

Softer velocities speak later (~9.5 ms at v36–45 vs ~5.5 ms at v127), and lower notes speak
later (A-1 ≈ 15 ms, mid/treble ≈ 5–9 ms).

## The IKMPAK `.pak` format

The container format was reverse-engineered. It is unencrypted and has a fixed layout:

![IKMPAK container layout](assets/pak_format.png)

```
HEADER   off0 "IKMPAK" (6 bytes) | off6 u32 version=2 | off10 u32 entryCount=N
TOC      N entries, in file order:  path\0 | u64 dataOffset | u64 dataSize
PAYLOAD  standard RIFF/WAVE files concatenated
         (each: RIFF | fmt = PCM 24-bit / 48 kHz / stereo | [bext] | [junk] | data)
```

Properties the repacker relies on:

- `fileLength == header + TOC + Σ(WAV sizes)` — no checksum, no gaps, no padding.
- The audio is 24-bit / 48 kHz / stereo PCM (exported by iZotope RX; some files carry
  `bext`/`junk` chunks).
- TOC paths encode the note, velocity (`vNNN`), round-robin (`rrN`) and pedal/envelope (`eN`).

Writing the container back is safe because:

- There is no checksum or footer to invalidate.
- There is no external byte-offset index — `Library Resources/*.pak` only holds icon PNGs, and
  `Library Info/*.pak` is ~100 bytes of metadata.
- The engine looks samples up by the path stored in the pak's own TOC, so recomputing the
  offsets keeps every reference valid.
- The engine plays each sample from frame 0 (which is exactly why the 8 ms appears), so
  trimming the head moves the onset earlier with no other change.

The `.pvsp` presets are encrypted (`I4TS` + `IKCRYPTO`), but they never need to be touched —
they only hold tone/mic/FX settings; the audio lives in the `.pak` files.

## How the fix works

For each WAV, the tool detects the perceptual onset and aligns every sample to a small,
common preroll:

```
input: WAV data chunk (24-bit/48k/stereo PCM), AnchorDb = -20, PrerollMs = 1.5

1. build a short-time envelope in 0.25 ms buckets: env[k] = max|x| over both channels (first 400 ms)
2. peak = max(env)                         # near-silent (peak < -102 dBFS) -> no trim
3. tAnchor = peak * 10^(AnchorDb / 20)      # i.e. peak - 20 dB
4. onsetFrame = first k where env[k] >= tAnchor      <- detection anchor
5. trimFrames = max(0, onsetFrame - preroll)
6. drop trimFrames from the head and fix the RIFF/data sizes by -trimBytes
```

The anchor is a peak-relative level rather than a noise-floor "foot". A foot search
(walking back from, say, peak − 45 dB) fails on bass notes, where the lead-in is loud
relative to the peak and never drops below the floor — so it finds foot = 0 and trims
nothing despite an 8 ms delay, and it disagrees between round-robins. The peak − 20 dB
crossing is the metric that measured most stable above, and it is robust across velocity,
pitch and round-robin.

The container is then rebuilt losslessly apart from the removed head:
`header + new TOC (paths kept, offsets/sizes recomputed) + the trimmed WAVs`, written as a
stream. The `fmt`/`bext`/`junk` chunks and every tail byte are preserved exactly, and the
output is checked for `fileLength == header + TOC + Σ`, zero gaps, and consistent WAV headers.

Three finishing passes run in `repack.py` (the gain pass is a whole-sample multiply, which is
too slow in PowerShell, so the full pipeline is in numpy):

- `--maxtrim` (default 20 ms): caps the trim so the very softest notes keep their natural slow
  attack instead of being cut to the bone.
- `--fade` (default 0.4 ms): a short fade-in at the cut removes the click from starting
  mid-signal.
- `--gains note_gains.csv`: applies the per-note volume correction described below.

## Volume correction

RMS was measured per sample across the YF3 Close keyboard, every key × 14 velocities
(rr1 + rr2, 2258 samples; `loudness_close_all.csv` via `analyze_loudness.py`):

![Note-to-note volume variation](assets/loudness_variation.png)

- Adjacent semitones differ by a median of 1.46 dB (90th percentile 5.3 dB) at the same
  velocity.
- Each note deviates from a smooth keyboard trend by σ 2.15 dB.
- The worst offenders stick out by several dB: F5 −5.7, F3 −4.6, A5 −3.9 (quiet); F#3 +3.6,
  D#3 +3.5, E6 +3.2 (loud).
- About 60% of that is a consistent per-note offset (the same across velocities), so a single
  gain per note corrects most of it; the remaining 40% is velocity-dependent and is left alone.
- Velocity layers are monotonic, and round-robin imbalance is small (mean 0.16 dB).

`analyze_loudness.py` writes a headroom-safe, attenuation-leaning gain per note to
`note_gains.csv`, and `repack.py --gains` applies it. On Close 1's A notes the gains land
exactly (ΔRMS ≈ the target), and the per-note deviation drops from σ 1.49 dB to 0.04 dB.

## Requirements

- Python 3 with `numpy`, `pandas`, and `matplotlib` (for `repack.py` and the figures).
- PowerShell (for the measurement sweeps).
- A licensed Pianoverse installation — the sample `.pak` files are not included here.

## Usage

Measure onset and loudness (PowerShell):

```powershell
. .\onset-sweep.ps1    -Paks @("...\Close 1\Close 1.pak") -RrFilter ''
. .\loudness-sweep.ps1 -Paks @("...\Close 1\Close 1.pak") -RrFilter ''
```

Generate the figures and the per-note gain table:

```bash
python assets/analyze_loudness.py
python assets/make_figures.py
```

Process a `.pak` — trim + cap + fade + gain, written to a new file so the original is left
in place:

```bash
python repack.py "...\Close 1\Close 1.pak" "...\Close 1\Close 1.trim.pak" \
       --preroll 1.5 --maxtrim 20 --fade 0.4 --gains note_gains.csv
```

> **Decoding note:** PowerShell's `-shl` truncates to the left operand's type when it is a
> `[byte]`, so 24-bit PCM must be assembled as
> `[int]$b[$i] + [int]$b[$i+1]*256 + [int]$b[$i+2]*65536` (cast to `int` before shifting).

## Applying it to Pianoverse

Once you have a processed `Close N.trim.pak`, swap it in (keep the backup):

1. Close Pianoverse / your DAW so the `.pak` file lock is released.
2. Rename the original aside: `Close 1.pak` → `Close 1.pak.orig`.
3. Put the processed file in place: `Close 1.trim.pak` → `Close 1.pak`.
4. Open Pianoverse and check. To revert, restore the `.orig`.

## Results

Measured before and after on YF3 Close 1 (every octave's A × 14 velocities × round-robins,
214 samples; `verify_close1.py`):

![Before / after head-trim](assets/onset_before_after.png)

- Onset delay: mean **9.3 ms → 2.3 ms**.
- Aligned notes (207 of 214): **σ 9.0 ms → 0.27 ms**, converged on the 1.5 ms preroll.
- The 7 softest notes (A5 v9, soft A-1) keep a natural late onset thanks to the cap.
- Per-note volume deviation: **1.49 dB → 0.04 dB**.

The same pipeline has been applied to the full YF3 Close set (Close 1–12).

## Repository layout

| File | Purpose |
|---|---|
| `repack.py` | Main tool: onset detection + trim (with cap) + fade + per-note gain + IKMPAK rebuild (numpy). |
| `repack.ps1` | Trim-only PowerShell version, kept as a reference implementation. |
| `pak.ps1` | `.pak` TOC parser, WAV chunk parsing, onset helpers. |
| `onset-sweep.ps1`, `loudness-sweep.ps1` | Batch onset / loudness measurement to CSV. |
| `analyze_loudness.py` | Volume analysis and the `note_gains.csv` gain table. |
| `assets/make_figures.py` | Generates the figures from the measured CSVs. |
| `verify_close1.py` | Re-measures onset and loudness before vs after. |
| `*.csv` | Measurements and the per-note gains (no audio). |

## Limitations

- **Coincident mic** is not done yet — it needs its own loudness analysis and gain table
  (the gains here are Close-specific).
- **Runtime loading** is argued safe from the format (no checksum, path-based lookup) and
  works in practice, but you should still verify after swapping a file in.
- The softest, highest notes are only partially aligned by design (the `--maxtrim` cap
  protects their natural slow attack).
- `preroll`, `maxtrim` and the correction strength are reasonable defaults, not tuned by ear.

## License

MIT — see [`LICENSE`](LICENSE). This covers the code, documentation and measurements only.
IK Multimedia's Pianoverse sample content is not included and remains under its own license.
