"""Engine Ookla: pilih server Speedtest.net berlatency terendah."""

import json
import threading
import time
import urllib.parse
import urllib.request

from .download import download_worker
from .net import (UA, auto_warmup, close_quietly, measure_latency, new_conn,
                  probe_once, run_threads)
from .upload import upload_worker

API = ("https://www.speedtest.net/api/js/servers"
       "?engine=js&https_functional=true&limit=30")
DL_FILE = "random4000x4000.jpg"


def _server_list(limit=30, timeout=12, retries=3):
    last_err = None
    for i in range(max(1, retries)):
        try:
            req = urllib.request.Request(API, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            # Format respons API tidak konsisten: list, {id: {...}},
            # atau {"servers": [...]} -- normalisasi jadi list.
            if isinstance(data, dict):
                if isinstance(data.get("servers"), list):
                    data = data["servers"]
                else:
                    data = list(data.values())
            result = [s for s in data if isinstance(s, dict) and s.get("url")]
            if result:
                return result
            last_err = RuntimeError("daftar server kosong")
        except Exception as e:
            last_err = e
        time.sleep(0.5 * (i + 1))
    raise RuntimeError("Gagal mengambil daftar server Ookla: %s" % last_err)


def _base(server):
    url = server.get("url", "")
    if "upload.php" in url:
        url = url.rsplit("upload.php", 1)[0]
    if not url.endswith("/"):
        url += "/"
    return url


def _targets(server):
    """Kandidat (use_https, hostport, prefix) untuk satu server.

    Port 8080 dicoba dulu (endpoint kanonis Ookla), lalu HTTPS 443 untuk
    firewall/proxy yang memblokir 8080.
    """
    base = _base(server)
    p = urllib.parse.urlparse(base)
    host = p.hostname or ""
    prefix = p.path or "/"
    cands = []
    if host:
        cands.append((False, "%s:8080" % host, prefix))
    if str(server.get("https_functional")) == "1" and host:
        cands.append((True, host, prefix))
        if prefix != "/":
            cands.append((True, host, "/"))
    return cands


def pick_server(limit=30, rounds=2):
    """Probe paralel semua kandidat; kembalikan list terurut latency.

    Tiap panggilan API mengembalikan server acak, jadi daftar diambil
    `rounds` kali lalu digabung (buang duplikat) agar peluang dapat
    server yang terjangkau lebih besar.
    """
    seen, servers = set(), []
    got_list = False
    for _ in range(max(1, rounds)):
        try:
            batch = _server_list(limit)
            got_list = True
        except Exception:
            break
        for s in batch:
            host = urllib.parse.urlparse(s.get("url", "")).hostname
            if host and host not in seen:
                seen.add(host)
                servers.append(s)
        if len(servers) >= 60:
            break
    if not got_list:
        raise RuntimeError("Gagal mengambil daftar server Ookla")
    scored = []
    lock = threading.Lock()
    # Terlalu banyak CONNECT bersamaan membuat proxy/firewall kewalahan
    # dan semuanya timeout -- batasi 12.
    sem = threading.Semaphore(12)

    def probe(srv):
        with sem:
            for use_https, hostport, prefix in _targets(srv):
                try:
                    # Server yang >3 detik menjawab latency.txt memang
                    # bukan pilihan bagus.
                    ms = probe_once(
                        use_https, hostport, prefix + "latency.txt", timeout=3)
                    with lock:
                        scored.append((ms, srv, use_https, hostport, prefix))
                    return
                except Exception:
                    continue

    threads = [threading.Thread(target=probe, args=(s,), daemon=True)
               for s in servers]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if not scored:
        raise RuntimeError("Tidak ada server Ookla yang bisa dijangkau")
    scored.sort(key=lambda x: x[0])
    return [{"server": srv, "probe_ms": ms, "use_https": use_https,
             "hostport": hostport, "prefix": prefix}
            for ms, srv, use_https, hostport, prefix in scored]


def resolve_redirects(use_https, hostport, path, timeout=8, max_hops=4):
    """Ikuti redirect (301/302/303/307/308); kembalikan target final.

    Banyak server kini me-redirect ke *.prod.hosts.ooklaserver.net:8080
    (platform hosting Ookla, layout file sama) -- ikuti sampai dapat
    respons 200/206. Return None bila gagal/loop.
    """
    cur_https, cur_hostport, cur_path = use_https, hostport, path
    seen = set()
    for _ in range(max_hops + 1):
        key = (cur_https, cur_hostport, cur_path)
        if key in seen:
            return None
        seen.add(key)
        conn = new_conn(cur_https, cur_hostport, timeout)
        try:
            conn.request("GET", cur_path, headers={
                "Range": "bytes=0-0",
                "Cache-Control": "no-cache",
                "Connection": "close",
                "User-Agent": UA,
            })
            resp = conn.getresponse()
            resp.read(1024)
            if resp.status in (200, 206):
                return cur_https, cur_hostport, cur_path
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    return None
                base = "%s://%s%s" % ("https" if cur_https else "http",
                                      cur_hostport, cur_path)
                absu = urllib.parse.urljoin(base, loc)
                pu = urllib.parse.urlparse(absu)
                if pu.scheme not in ("http", "https") or not pu.netloc:
                    return None
                cur_https = (pu.scheme == "https")
                cur_hostport = pu.netloc
                cur_path = pu.path or "/"
                if pu.query:
                    cur_path += "?" + pu.query
                continue
            return None
        except Exception:
            return None
        finally:
            close_quietly(conn)
    return None


def _verify_candidates(candidates):
    """Verifikasi paralel: kandidat pertama (urutan latency) yang file
    download-nya benar-benar ada yang dipakai."""
    resolved = [None] * len(candidates)
    sem = threading.Semaphore(6)

    def verify(i, c):
        with sem:
            resolved[i] = resolve_redirects(
                c["use_https"], c["hostport"], c["prefix"] + DL_FILE)

    vthreads = [threading.Thread(target=verify, args=(i, c))
                for i, c in enumerate(candidates)]
    for t in vthreads:
        t.start()
    for t in vthreads:
        t.join()
    for c, f in zip(candidates, resolved):
        if f:
            return c, f
    return None, None


def measure(threads_dl, threads_ul, duration, warmup, latency_samples,
            on_phase=None):
    def phase(name):
        if on_phase:
            on_phase(name)

    phase("pilih server")
    candidates = pick_server()[:12]
    pick, final = _verify_candidates(candidates)
    if pick is None or final is None:
        raise RuntimeError("Tidak ada server Ookla yang layak dipakai")
    server = pick["server"]
    use_https, hostport, dl_path = final
    upath = dl_path.rsplit("/", 1)[0] + "/"
    server_info = {
        "name": server.get("name"),
        "sponsor": server.get("sponsor"),
        "country": server.get("country"),
        "id": server.get("id"),
        "target": "%s://%s%s" % (
            "https" if use_https else "http", hostport, upath),
        "probe_ms": round(pick["probe_ms"], 2),
    }
    phase("latency")
    lat = measure_latency(use_https, hostport, upath + "latency.txt",
                          samples=latency_samples)
    if warmup is None:
        warmup = auto_warmup(lat["ping_ms"], duration)
    phase("download")
    dl = run_threads(
        download_worker,
        [(use_https, hostport, upath + DL_FILE, 0,
          duration, warmup)] * threads_dl)
    phase("upload")
    ul = run_threads(
        upload_worker,
        [(use_https, hostport, upath + "upload.php",
          duration)] * threads_ul)
    return lat, dl, ul, warmup, server_info
