#!/usr/bin/env python3
"""Verify the full Close 1 pipeline (trim+cap+fade+gain): onset and loudness."""
import os, numpy as np, pandas as pd
R = os.path.dirname(os.path.abspath(__file__))


def note_key(n):
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    i = 2 if (len(n) > 1 and n[1] == "#") else 1
    return base[n[0]] + (1 if i == 2 else 0) + 12 * (int(n[i:]) + 1)


def num(s):
    return pd.to_numeric(s, errors="coerce")


# ---------- onset ----------
b = pd.read_csv(os.path.join(R, "onset_close1_before.csv"))
a = pd.read_csv(os.path.join(R, "onset_close1_after.csv"))
b["o"] = num(b["T_m20ms"]); a["o"] = num(a["T_m20ms"])
m = b[["Name", "o"]].merge(a[["Name", "o"]], on="Name", suffixes=("_b", "_a")).dropna()
print("=== ONSET (Close 1, %d samples) ===" % len(m))
print("before  mean %.2f  sd %.2f  max %.2f ms" % (m.o_b.mean(), m.o_b.std(), m.o_b.max()))
print("after   mean %.2f  sd %.2f  max %.2f ms  (max-trim cap keeps soft notes natural)"
      % (m.o_a.mean(), m.o_a.std(), m.o_a.max()))

# ---------- loudness ----------
allc = pd.read_csv(os.path.join(R, "loudness_close_all.csv"))
aft = pd.read_csv(os.path.join(R, "loudness_close1_after.csv"))
gains = pd.read_csv(os.path.join(R, "note_gains.csv")).set_index("Note")["GainDb"]
allc["pk"] = allc["Note"].map(note_key)

# per-velocity smooth trend over the whole keyboard (unchanged neighbours define it)
def add_resid(df):
    df = df.copy(); df["pk"] = df["Note"].map(note_key); out = []
    for vel, sub in df.groupby("Vel"):
        sub = sub.sort_values("pk")
        # trend from the ORIGINAL full keyboard at these pitches
        ref = allc[allc.Vel == vel].groupby("pk").RmsDb.mean().sort_index()
        trend = ref.rolling(5, center=True, min_periods=1).median()
        sub["resid"] = sub.apply(lambda r: r.RmsDb - trend.reindex([r.pk]).interpolate().iloc[0]
                                 if r.pk in trend.index else np.nan, axis=1)
        out.append(sub)
    return pd.concat(out)

isA = allc.Note.str.match(r"A(-1|\d)$")
bef_resid = add_resid(allc[isA]).groupby("Note")["resid"].mean()
aft_resid = add_resid(aft).groupby("Note")["resid"].mean()
bef_rms = allc[isA].groupby("Note").RmsDb.mean()
aft_rms = aft.groupby("Note").RmsDb.mean()

print("\n=== LOUDNESS — A notes (Close 1) ===")
print("%-5s %8s %8s %7s %8s %8s" % ("note", "gainDb", "dRMS", "->ok?", "resid_b", "resid_a"))
for n in sorted(bef_rms.index, key=note_key):
    d = aft_rms[n] - bef_rms[n]; g = gains.get(n, 0)
    ok = "yes" if abs(d - g) < 0.6 else "OFF"
    print("%-5s %8.2f %8.2f %7s %8.2f %8.2f" % (n, g, d, ok, bef_resid[n], aft_resid.get(n, np.nan)))
print("\nA-note systematic deviation  std:  before %.2f dB  ->  after %.2f dB"
      % (bef_resid.std(), aft_resid.std()))
print("mean |deviation|:                  before %.2f dB  ->  after %.2f dB"
      % (bef_resid.abs().mean(), aft_resid.abs().mean()))
