"""Worker download: N stream paralel, dua fase (warm-up lalu ukur)."""

import time

from .net import UA, close_quietly, new_conn


def download_worker(use_https, hostport, path, chunk_bytes, duration,
                    warmup, out, idx):
    """Fase warm-up mentransfer seperti biasa tapi byte-nya dibuang; fase
    ukur menghitung semua byte dibagi durasi fase.

    Warm-up menampung handshake TLS + slow-start TCP yang hanya terjadi
    sekali karena koneksi dipakai ulang (keep-alive). Jeda diam ikut
    dihitung sebagai waktu -- itu perilaku link, dan mengeluarkannya
    membuat link bursty (mis. WiFi lemah) terbaca jauh lebih cepat
    dari aslinya.
    """
    t_start = time.monotonic()
    t_warm_end = t_start + warmup
    t_end = t_warm_end + duration
    size = chunk_bytes or 0
    total_b = 0
    consec_403 = 0
    n_limited = 0
    conn = None

    def get_resp():
        # Minta satu respons; None bila waktu habis atau menyerah.
        nonlocal conn, size, consec_403, n_limited
        while True:
            if time.monotonic() >= t_end:
                return None
            try:
                if conn is None:
                    conn = new_conn(use_https, hostport, timeout=10)
                req_path = (path.replace("{n}", str(size))
                            if "{n}" in path else path)
                conn.request("GET", req_path, headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "User-Agent": UA,
                })
                resp = conn.getresponse()
                if resp.status in (403, 413, 429) and "{n}" in path:
                    # Cloudflare membatasi laju per IP: kecilkan request,
                    # tunggu sebentar dengan backoff, lalu lanjut.
                    resp.read()
                    consec_403 += 1
                    n_limited += 1
                    if consec_403 > 4:
                        return None
                    size = max(2000000, size // 2)
                    time.sleep(min(2 ** consec_403, 8))
                    continue
                if resp.status != 200:
                    resp.read()
                    raise OSError("HTTP %s" % resp.status)
                consec_403 = 0
                return resp
            except Exception:
                close_quietly(conn)
                conn = None
                time.sleep(0.05)

    try:
        n_warm = 0
        t_w0 = time.monotonic()
        resp = get_resp()
        while resp is not None:
            if time.monotonic() >= t_warm_end:
                break
            try:
                chunk = resp.read(65536)
            except Exception:
                resp = get_resp()
                continue
            if not chunk:
                resp = get_resp()
                continue
            n_warm += len(chunk)
        warm_dt = time.monotonic() - t_w0
        # Ukuran request berikut diadaptasi dari rate warm-up: target
        # ~3 detik per request agar overhead antar-request kecil.
        if "{n}" in path and warm_dt > 0.2 and n_warm > 0:
            rate = n_warm / warm_dt
            size = max(4000000, min(int(rate * 3.0), 25000000))
        # Lanjutkan stream warm-up bila masih ada isinya.
        t_m0 = time.monotonic()
        if resp is None:
            resp = get_resp()
        while resp is not None:
            if time.monotonic() >= t_end:
                break
            try:
                chunk = resp.read(65536)
            except Exception:
                resp = get_resp()
                continue
            if not chunk:
                resp = get_resp()
                continue
            total_b += len(chunk)
        measure_s = max(time.monotonic() - t_m0, 0.001)
    finally:
        close_quietly(conn)
    out[idx] = (total_b, measure_s, n_limited)
