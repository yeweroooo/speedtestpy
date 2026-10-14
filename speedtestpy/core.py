"""Orkestrasi speed test: kelas SpeedTest (API publik)."""

from datetime import datetime, timezone

from . import cloudflare, ookla
from .net import to_mbps


class SpeedTest:
    """Speed test akurat & cepat. Engine: 'cloudflare' atau 'ookla'."""

    def __init__(self, engine="cloudflare", threads_dl=8, threads_ul=6,
                 duration=8.0, warmup=None, latency_samples=5):
        if engine not in ("cloudflare", "ookla"):
            raise ValueError("engine harus 'cloudflare' atau 'ookla'")
        self.engine = engine
        self.threads_dl = max(1, int(threads_dl))
        self.threads_ul = max(1, int(threads_ul))
        self.duration = max(2.0, float(duration))
        # warmup=None -> otomatis 8x RTT (lihat net.auto_warmup).
        self.warmup = (min(float(warmup), self.duration / 2.0)
                       if warmup is not None else None)
        self.latency_samples = max(2, int(latency_samples))

    def run(self, on_phase=None):
        """Jalankan test penuh. on_phase(name) dipanggil tiap tahap dimulai."""
        eng = cloudflare if self.engine == "cloudflare" else ookla
        lat, dl, ul, warmup, server_info = eng.measure(
            self.threads_dl, self.threads_ul, self.duration,
            self.warmup, self.latency_samples, on_phase)

        notes = []
        n_limited = sum(r[2] for r in dl if len(r) > 2)
        if n_limited:
            notes.append(
                "Sebagian request download dibatasi server (rate limit); "
                "angka download bisa lebih rendah dari kecepatan aktual.")

        return {
            "engine": self.engine,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ping_ms": round(lat["ping_ms"], 2),
            "jitter_ms": round(lat["jitter_ms"], 2),
            "latency_samples_ms": lat["samples_ms"],
            "download_mbps": round(to_mbps(dl), 2),
            "upload_mbps": round(to_mbps(ul), 2),
            "server": server_info,
            "notes": notes,
            "config": {
                "threads_dl": self.threads_dl,
                "threads_ul": self.threads_ul,
                "duration_s": self.duration,
                "warmup_s": round(warmup, 2),
            },
        }
