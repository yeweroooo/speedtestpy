"""Command-line interface untuk speedtestpy."""

import argparse
import json
import sys
import time

from .core import SpeedTest


def build_parser():
    ap = argparse.ArgumentParser(
        description="Speed test akurat & cepat (ala Ookla & Cloudflare).")
    ap.add_argument("--engine", choices=["cloudflare", "ookla"],
                    default="cloudflare", help="engine pengujian")
    ap.add_argument("--threads-dl", type=int, default=8,
                    help="koneksi paralel download")
    ap.add_argument("--threads-ul", type=int, default=6,
                    help="koneksi paralel upload")
    ap.add_argument("--duration", type=float, default=8.0,
                    help="durasi tiap tahap download/upload (detik)")
    ap.add_argument("--warmup", type=float, default=None,
                    help="warm-up download (detik); default otomatis 8x ping")
    ap.add_argument("--latency-samples", type=int, default=5,
                    help="jumlah sampel latency")
    ap.add_argument("--quick", action="store_true",
                    help="mode cepat: durasi 4 dtk, thread lebih sedikit")
    ap.add_argument("--json", action="store_true", help="output JSON")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.quick:
        args.duration = 4.0
        args.threads_dl = 4
        args.threads_ul = 4
        args.latency_samples = 3

    st = SpeedTest(engine=args.engine,
                   threads_dl=args.threads_dl,
                   threads_ul=args.threads_ul,
                   duration=args.duration,
                   warmup=args.warmup,
                   latency_samples=args.latency_samples)

    phases = {"latency": "mengukur ping...",
              "download": "mengukur download...",
              "upload": "mengukur upload...",
              "pilih server": "mencari server Ookla tercepat..."}
    t0 = time.perf_counter()
    try:
        hasil = st.run(
            on_phase=lambda p: print(" " + phases.get(p, p), flush=True)
            if not args.json else None)
    except KeyboardInterrupt:
        print("\nDibatalkan.")
        raise SystemExit(1)
    except Exception as e:
        print("Gagal: %s" % e)
        raise SystemExit(1)
    elapsed = time.perf_counter() - t0

    if args.json:
        print(json.dumps(hasil, indent=2))
        return

    print("=== Hasil SpeedTest (%s) ===" % hasil["engine"])
    if hasil["server"]:
        s = hasil["server"]
        print("Server   : %s (%s, %s)" % (
            s["sponsor"], s["name"], s["country"]))
    print("Ping     : %.2f ms  (jitter %.2f ms)" % (
        hasil["ping_ms"], hasil["jitter_ms"]))
    print("Download : %.2f Mbps" % hasil["download_mbps"])
    print("Upload   : %.2f Mbps" % hasil["upload_mbps"])
    for note in hasil.get("notes", []):
        print("Catatan  : %s" % note)
    print("Waktu    : %.1f detik" % elapsed)


if __name__ == "__main__":
    main()
