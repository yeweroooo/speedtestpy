# speedtestpy

Speed test yang akurat & cepat, ditulis murni dengan Python stdlib (tanpa dependensi pihak ketiga). Metodologinya meniru Ookla Speedtest dan Cloudflare Speed Test.

## Cara kerja

- **Latency**: beberapa sampel request kecil, diambil nilai *minimum* (bukan rata-rata, supaya kebal terhadap spike) + jitter.
- **Download**: N koneksi paralel dalam dua fase — *warm-up* (transfer jalan tapi byte-nya dibuang; menampung handshake TLS + slow-start TCP yang hanya terjadi sekali via keep-alive), lalu *fase ukur* (semua byte dibagi durasi fase). Jeda diam ikut dihitung sebagai waktu karena itu perilaku link; mengeluarkannya membuat link bursty (mis. WiFi lemah) terbaca jauh lebih cepat dari aslinya. Throughput total = **jumlah** rate per-thread, bukan rata-rata.
- **Upload**: N POST paralel dengan ukuran payload adaptif (target tiap POST ~2.5 detik) supaya overhead slow-start menjadi fraksi kecil. POST pertama tiap worker dibuang sebagai warm-up.
- **Warm-up otomatis**: 8x RTT (1–4 detik), karena link berlatency tinggi butuh waktu lebih lama untuk mencapai kecepatan penuh.

Dua engine:

- `cloudflare` (default): `speed.cloudflare.com/__down` dan `/__up`
- `ookla`: memilih server Speedtest.net dengan latency terendah (di-probe paralel), lalu menguji ke server tersebut

Dukungan proxy otomatis dari environment (`http_proxy`/`https_proxy`, menghormati `no_proxy`).

## Instalasi

```bash
pip install .
# atau tanpa instal:
python -m speedtestpy.cli
```

## Pakai

```bash
speedtestpy                        # test penuh, engine cloudflare
speedtestpy --engine ookla         # via server Ookla
speedtestpy --quick                # mode cepat (~10 detik)
speedtestpy --json                 # output JSON
speedtestpy --duration 12 --threads-dl 12
```

Sebagai library:

```python
from speedtestpy import SpeedTest

hasil = SpeedTest(engine="cloudflare").run()
print(hasil["download_mbps"], hasil["upload_mbps"], hasil["ping_ms"])
```

Hasil `run()` adalah dict berisi `engine`, `timestamp`, `ping_ms`, `jitter_ms`, `latency_samples_ms`, `download_mbps`, `upload_mbps`, `server` (info server Ookla, atau `None` untuk Cloudflare), `notes`, dan `config`.

## Validasi

Logika pengukuran diuji terhadap server HTTP lokal yang di-throttle pada kecepatan yang diketahui, termasuk pola pengiriman bursty (simulasi link tidak stabil):

| Link simulasi              | Terbaca |
|----------------------------|----------|
| 500 Kbps mulus, 1 thread   | 0.50 Mbps |
| 500 Kbps mulus, 4 thread   | 2.00 Mbps |
| 50 Mbps mulus, 2 thread    | 100.00 Mbps |
| 500 Kbps bursty, 1 thread  | 0.50 Mbps |
| 500 Kbps bursty, 4 thread  | 2.00 Mbps |

## Catatan

- Cloudflare menerapkan rate limit per IP pada endpoint `__down`. Jika limit terkena saat pengujian, script otomatis backoff dan hasil menyertakan peringatan di `notes` bahwa angka download bisa terbaca lebih rendah.
- Hasil di jaringan nyata bergantung pada kondisi saat pengujian (kepadatan, sinyal WiFi, routing ISP). Bandingkan selalu dalam momen dan jaringan yang sama.

## Lisensi

MIT
