"""Worker upload: N POST paralel dengan ukuran payload adaptif."""

import os
import time

from .net import UA, close_quietly, new_conn


def upload_worker(use_https, hostport, path, duration, out, idx):
    # Tiap POST ditarget ~2.5 detik supaya overhead slow-start dan tunggu
    # respons menjadi fraksi kecil dari waktu ukur.
    t_start = time.monotonic()
    t_end = t_start + duration
    target = max(1.0, min(2.5, duration / 3.0))
    cache = {}

    def payload(size):
        p = cache.get(size)
        if p is None:
            p = os.urandom(size)
            cache[size] = p
        return p

    size = 262144
    done_bytes = 0
    done_secs = 0.0
    skipped_first = False
    conn = None
    try:
        while time.monotonic() < t_end:
            data = payload(size)
            t0 = time.perf_counter()
            try:
                if conn is None:
                    conn = new_conn(
                        use_https, hostport,
                        timeout=min(duration + 30, 120))
                conn.request("POST", path, body=data, headers={
                    "Content-Type": "application/octet-stream",
                    "Content-Length": str(len(data)),
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "User-Agent": UA,
                })
                resp = conn.getresponse()
                resp.read()
                if resp.status not in (200, 201, 204):
                    raise OSError("HTTP %s" % resp.status)
            except Exception:
                close_quietly(conn)
                conn = None
                time.sleep(0.1)
                continue
            dt = time.perf_counter() - t0
            if dt > 0:
                factor = min(max(target / max(dt, 0.05), 0.25), 4.0)
                size = max(131072, min(int(size * factor), 67108864))
            if not skipped_first:
                # POST pertama masih dalam slow-start: buang.
                skipped_first = True
                continue
            done_bytes += len(data)
            done_secs += dt
    finally:
        close_quietly(conn)
    out[idx] = (done_bytes, max(done_secs, 0.001), 0)
