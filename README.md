# Pianoverse onset-delay research & `.pak` head-trim tool

IK Multimedia Pianoverse has a ~8 ms gap between note-on and the note actually speaking. This repo works out where that comes from (it's baked into the sample data, not the audio buffer), reverse-engineers the `.pak` sample container, and provides a tool that trims each sample's head so the attack speaks immediately and evenly — plus a per-note gain pass that flattens note-to-note volume bumps.

Measured on the YF3 Close mic: onset delay 9.3 → 2.3 ms (the aligned bulk goes from σ 9.0 ms to 0.27 ms), and the systematic per-note volume deviation drops from 1.49 dB to 0.04 dB.

> No Pianoverse sample audio is included here — only analysis code, measurements, and figures. You need your own licensed copy. This is interoperability/analysis research, not affiliated with IK Multimedia; respect your own license/EULA. Figures are generated from the measured data by `assets/make_figures.py`.

---

## 1. Why

- A fixed mechanical key-press still has ~8 ms between note-on and audible sound.
- It isn't audio-buffer or driver latency — it's in the sample data.
- Pianoverse exposes no sample-start / playback-offset control (an amplitude attack envelope can't move the content), so it can't be fixed inside the plugin.
- The `.pak` containers aren't encrypted and hold plain WAV, so trimming the sample heads and writing the `.pak` back fixes the delay while leaving Pianoverse's engine, presets, mics and velocity mapping untouched.

## 2. What the delay actually is

Measured across the YF3 Close mic, every key × 14 velocities (`onset.csv`).

In the raw waveform the note stays quiet for ~8 ms after note-on (top = original, bottom = head-trimmed):

![onset delay visible in the waveform](assets/onset_waveform.png)

Each sample has a two-stage start:

![attack onset structure](assets/onset_structure.png)

- First ~7 ms: only a low-level (~-40 dBFS) touch/mechanical noise floor.
- ~7–9 ms: the hammer/string tone comes in. Even on a treble note (A6, whose tone would develop in <1 ms) the 7 ms floor is there first, so it's a separate noise lead-in, not a slow tone.
- The ~8 ms is consistent across the keyboard, so it's in the data, not the buffer.

The delay varies, which is why it sounds uneven:

![onset depends on velocity and pitch](assets/onset_dependence.png)

| metric (time to cross, rel. window peak) | mean | range |
|---|---|---|
| first content (-40 dB) | ~2 ms (≈ t0) | 0–21 ms |
| tone onset (-20 dB) | 7.5 ms | 0.02–68 ms |
| near peak (-12 dB) | 9.6 ms | –85 ms |
| peak | 37.7 ms | 4.7–216 ms |

- Velocity: softer speaks later (~9.5 ms at v36–45 → ~5.5 ms at v127).
- Pitch: lower speaks later (A-1 ≈ 15 ms, mid/treble ≈ 5–9 ms).

## 3. The `.pak` (IKMPAK) format

Reverse-engineered. No encryption, fixed layout.

![IKMPAK container layout](assets/pak_format.png)

```
HEADER   off0 "IKMPAK"(6) | off6 u32 version=2 | off10 u32 entryCount=N
TOC      N entries, file order:  path\0 | u64 dataOffset | u64 dataSize
PAYLOAD  standard RIFF/WAVE concatenated (each: RIFF|fmt(PCM 24-bit/48k/stereo)|[bext]|[junk]|data)
```

Invariants the repacker relies on:

- `fileLength == header + TOC + Σ(WAV sizes)` — no checksum, no gaps, no padding.
- WAVs are 24-bit / 48 kHz / stereo PCM (iZotope RX exports, some with bext/junk).
- TOC paths encode note / velocity (vNNN) / round-robin (rrN) / pedal-env (eN).

Why writing it back is safe:

- No checksum/footer (the invariant above).
- No external byte-offset index: `Library Resources/*.pak` is just icon PNGs, `Library Info/*.pak` is ~100-byte metadata.
- The engine resolves samples by the path in the pak's own TOC, so recomputing the offsets keeps every reference valid.
- The engine plays each sample from frame 0 (that's why the 8 ms shows up), so trimming the head moves the onset earlier directly.

The `.pvsp` presets are `I4TS`+`IKCRYPTO` encrypted, but there's no need to touch them — they hold tone/mic/FX settings only; the samples live in the `.pak`.

## 4. Head-trim algorithm

Detect each WAV's perceptual onset and align all samples to a small common preroll.

```
input: WAV data chunk (24-bit/48k/stereo PCM), AnchorDb=-20, PrerollMs=1.5
1. short-time envelope, 0.25 ms buckets: env[k] = max|x| (both channels), first 400 ms
2. peak = max(env)                         # near-silent (peak < -102 dBFS) -> no trim
3. tAnchor = peak * 10^(AnchorDb/20)        # peak - 20 dB
4. onsetFrame = first k where env[k] >= tAnchor      <- detection anchor
5. trimFrames = max(0, onsetFrame - preroll)
6. drop trimFrames from the head; fix the RIFF/data sizes by -trimBytes
```

Why a peak-relative anchor (a foot search was dropped): walking back from the noise floor (peak-45 dB) fails on bass notes, where the lead-in is loud relative to the peak and never drops below the floor — so foot=0, no trim, despite an 8 ms delay, and it disagreed between round-robins (96/214 left untrimmed). The peak-20 dB crossing is the metric that measured most stable in §2 and is robust across velocity / pitch / round-robin.

Repack (lossless apart from the head): rebuild `header + new TOC (paths kept, offsets/sizes recomputed) + concatenated trimmed WAVs`, streamed. fmt/bext/junk and the tail bytes are byte-for-byte unchanged; output is checked for `fileLength == header+TOC+Σ`, zero gaps and consistent WAV headers.

### Finishing passes (`repack.py`, numpy)

The gain pass is a whole-sample multiply (too slow in PowerShell), so the full pipeline runs in numpy.

- `--maxtrim` (default 20 ms): cap the trim so the softest notes keep a natural slow attack instead of being cut to the bone.
- `--fade` (default 0.4 ms): a short fade-in at the cut removes the click from starting mid-signal.
- `--gains note_gains.csv`: per-note volume correction (§7).

### Result (YF3 Close 1 = every octave's A × 14 vel × rr, 214 samples)

![before / after head-trim](assets/onset_before_after.png)

- onset delay mean 9.3 → 2.3 ms
- aligned bulk (207/214): σ 9.0 → 0.27 ms (converged to the 1.5 ms preroll)
- the 7 softest notes (A5 v9, soft A-1) keep a natural late onset via the cap
- checked by re-measurement (`verify_close1.py`)

## 5. Tools

| file | role |
|---|---|
| `pak.ps1` | `.pak` TOC parser / WAV chunk parsing / onset helpers |
| `onset-sweep.ps1`, `loudness-sweep.ps1` | batch-measure onset / loudness → CSV |
| `repack.py` | the main one: onset detect + trim (cap) + fade + per-note gain + IKMPAK rebuild (numpy) |
| `repack.ps1` | trim-only PowerShell version (reference) |
| `assets/make_figures.py`, `analyze_loudness.py` | figures (PNG) + `note_gains.csv` from the measured CSVs |
| `verify_close1.py` | re-measure onset/loudness before vs after |
| `onset*.csv`, `loudness*.csv`, `note_gains.csv` | measurements and gains |

```powershell
# measure (onset / loudness)
. .\onset-sweep.ps1    -Paks @("...\Close 1\Close 1.pak") -RrFilter ''
. .\loudness-sweep.ps1 -Paks @("...\Close 1\Close 1.pak") -RrFilter ''
```
```bash
# figures + per-note gain table
python assets/analyze_loudness.py
python assets/make_figures.py

# trim + cap + fade + gain, written to a copy (original untouched)
python repack.py "...\Close 1\Close 1.pak" "...\Close 1\Close 1.trim.pak" \
       --preroll 1.5 --maxtrim 20 --fade 0.4 --gains note_gains.csv
```

> Decoding note: PowerShell's `-shl` truncates to the left operand's type when it's a `[byte]`, so build 24-bit PCM as `[int]$b[$i] + [int]$b[$i+1]*256 + [int]$b[$i+2]*65536` (cast to int before shifting).

## 6. Status

- [x] `.pak` (IKMPAK) format, confirmed unencrypted
- [x] delay shown to be in the sample data (noise lead-in → tone at ~8 ms)
- [x] head-trim repacker (lossless rebuild, verified)
- [x] volume study + per-note gain correction (std 1.49 → 0.04 dB)
- [x] full pipeline `repack.py` (trim+cap+fade+gain), applied to all YF3 Close paks, before/after verified
- [ ] Coincident mic (needs its own loudness analysis / gain table)
- [ ] tune preroll / maxtrim / correction strength by ear

### Swap procedure (keep a backup)

1. Close Pianoverse / the DAW (release the `.pak` file lock).
2. Move the original aside: `Close 1.pak` → `Close 1.pak.orig`.
3. Put the processed file in place: `Close 1.trim.pak` → `Close 1.pak`.
4. Open Pianoverse and check. To revert, restore the `.orig`.

## 7. Volume variation

RMS per sample across the YF3 Close keyboard, every key × 14 vel (rr1+rr2, 2258 samples, `loudness_close_all.csv` → `analyze_loudness.py`).

![note-to-note volume variation](assets/loudness_variation.png)

- adjacent-semitone level difference: median 1.46 dB, 90th pct 5.3 dB (same velocity, neighbouring keys differ).
- deviation from a smooth trend: σ 2.15 dB.
- outliers: F5 -5.7 dB, F3 -4.6, A5 -3.9 (quiet); F#3 +3.6, D#3 +3.5, E6 +3.2 (loud).
- 60% of that is a consistent per-note offset (same across velocities), so one gain per note fixes ~60% (the other 40% is velocity-dependent).
- velocity layers are monotonic, round-robin imbalance is small (mean 0.16 dB).

`analyze_loudness.py` writes the per-note gains (`note_gains.csv`, headroom-safe, attenuation-leaning); `repack.py --gains` applies them. Verified on Close 1's A notes: gains land exactly (ΔRMS ≈ target), per-note deviation std 1.49 → 0.04 dB (A5's -3.9 dB → +3.9 dB correction, residual ≈ 0). Velocity-dependent variation is left alone.

## 8. Known issues (self-review)

- [x] over-trimming soft/high notes → `--maxtrim 20ms` (A5 v9's 112 ms cut is capped; the 7 softest notes keep a natural onset).
- [x] no fade at the cut → `--fade 0.4ms` fade-in, removes the click.
- [ ] Pianoverse runtime loading: argued safe from the format (no checksum, path lookup) and confirmed working in practice, but still verify after a swap.
- onset metric window differs slightly between measurement (250 ms) and trim (400 ms) — minor.

## 9. Notes / backups / license

- Personal use and analysis only. No sample redistribution; no circumventing the `.pvsp` encryption.
- Originals are kept as renamed `.orig` backups, and are also recoverable from the installer.
- Code, docs and measurements are MIT (`LICENSE`). IK Multimedia sample content is not included and stays under its own license.
