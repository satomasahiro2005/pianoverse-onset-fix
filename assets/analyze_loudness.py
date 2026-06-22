#!/usr/bin/env python3
"""Characterise volume variation across the YF3 Close keyboard.

Reads ../loudness_close_all.csv (Mic,Note,Vel,RR,PeakDb,RmsDb).
Separates the *natural* loudness-vs-pitch trend from per-note bumps, and tests
whether those bumps are consistent across velocities (=> fixable with one gain
per note, analogous to the per-sample head-trim).
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BLUE, TEAL, AMBER, CORAL, GRAY, INK = "#2563eb", "#0d9488", "#d97706", "#dc2626", "#64748b", "#1f2933"
plt.rcParams.update({"figure.dpi": 150, "savefig.dpi": 150, "font.size": 11,
                     "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titlesize": 12, "axes.titleweight": "bold",
                     "grid.color": "#e2e8f0"})


def note_key(n):
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    i = 2 if (len(n) > 1 and n[1] == "#") else 1
    return base[n[0]] + (1 if i == 2 else 0) + 12 * (int(n[i:]) + 1)


def main():
    df = pd.read_csv(os.path.join(ROOT, "loudness_close_all.csv"))
    df["pk"] = df["Note"].map(note_key)
    # average round-robins -> one loudness per (note, vel)
    g = df.groupby(["Note", "pk", "Vel"], as_index=False)["RmsDb"].mean()

    resid_rows = []
    for vel, sub in g.groupby("Vel"):
        sub = sub.sort_values("pk")
        rms = sub["RmsDb"].values
        # smooth natural trend = rolling median over 5 semitones
        trend = pd.Series(rms).rolling(5, center=True, min_periods=1).median().values
        for note, pk, r, tr in zip(sub["Note"], sub["pk"], rms, trend):
            resid_rows.append({"Note": note, "pk": pk, "Vel": vel, "resid": r - tr})
    R = pd.DataFrame(resid_rows)

    # adjacent-semitone jumps at each velocity
    adj = []
    for vel, sub in g.groupby("Vel"):
        rms = sub.sort_values("pk")["RmsDb"].values
        adj.extend(np.abs(np.diff(rms)))
    adj = np.array(adj)

    # per-note mean residual (systematic bump) + consistency across velocities
    pernote = R.groupby(["Note", "pk"])["resid"].agg(["mean", "std"]).reset_index().sort_values("pk")
    sys_std = pernote["mean"].std()
    resid_std = R["resid"].std()
    explained = 1 - (R.merge(pernote[["Note", "mean"]], on="Note")
                     .eval("resid - mean").std() ** 2) / resid_std ** 2

    print("=== volume variation across YF3 Close keyboard ===")
    print(f"samples: {len(df)}   notes: {g['Note'].nunique()}   velocities: {g['Vel'].nunique()}")
    print(f"adjacent-semitone |dRMS|: median {np.median(adj):.2f} dB  90th pct {np.percentile(adj,90):.2f}  max {adj.max():.2f}")
    print(f"residual (note - local trend) std: {resid_std:.2f} dB")
    print(f"systematic per-note bump std: {sys_std:.2f} dB   (variance explained by a per-note gain: {explained*100:.0f}%)")
    print("\nloudest sticking-out notes (mean residual):")
    print(pernote.sort_values("mean", ascending=False).head(6)[["Note", "mean", "std"]].round(2).to_string(index=False))
    print("\nquietest sticking-out notes:")
    print(pernote.sort_values("mean").head(6)[["Note", "mean", "std"]].round(2).to_string(index=False))

    # ---- per-note gain table: correct the systematic bump, headroom-safe ----
    peak = df.groupby("Note")["PeakDb"].max()
    gtab = []
    for _, row in pernote.iterrows():
        note = row["Note"]
        desired = float(np.clip(-row["mean"], -6, 6))   # pull toward the trend
        if desired > 0:                                  # boost: clamp to headroom (keep 3 dB margin so peaky notes' attacks don't overshoot)
            desired = min(desired, -float(peak[note]) - 3.0)
        gtab.append({"Note": note, "GainDb": round(desired, 2)})
    pd.DataFrame(gtab).to_csv(os.path.join(ROOT, "note_gains.csv"), index=False)
    gv = [g["GainDb"] for g in gtab]
    print(f"\nwrote note_gains.csv ({len(gtab)} notes), gain {min(gv):.2f}..{max(gv):.2f} dB, "
          f"mean|g| {np.mean(np.abs(gv)):.2f} dB")

    # ---- figure ----
    fig, (axc, axb) = plt.subplots(1, 2, figsize=(10.4, 4.3))
    velshow = sorted(g["Vel"].unique())[len(g["Vel"].unique()) // 2]  # a mid velocity
    sub = g[g["Vel"] == velshow].sort_values("pk")
    trend = pd.Series(sub["RmsDb"].values).rolling(5, center=True, min_periods=1).median().values
    axc.plot(sub["pk"], sub["RmsDb"], "-o", color=BLUE, ms=3, lw=1, label=f"per-note RMS (v{velshow})")
    axc.plot(sub["pk"], trend, color=CORAL, lw=2, label="smooth trend (natural)")
    aticks = {n: note_key(n) for n in ["A-1", "A1", "A3", "A5"]}
    axc.set_xticks(list(aticks.values())); axc.set_xticklabels(list(aticks.keys()))
    axc.set_xlabel("pitch (low -> high)"); axc.set_ylabel("RMS (dBFS)")
    axc.set_title("Loudness vs pitch: note-to-note bumps")
    axc.grid(axis="y"); axc.legend(frameon=False, fontsize=9)

    axb.bar(pernote["pk"], pernote["mean"], width=0.9,
            color=[CORAL if v > 0 else BLUE for v in pernote["mean"]])
    axb.axhline(0, color=GRAY, lw=0.8)
    axb.set_xticks(list(aticks.values())); axb.set_xticklabels(list(aticks.keys()))
    axb.set_xlabel("pitch (low -> high)"); axb.set_ylabel("mean deviation from trend (dB)")
    axb.set_title(f"Per-note bump (consistent across vel: {explained*100:.0f}% explained)")
    axb.grid(axis="y")

    fig.suptitle(f"Volume variation — note-to-note σ {resid_std:.2f} dB, "
                 f"systematic per-note σ {sys_std:.2f} dB  (YF3 Close)",
                 fontsize=12, fontweight="bold", y=1.02)
    fig.tight_layout()
    out = os.path.join(HERE, "loudness_variation.png")
    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
    print("\nwrote", out)


if __name__ == "__main__":
    main()
