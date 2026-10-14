"""Engine Cloudflare: endpoint speed.cloudflare.com."""

from .download import download_worker
from .net import auto_warmup, measure_latency, run_threads
from .upload import upload_worker

HOST = "speed.cloudflare.com"
DOWN_TEMPLATE = "/__down?bytes={n}"
DOWN_BYTES = 2000000
UP_PATH = "/__up"
LAT_PATH = "/__down?bytes=0"


def measure(threads_dl, threads_ul, duration, warmup, latency_samples,
            on_phase=None):
    def phase(name):
        if on_phase:
            on_phase(name)

    phase("latency")
    lat = measure_latency(True, HOST, LAT_PATH, samples=latency_samples)
    if warmup is None:
        warmup = auto_warmup(lat["ping_ms"], duration)
    phase("download")
    dl = run_threads(
        download_worker,
        [(True, HOST, DOWN_TEMPLATE, DOWN_BYTES,
          duration, warmup)] * threads_dl)
    phase("upload")
    ul = run_threads(
        upload_worker,
        [(True, HOST, UP_PATH, duration)] * threads_ul)
    return lat, dl, ul, warmup, None
