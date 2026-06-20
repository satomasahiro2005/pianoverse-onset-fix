#!/usr/bin/env python3
"""Generate the research figures (PNG) for the Pianoverse onset study.

Data sources (produced by the PowerShell tools):
  ../onset.csv                  onset sweep over YF3 Close, 88 keys x 14 vel (rr1)
  ../onset_close1_before.csv    onset(-20dB) per sample, Close 1, original pak
  ../onset_close1_after.csv     onset(-20dB) per sample, Close 1, head-trimmed pak

Figure labels are English on purpose (the embedded matplotlib font has no CJK
glyphs); the prose explanation lives in the Japanese README.
"""
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BLUE, TEAL, AMBER, CORAL, GRAY, INK = "#2563eb", "#0d9488", "#d97706", "#dc2626", "#64748b", "#1f2933"

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150,
    "font.size": 11, "font.family": "DejaVu Sans",
    "axes.edgecolor": "#94a3b8", "axes.linewidth": 0.8,
    "axes.titlesize": 13, "axes.titleweight": "bold", "axes.titlepad": 12,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.spines.top": False, "axes.spines.right": False,
    "grid.color": "#e2e8f0", "grid.linewidth": 0.8,
})

# ---- real measured 0.5 ms attack envelopes (dBFS), t = 0..16 ms (33 pts) ----
T = np.arange(33) * 0.5
ENV = {
    "A3 v127 (mid, ff)":  [-38.3,-47.8,-45.8,-40.4,-39.7,-45.2,-39.5,-38.5,-39.2,-38.4,-39.3,-36.5,-42.5,-38.3,-27.5,-24.4,-26.8,-15.4,-8.3,-15.7,-12.2,-14,-15.2,-8.8,-10.3,-8.8,-10.8,-8.2,-9.5,-6.9,-7.2,-9.7,-5.9],
    "A6 v127 (treble, ff)": [-45.3,-46.9,-51.8,-45.5,-46,-42.4,-39.9,-39.5,-40.6,-41.2,-42.9,-48.4,-48.1,-44.6,-36,-35.9,-33.1,-34,-25.9,-13.8,-15.5,-14.5,-12.1,-14.3,-11.4,-9.8,-11.1,-13.5,-14.6,-10,-13.9,-13.1,-12.5],
    "A3 v90 (mid, mf)":   [-56.9,-56.6,-57.8,-59,-58.3,-59.3,-61.2,-59.5,-54.5,-57.6,-62.2,-62.5,-52.7,-48.4,-48.3,-37.7,-41.7,-25,-17.2,-23.7,-23.9,-24.2,-25.4,-17.9,-19.8,-17.6,-18.4,-16,-16.8,-15,-15,-20.1,-14.1],
}
ENV_COLOR = {"A3 v127 (mid, ff)": BLUE, "A6 v127 (treble, ff)": TEAL, "A3 v90 (mid, mf)": AMBER}


def note_key(n):
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    letter = n[0]
    i = 1
    sharp = 0
    if len(n) > 1 and n[1] == "#":
        sharp = 1
        i = 2
    octave = int(n[i:])
    return base[letter] + sharp + 12 * (octave + 1)


def fig_structure():
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.axvspan(0, 7, color=AMBER, alpha=0.10, zorder=0)
    for label, env in ENV.items():
        ax.plot(T, env, color=ENV_COLOR[label], lw=2.2, label=label, zorder=3)
    # anchor illustration for A3 v127: peak and peak-20 dB
    a3 = np.array(ENV["A3 v127 (mid, ff)"])
    peak = a3.max()
    ax.axhline(peak - 20, color=BLUE, ls=(0, (4, 3)), lw=1.1, alpha=0.7, zorder=2)
    ax.text(15.8, peak - 20 + 0.6, "A3 peak − 20 dB  (detection anchor)",
            ha="right", va="bottom", fontsize=9, color=BLUE)
    ax.axvline(8, color=GRAY, ls=(0, (2, 2)), lw=1.1, zorder=2)
    ax.annotate("tonal onset ≈ 8 ms\n(hammer/string tone)", xy=(8, -4),
                xytext=(10.2, -3.5), fontsize=9.5, color=INK, va="top",
                arrowprops=dict(arrowstyle="->", color=GRAY, lw=1.0))
    ax.annotate("~7 ms touch / mechanical\nnoise floor (~ −40 dB)", xy=(3.2, -40),
                xytext=(0.4, -16), fontsize=9.5, color="#92600a", va="top",
                arrowprops=dict(arrowstyle="->", color=AMBER, lw=1.1))
    ax.set_xlim(0, 16)
    ax.set_ylim(-65, 0)
    ax.set_xlabel("time from sample start (ms)")
    ax.set_ylabel("level (dBFS)")
    ax.set_title("Pianoverse YF3 Close — attack onset structure")
    ax.set_xticks(range(0, 17, 2))
    ax.grid(axis="y")
    ax.legend(frameon=False, fontsize=9.5, loc="lower right")
    fig.tight_layout()
    out = os.path.join(HERE, "onset_structure.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def fig_dependence():
    df = pd.read_csv(os.path.join(ROOT, "onset.csv"))
    df["onset"] = pd.to_numeric(df["T_m20ms"], errors="coerce")
    df = df.dropna(subset=["onset"])
    fig, (axv, axp) = plt.subplots(1, 2, figsize=(10.2, 4.3))

    # left: onset vs velocity
    vels = sorted(df["Vel"].unique())
    data = [df.loc[df["Vel"] == v, "onset"].values for v in vels]
    bp = axv.boxplot(data, positions=range(len(vels)), widths=0.6, patch_artist=True,
                     showfliers=False, medianprops=dict(color=INK, lw=1.3))
    for box in bp["boxes"]:
        box.set(facecolor=BLUE, alpha=0.25, edgecolor=BLUE)
    for whisk in bp["whiskers"]:
        whisk.set(color=BLUE, alpha=0.7)
    for cap in bp["caps"]:
        cap.set(color=BLUE, alpha=0.7)
    means = [d.mean() for d in data]
    axv.plot(range(len(vels)), means, "-o", color=CORAL, ms=4, lw=1.6, label="mean", zorder=5)
    axv.set_xticks(range(len(vels)))
    axv.set_xticklabels([str(v) for v in vels], rotation=45, fontsize=8)
    axv.set_xlabel("MIDI velocity")
    axv.set_ylabel("onset (−20 dB rel. peak) [ms]")
    axv.set_title("Onset vs. velocity")
    axv.grid(axis="y")
    axv.legend(frameon=False, fontsize=9)

    # right: onset vs pitch
    df = df.copy()
    df["pk"] = df["Note"].map(note_key)
    sc = axp.scatter(df["pk"], df["onset"], c=df["Vel"], cmap="viridis", s=14, alpha=0.75)
    axp.set_xlabel("pitch (low → high)")
    axp.set_ylabel("onset (−20 dB rel. peak) [ms]")
    axp.set_title("Onset vs. pitch")
    axp.grid(axis="y")
    # mark octave A's
    aticks = {n: note_key(n) for n in ["A-1", "A1", "A3", "A5"]}
    axp.set_xticks(list(aticks.values()))
    axp.set_xticklabels(list(aticks.keys()), fontsize=8)
    cb = fig.colorbar(sc, ax=axp, pad=0.02)
    cb.set_label("velocity", fontsize=9)

    fig.suptitle("Why it sounds uneven: the baked-in onset varies by velocity and pitch",
                 fontsize=12, fontweight="bold", y=1.02)
    fig.tight_layout()
    out = os.path.join(HERE, "onset_dependence.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def fig_before_after():
    bp = os.path.join(ROOT, "onset_close1_before.csv")
    ap = os.path.join(ROOT, "onset_close1_after.csv")
    if not (os.path.exists(bp) and os.path.exists(ap)):
        print("skip before/after (csv not found yet)")
        return
    b = pd.read_csv(bp); a = pd.read_csv(ap)
    b["onb"] = pd.to_numeric(b["T_m20ms"], errors="coerce")
    a["ona"] = pd.to_numeric(a["T_m20ms"], errors="coerce")
    m = pd.merge(b[["Name", "onb"]], a[["Name", "ona"]], on="Name").dropna()
    onb, ona = m["onb"].values, m["ona"].values
    bulk = ona[ona < 5]                      # aligned notes (rest hit the soft-note cap)

    fig, (axh, axs) = plt.subplots(1, 2, figsize=(10.2, 4.3))
    bins = np.linspace(0, max(onb.max(), 12), 40)
    axh.hist(onb, bins=bins, color=GRAY, alpha=0.55, label=f"before  (mean {onb.mean():.1f} ± {onb.std():.1f} ms)")
    axh.hist(ona, bins=bins, color=TEAL, alpha=0.75, label=f"after bulk  (mean {bulk.mean():.2f} ± {bulk.std():.2f} ms, n={len(bulk)})")
    axh.axvline(onb.mean(), color=GRAY, ls="--", lw=1.2)
    axh.axvline(ona.mean(), color=TEAL, ls="--", lw=1.2)
    axh.set_xlabel("onset (−20 dB rel. peak) [ms]")
    axh.set_ylabel("number of samples")
    axh.set_title("Onset distribution: before vs after trim")
    axh.legend(frameon=False, fontsize=9)
    axh.grid(axis="y")

    # paired scatter
    axs.scatter(onb, ona, s=16, color=BLUE, alpha=0.6)
    lim = max(onb.max(), ona.max()) * 1.05
    axs.plot([0, lim], [0, lim], color=GRAY, ls=":", lw=1, label="no change (y=x)")
    axs.axhline(ona.mean(), color=TEAL, ls="--", lw=1.1, label=f"after mean {ona.mean():.1f} ms")
    axs.set_xlim(0, lim); axs.set_ylim(0, max(ona.max() * 1.4, 4))
    axs.set_xlabel("onset BEFORE [ms]")
    axs.set_ylabel("onset AFTER [ms]")
    axs.set_title("Per-sample: every onset pulled to the target")
    axs.legend(frameon=False, fontsize=9)
    axs.grid(True)

    fig.suptitle(f"Head-trim — delay {onb.mean():.1f}→{ona.mean():.1f} ms; aligned bulk "
                 f"σ {bulk.std():.2f} ms ({len(bulk)}/{len(ona)}), {len(ona)-len(bulk)} soft notes preserved",
                 fontsize=12, fontweight="bold", y=1.02)
    fig.tight_layout()
    out = os.path.join(HERE, "onset_before_after.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


def fig_pak_format():
    fig, ax = plt.subplots(figsize=(9.2, 5.6))
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

    def block(x, y, w, h, fc, ec, title, rows, off_labels=None):
        ax.add_patch(Rectangle((x, y), w, h, facecolor="white", edgecolor=ec, lw=1.4, zorder=2))
        ax.add_patch(Rectangle((x, y + h - 7), w, 7, facecolor=ec, edgecolor=ec, zorder=3))
        ax.text(x + 1.5, y + h - 3.5, title, color="white", fontsize=10.5, fontweight="bold", va="center", zorder=4)
        n = len(rows)
        rh = (h - 7) / n
        for i, (a, b) in enumerate(rows):
            ry = y + h - 7 - (i + 1) * rh
            if i:
                ax.plot([x, x + w], [ry + rh, ry + rh], color="#e2e8f0", lw=0.7, zorder=3)
            ax.text(x + 2, ry + rh / 2, a, fontsize=9.5, va="center", family="DejaVu Sans Mono", color=INK, zorder=4)
            ax.text(x + w - 2, ry + rh / 2, b, fontsize=9, va="center", ha="right", color=GRAY, zorder=4)
            if off_labels and i < len(off_labels) and off_labels[i] is not None:
                ax.text(x - 1.5, ry + rh / 2, off_labels[i], fontsize=8, va="center", ha="right", color="#94a3b8", zorder=4)

    block(10, 78, 80, 20, "white", "#1e3a5f", "HEADER",
          [('"IKMPAK"', "6-byte magic"),
           ("uint32  version = 2", "container version"),
           ("uint32  entryCount = N", "number of samples")],
          off_labels=["0", "6", "10"])

    block(10, 44, 80, 30, "white", BLUE, "TABLE OF CONTENTS  —  N entries, file order",
          [("char  path[]  \\0", "NUL-terminated relative path"),
           ("uint64  dataOffset", "absolute byte offset of this WAV"),
           ("uint64  dataSize", "byte length of this WAV")])
    ax.plot([90.5, 92, 92, 90.5], [66, 66, 45.5, 45.5], color=BLUE, lw=1.3)
    ax.text(93, 55.75, "× N", color=BLUE, fontsize=10, va="center", ha="left")

    block(10, 12, 80, 28, "white", TEAL, "PAYLOAD  —  standard RIFF/WAVE, concatenated",
          [("WAV 0 | WAV 1 | WAV 2 | … | WAV N-1", "contiguous, in TOC order"),
           ("RIFF | fmt | [bext] | [junk] | data", "PCM 24-bit / 48 kHz / stereo")])

    ax.text(50, 6.5, "fileLength  ==  header + TOC + Σ(WAV sizes)      •   no gaps   •   no padding   •   no checksum / footer",
            ha="center", fontsize=9, color="#0f766e")
    ax.text(50, 99, "IKMPAK (.pak) container layout", ha="center", fontsize=14, fontweight="bold", color="#1e3a5f")

    fig.tight_layout()
    out = os.path.join(HERE, "pak_format.png")
    fig.savefig(out, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", out)


def _onset_ms(sig, t, frac=0.12, win=12):
    pk = np.abs(sig).max()
    env = np.array([np.abs(sig[i:i + win]).max() for i in range(len(sig))])
    idx = int(np.argmax(env >= pk * frac))
    return t[idx]


def fig_waveform():
    """Wide linear-amplitude waveform: the onset delay is visible to the eye."""
    csv = os.path.join(ROOT, "waveform_a3.csv")
    if not os.path.exists(csv):
        print("skip waveform (csv not found)")
        return
    df = pd.read_csv(csv)
    t, o, r = df["t_ms"].values, df["orig"].values, df["trim"].values
    o_on, r_on = _onset_ms(o, t), _onset_ms(r, t)
    yl = 0.62

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.6, 5.6), sharex=True, sharey=True)
    for ax in (ax1, ax2):
        ax.axhline(0, color="#cbd5e1", lw=0.7)
        ax.set_ylim(-yl, yl)
        ax.set_xlim(0, 50)
        ax.set_ylabel("amplitude")
        ax.grid(axis="x")

    ax1.plot(t, o, color=GRAY, lw=0.6)
    ax1.axvspan(0, o_on, color=CORAL, alpha=0.13, zorder=0)
    ax1.annotate("", xy=(o_on, 0.46), xytext=(0, 0.46),
                 arrowprops=dict(arrowstyle="<->", color=CORAL, lw=1.7))
    ax1.text(o_on / 2, 0.5, f"onset delay ≈ {o_on:.1f} ms", ha="center", va="bottom",
             color="#b91c1c", fontsize=10.5, fontweight="bold")
    ax1.set_title("original sample — the note stays quiet for ~8 ms after note-on", loc="left")

    ax2.plot(t, r, color=TEAL, lw=0.6)
    ax2.axvspan(0, r_on, color=TEAL, alpha=0.16, zorder=0)
    ax2.annotate("", xy=(r_on, 0.46), xytext=(0, 0.46),
                 arrowprops=dict(arrowstyle="<->", color=TEAL, lw=1.7))
    ax2.text(r_on + 0.6, 0.5, f"onset ≈ {r_on:.1f} ms", ha="left", va="bottom",
             color="#0f766e", fontsize=10.5, fontweight="bold")
    ax2.set_title("head-trimmed sample — the attack now starts almost immediately", loc="left")
    ax2.set_xlabel("time from note-on (ms)")

    fig.suptitle("Onset delay is in the audio data  (YF3 Close · A3 · v127)",
                 fontsize=13, fontweight="bold", y=0.99)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    out = os.path.join(HERE, "onset_waveform.png")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print("wrote", out)


if __name__ == "__main__":
    fig_waveform()
    fig_structure()
    fig_dependence()
    fig_before_after()
    fig_pak_format()
