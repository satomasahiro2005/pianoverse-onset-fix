#!/usr/bin/env python3
"""Keyboard-wide loudness variation, BEFORE (original .orig) vs AFTER (per-note
gain, live .pak). Onset-aligned 300 ms RMS over all 88 notes x velocities, then
plot per-note deviation from the smooth trend and the note-to-note jumps."""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from repack import parse_toc, wav_layout, dec24, onset_frame
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

BLUE, TEAL, AMBER, CORAL, GRAY, INK = "#2563eb", "#0d9488", "#d97706", "#dc2626", "#64748b", "#1f2933"
plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.size": 11, "font.family": "DejaVu Sans",
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 12, "axes.titleweight": "bold", "grid.color": "#e2e8f0"})
NOTES = r"E:\IK Multimedia\Pianoverse\Samples\Pianoverse\Concert Grand YF3\Notes"


def note_key(n):
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    i = 2 if (len(n) > 1 and n[1] == "#") else 1
    return base[n[0]] + (1 if i == 2 else 0) + 12 * (int(n[i:]) + 1)


def measure(src):
    rows = []
    for n in range(1, 13):
        pak = os.path.join(NOTES, f"Close {n}", f"Close {n}" + src)
        if not os.path.exists(pak):
            continue
        ver, cnt, ents = parse_toc(pak)
        with open(pak, "rb") as f:
            for pth, off, sz in ents:
                b = pth.replace("/", "\\").split("\\")[-1]; note = b.split("_")[0]
                mv = re.search(r"_v(\d+)_", b); vel = int(mv.group(1)) if mv else 0
                f.seek(off); head = f.read(min(sz, 200000)); lay = wav_layout(head)
                if lay is None:
                    continue
                data = head[lay["data_payload"]:]; data = data[:len(data) // 6 * 6]
                if len(data) < 6 * 4800:
                    continue
                v = dec24(data).reshape(-1, lay["ch"]).astype(np.float64); sr = lay["sr"]
                on = max(onset_frame(np.abs(v).max(axis=1), sr), 0)
                w = v[on:on + int(sr * 0.3)]
                if len(w) < int(sr * 0.1):
                    continue
                rows.append((note, vel, 20 * np.log10(max(np.sqrt(np.mean(w ** 2)), 1) / 8388608.0)))
    return pd.DataFrame(rows, columns=["Note", "Vel", "RmsDb"])


def resid(df):
    df = df.copy(); df["pk"] = df["Note"].map(note_key)
    g = df.groupby(["Note", "pk", "Vel"], as_index=False)["RmsDb"].mean()
    rr, adj = [], []
    for vel, sub in g.groupby("Vel"):
        sub = sub.sort_values("pk"); r = sub["RmsDb"].values
        tr = pd.Series(r).rolling(5, center=True, min_periods=1).median().values
        for nt, pk, res in zip(sub["Note"], sub["pk"], r - tr):
            rr.append((nt, pk, res))
        adj.extend(np.abs(np.diff(r)))
    R = pd.DataFrame(rr, columns=["Note", "pk", "resid"])
    per = R.groupby(["Note", "pk"])["resid"].mean().reset_index().sort_values("pk")
    return R, per, np.array(adj)


before = measure(".pak.orig"); after = measure(".pak")
Rb, perb, adjb = resid(before); Ra, pera, adja = resid(after)

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.2, 4.4))
ax1.axhline(0, color=GRAY, lw=0.8)
ax1.plot(perb["pk"], perb["resid"], color=GRAY, lw=1.0, alpha=0.85, label=f"before    σ {Rb['resid'].std():.2f} dB")
ax1.plot(pera["pk"], pera["resid"], color=TEAL, lw=1.5, label=f"after gain  σ {Ra['resid'].std():.2f} dB")
at = {n: note_key(n) for n in ["A-1", "A1", "A3", "A5"]}
ax1.set_xticks(list(at.values())); ax1.set_xticklabels(list(at.keys()))
ax1.set_xlabel("pitch (low -> high)"); ax1.set_ylabel("deviation from trend (dB)")
ax1.set_title("Per-note loudness deviation"); ax1.grid(axis="y"); ax1.legend(frameon=False, fontsize=9.5)

bins = np.linspace(0, 8, 33)
ax2.hist(adjb, bins=bins, color=GRAY, alpha=0.55, label=f"before    median {np.median(adjb):.2f} dB")
ax2.hist(adja, bins=bins, color=TEAL, alpha=0.8, label=f"after gain  median {np.median(adja):.2f} dB")
ax2.set_xlabel("|adjacent-semitone ΔRMS| (dB)"); ax2.set_ylabel("count")
ax2.set_title("Note-to-note jumps"); ax2.grid(axis="y"); ax2.legend(frameon=False, fontsize=9.5)

fig.suptitle("Keyboard-wide loudness variation — before vs after the per-note gain  (YF3 Close, all 88 notes)",
             fontsize=12.5, fontweight="bold", y=1.02)
fig.tight_layout()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loudness_before_after.png")
fig.savefig(out, bbox_inches="tight"); plt.close(fig)
print("wrote", out, "| before sigma", round(Rb["resid"].std(), 2), "after sigma", round(Ra["resid"].std(), 2),
      "| adj median", round(np.median(adjb), 2), "->", round(np.median(adja), 2))
