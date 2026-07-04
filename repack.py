#!/usr/bin/env python3
"""IKMPAK repacker (numpy): head-trim + max-trim cap + fade-in + per-note gain.

Supersedes repack.ps1 for the full pipeline (PowerShell is too slow to apply a
whole-sample gain). Lossless container rebuild; only the head is trimmed and an
optional constant gain / short fade-in are applied to the 24-bit PCM.

Works on any IKMPAK container whose payload is 24-bit PCM WAV; anything else is
refused rather than silently corrupted. Gains are keyed on the note name parsed
from each TOC path (basename up to the first '_', e.g. "A3_v100_rr1..." -> A3).

Usage:
  python repack.py IN.pak OUT.pak [--preroll 1.5] [--maxtrim 20] [--fade 0.4]
                   [--gains note_gains.csv] [--anchor -20]
"""
import os, sys, struct, argparse, csv
import numpy as np

HDR = 14  # "IKMPAK"(6) + u32 version + u32 count


def parse_toc(path):
    with open(path, "rb") as f:
        magic = f.read(6)
        if magic != b"IKMPAK":
            raise ValueError("not IKMPAK: %s" % path)
        ver, cnt = struct.unpack("<II", f.read(8))
        buf = f.read(8 * 1024 * 1024)  # TOC is tiny (KBs); 8MB is plenty
    p, entries = 0, []
    for _ in range(cnt):
        z = buf.index(0, p)
        pth = buf[p:z].decode("ascii"); p = z + 1
        off, sz = struct.unpack_from("<QQ", buf, p); p += 16
        entries.append((pth, off, sz))
    return ver, cnt, entries


def wav_layout(b):
    if b[:4] != b"RIFF":
        return None
    q, fmt = 12, None
    while q + 8 <= len(b):
        cid = b[q:q + 4]; csz = struct.unpack_from("<I", b, q + 4)[0]
        if cid == b"fmt ":
            ch = struct.unpack_from("<H", b, q + 10)[0]
            sr = struct.unpack_from("<I", b, q + 12)[0]
            bits = struct.unpack_from("<H", b, q + 22)[0]
            fmt = (ch, sr, bits)
        if cid == b"data":
            return dict(data_hdr=q, data_payload=q + 8, data_size=csz,
                        ch=fmt[0], sr=fmt[1], bits=fmt[2])
        q = q + 8 + csz + (csz & 1)
    return None


def dec24(raw):
    a = np.frombuffer(raw, dtype=np.uint8).astype(np.int32)
    v = a[0::3] | (a[1::3] << 8) | (a[2::3] << 16)
    return np.where(v & 0x800000, v - 0x1000000, v)


def enc24(v):
    v = np.clip(np.rint(v), -8388608, 8388607).astype(np.int32)
    u = v.astype(np.uint32) & 0xFFFFFF
    out = np.empty((u.size, 3), dtype=np.uint8)
    out[:, 0] = u & 0xFF; out[:, 1] = (u >> 8) & 0xFF; out[:, 2] = (u >> 16) & 0xFF
    return out.tobytes()


def onset_frame(maxch, sr, anchor_db=-20.0, scan_ms=400, step=12):
    n = min(len(maxch), int(sr * scan_ms / 1000))
    nb = n // step
    if nb < 4:
        return -1
    env = maxch[:nb * step].reshape(nb, step).max(axis=1)
    peak = env.max()
    if peak < 64:
        return -1
    thr = peak * (10 ** (anchor_db / 20))
    hits = np.nonzero(env >= thr)[0]
    return int(hits[0] * step) if len(hits) else -1


def load_gains(path):
    g = {}
    if path and os.path.exists(path):
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                g[row["Note"]] = float(row["GainDb"])
    return g


def repack(in_pak, out_pak, preroll_ms=1.5, max_trim_ms=20.0, fade_ms=0.4,
           gains=None, anchor_db=-20.0, report=None):
    gains = gains or {}
    ver, cnt, entries = parse_toc(in_pak)
    toc = bytearray(b"IKMPAK") + struct.pack("<II", ver, cnt)
    pos = []
    for pth, _, _ in entries:
        toc += pth.encode("ascii") + b"\x00"
        pos.append(len(toc)); toc += struct.pack("<QQ", 0, 0)
    meta = []
    with open(in_pak, "rb") as fin, open(out_pak, "wb") as fout:
        fout.write(toc)
        cur = len(toc)
        for pth, off, sz in entries:
            fin.seek(off); b = fin.read(sz)
            lay = wav_layout(b)
            if lay is None:
                fout.write(b); meta.append((cur, sz)); cur += sz; continue
            if lay["bits"] != 24:
                raise ValueError("%s is %d-bit; only 24-bit PCM is supported "
                                 "(refusing to write a corrupted pak)" % (pth, lay["bits"]))
            sr, ch = lay["sr"], lay["ch"]
            data = b[lay["data_payload"]:lay["data_payload"] + lay["data_size"]]
            v = dec24(data).astype(np.float64).reshape(-1, ch)
            maxch = np.abs(v).max(axis=1)
            on = onset_frame(maxch, sr, anchor_db)
            pre = int(sr * preroll_ms / 1000); cap = int(sr * max_trim_ms / 1000)
            trim = 0 if on < 0 else max(0, min(on - pre, cap))
            v = v[trim:]
            note = pth.replace("\\", "/").split("/")[-1].split("_")[0]
            gdb = gains.get(note, 0.0)
            if gdb:
                v *= 10 ** (gdb / 20)
            fn = int(sr * fade_ms / 1000)
            if fn > 1 and len(v) > fn:
                v[:fn] *= np.linspace(0.0, 1.0, fn).reshape(-1, 1)
            nd = enc24(v.reshape(-1)); nsize = len(nd)
            hdr = bytearray(b[:lay["data_payload"]])
            struct.pack_into("<I", hdr, 4, lay["data_payload"] + nsize - 8)
            struct.pack_into("<I", hdr, lay["data_hdr"] + 4, nsize)
            fout.write(hdr); fout.write(nd)
            meta.append((cur, len(hdr) + nsize)); cur += len(hdr) + nsize
            if report is not None:
                report.append(dict(Name=pth.split("/")[-1],
                                   TrimMs=round(trim / sr * 1000, 3), GainDb=gdb))
        for i, (o, s) in enumerate(meta):
            fout.seek(pos[i]); fout.write(struct.pack("<QQ", o, s))
    return cnt


def verify(out_pak):
    ver, cnt, entries = parse_toc(out_pak)
    flen = os.path.getsize(out_pak)
    es = sorted(entries, key=lambda e: e[1])
    gaps = sum(1 for i in range(len(es) - 1) if es[i][1] + es[i][2] != es[i + 1][1])
    last = es[-1]
    ok_hdr = 0
    with open(out_pak, "rb") as f:
        for pth, off, sz in entries[:: max(1, cnt // 8)]:
            f.seek(off); b = f.read(min(sz, 200))
            lay = wav_layout(b + b"\x00" * 0) if sz <= 200 else wav_layout(_read(f, off, sz))
            riff = struct.unpack_from("<I", b, 4)[0]
            if riff == sz - 8:
                ok_hdr += 1
    return dict(entries=cnt, fileLen=flen, contiguous=(last[1] + last[2] == flen and gaps == 0),
               headerOK=ok_hdr)


def _read(f, off, sz):
    f.seek(off); return f.read(sz)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("in_pak"); ap.add_argument("out_pak")
    ap.add_argument("--preroll", type=float, default=1.5)
    ap.add_argument("--maxtrim", type=float, default=20.0)
    ap.add_argument("--fade", type=float, default=0.4)
    ap.add_argument("--gains", default=None)
    ap.add_argument("--anchor", type=float, default=-20.0)
    a = ap.parse_args()
    rep = []
    n = repack(a.in_pak, a.out_pak, a.preroll, a.maxtrim, a.fade,
               load_gains(a.gains), a.anchor, report=rep)
    tr = np.array([r["TrimMs"] for r in rep])
    gn = np.array([r["GainDb"] for r in rep])
    print(f"repacked {n} entries -> {a.out_pak}")
    print(f"trim ms: mean {tr.mean():.2f} max {tr.max():.2f}  (capped at {a.maxtrim})")
    print(f"gain dB: applied to {int((gn!=0).sum())} samples, range {gn.min():.2f}..{gn.max():.2f}")
    print("verify:", verify(a.out_pak))
