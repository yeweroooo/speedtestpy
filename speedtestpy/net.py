"""Koneksi HTTP, proxy, latency, dan orkestrasi thread.

Semuanya di atas stdlib (http.client) agar kontrol penuh atas keep-alive,
timeout per operasi, dan tunneling proxy -- hal yang dibutuhkan worker
download/upload.
"""

import base64
import http.client
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request

UA = "speedtestpy/1.1.0"


def parse_target(url):
    if "://" not in url:
        return True, url
    p = urllib.parse.urlparse(url)
    return p.scheme == "https", p.netloc or p.hostname


def proxy_for_target(use_https, host):
    """URL proxy dari environment (seperti curl), menghormati no_proxy."""
    no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY") or ""
    for entry in no_proxy.replace(" ", "").split(","):
        e = entry.strip().lstrip(".")
        if e and (host == e or host.endswith("." + e)):
            return None
    names = (("https_proxy", "HTTPS_PROXY") if use_https
             else ("http_proxy", "HTTP_PROXY"))
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return os.environ.get("all_proxy") or os.environ.get("ALL_PROXY")


def new_conn(use_https, hostport, timeout):
    if ":" in hostport and not hostport.startswith("["):
        thost, tport_s = hostport.rsplit(":", 1)
        try:
            tport = int(tport_s)
        except ValueError:
            thost, tport = hostport, (443 if use_https else 80)
    else:
        thost, tport = hostport, (443 if use_https else 80)

    proxy_url = proxy_for_target(use_https, thost)
    if proxy_url:
        p = urllib.parse.urlparse(proxy_url)
        tunnel_headers = {}
        if p.username:
            user = urllib.parse.unquote(p.username)
            pwd = urllib.parse.unquote(p.password or "")
            token = base64.b64encode(
                ("%s:%s" % (user, pwd)).encode()).decode()
            tunnel_headers["Proxy-Authorization"] = "Basic " + token
        if use_https:
            ctx = ssl.create_default_context()
            conn = http.client.HTTPSConnection(
                p.hostname, p.port or 3128, timeout=timeout, context=ctx)
        else:
            conn = http.client.HTTPConnection(
                p.hostname, p.port or 3128, timeout=timeout)
        conn.set_tunnel(thost, tport, tunnel_headers or None)
        return conn

    if use_https:
        ctx = ssl.create_default_context()
        return http.client.HTTPSConnection(
            hostport, timeout=timeout, context=ctx)
    return http.client.HTTPConnection(hostport, timeout=timeout)


def close_quietly(conn):
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


def probe_once(use_https, hostport, path, timeout=5):
    t0 = time.perf_counter()
    conn = new_conn(use_https, hostport, timeout)
    try:
        conn.request("GET", path, headers={
            "Cache-Control": "no-cache",
            "Connection": "close",
            "User-Agent": UA,
        })
        resp = conn.getresponse()
        resp.read()
        # 2xx/3xx berarti server merespons (waktu ke header pertama);
        # 4xx/5xx berarti gagal.
        if resp.status >= 400:
            raise OSError("HTTP %s" % resp.status)
        return (time.perf_counter() - t0) * 1000.0
    finally:
        close_quietly(conn)


def measure_latency(use_https, hostport, path, samples=5, timeout=5):
    """Latency = MINIMUM beberapa sampel (bukan rata-rata) + jitter."""
    lat = []
    for _ in range(samples):
        try:
            lat.append(probe_once(use_https, hostport, path, timeout))
        except Exception:
            continue
    if not lat:
        raise RuntimeError("Latency: tidak ada sampel yang berhasil")
    # Minimum kebal terhadap spike; rata-rata justru bias ke atas.
    ping = min(lat)
    jitter = (sum(abs(lat[i] - lat[i - 1]) for i in range(1, len(lat)))
              / (len(lat) - 1)) if len(lat) > 1 else 0.0
    return {
        "ping_ms": ping,
        "jitter_ms": jitter,
        "samples_ms": [round(x, 2) for x in lat],
    }


def auto_warmup(ping_ms, duration):
    """Warm-up otomatis: 8x RTT (1-4 dtk).

    Link berlatency tinggi butuh warm-up lebih lama agar slow-start TCP
    selesai sebelum pengukuran dimulai.
    """
    return min(max(ping_ms / 1000.0 * 8, 1.0), 4.0, duration / 2.0)


def run_threads(worker, arg_sets):
    out = [None] * len(arg_sets)
    threads = []
    for i, args in enumerate(arg_sets):
        t = threading.Thread(target=worker, args=(*args, out, i), daemon=True)
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return [r for r in out if r is not None]


def to_mbps(results):
    """Throughput total = JUMLAH rate per-thread.

    Tiap thread berjalan paralel dan melaporkan (bytes, secs) pada
    jendelanya sendiri, jadi totalnya r1 + r2 + ... + rn. Menjumlahkan
    semua byte lalu membagi jumlah semua detik justru keliru -- itu
    rata-rata terbobot yang mengecil ~N kali lipat.
    """
    total = 0.0
    for r in results:
        b, s = r[0], r[1]
        if b > 0 and s > 0:
            total += (b * 8) / s / 1e6
    return total
