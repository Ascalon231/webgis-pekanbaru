# WebGIS Hidrologi Pekanbaru — Progress Report

## Ringkasan Proyek
WebGIS interaktif untuk analisis hidrologi dan visualisasi kontur dari data
DEMNAS Pekanbaru + BATNAS, dengan integrasi data curah hujan real-time.

---

## Dataset

| Data | Sumber | Coverage | Resolusi | Ukuran |
|------|--------|----------|----------|--------|
| DEMNAS Pekanbaru | BIG (clip) | Batas Kota Pekanbaru | ~8.3m | 31MB |
| BATNAS | BIG | 100-105°E, 0-5°N | ~185m | 35MB |
| Pekanbaru boundary | BIG (clip) | Kota Pekanbaru | - | 186KB |
| Bangunan | OSM | Kota Pekanbaru | - | ? |
| Flow Accumulation | PySheds | Kota Pekanbaru | ~10m | 18MB |
| Sink Difference | PySheds | Kota Pekanbaru | ~10m | 6.4MB |

## ✅ Sudah Selesai

### Preprocessing Hidrologi
- [x] Reproject DEM ke UTM 48N → Sink Fill → Flow Direction → Flow Accumulation
- [x] Stream network extraction (threshold 1000 cells)
- [x] Catchment delineation + Sink difference raster
- [x] Kontur 1m/5m/10m + simplify
- [x] Analisis muara Siak (cross-section E-W/N-S)

### Server (Flask) — Endpoint
| Route | Fungsi |
|-------|--------|
| `/tiles/<layer>/<z>/<x>/<y>.png` | Raster tiles (dem, batnas, facc, sinkdiff) |
| `/tiles/terrainrgb/<z>/<x>/<y>.png` | Mapbox Terrain-RGB on-the-fly |
| `/tiles/contour/<interval>/<z>/<x>/<y>.png` | Kontur raster tiles |
| `/tiles/risk/<z>/<x>/<y>.png` | Zona Risiko Banjir composite |
| `/tiles/inundation/<mm>/<z>/<x>/<y>.png` | Simulasi genangan slider |
| `/tiles/streams/<z>/<x>/<y>.png` | Sungai raster tiles (dari FlatGeobuf) |
| `/api/elevation` | Query elevasi + flow acc |
| `/api/risk-score` | Zona risiko + rekomendasi |
| `/api/weather` | Proxy RainViewer (cache 120s) |
| `/api/weather/alert` | Status peringatan dini |
| `/api/siak` | Analisis muara Siak |
| `/data/<filename>` | Serve GeoJSON/geojson |

### Frontend — 2D Leaflet
- [x] Layer: DEM, kontur (1/5/10m), aliran, sungai, genangan, risiko
- [x] Simulasi genangan interaktif (slider 10-500mm)
- [x] RainViewer animasi (play/pause/slider/forecast)
- [x] Klik titik → info elevasi + akumulasi + zona risiko
- [x] Legenda dinamis, toolbar, sidebar glassmorphism
- [x] Flood early warning banner (auto-refresh 60s)

### Frontend — 3D MapLibre
- [x] Terrain dari DEM (terrain-rgb, 4x exaggeration default)
- [x] Hillshade native (`type: hillshade`, GPU-accelerated)
- [x] Kontur overlay, Sungai (GeoJSON), Boundary
- [x] Pencahayaan dinamis (shadow/highlight/accent color)

### Optimasi & Code Quality
- [x] SQLite persistent tile cache (ganti LRUCache in-memory)
- [x] GeoJSON → FlatGeobuf (streams, contours) — zero persistent memory
- [x] Hillshade server-side removed (pindah ke native MapLibre)
- [x] Raw DEMNAS tiles dihapus (172MB freed)
- [x] Contour GeoJSON dihapus (78MB freed)
- [x] Nodata handling terrain-RGB: fill dengan elevasi minimum valid

## 🚧 Dalam Pengerjaan / Rencana

### 1. Bangunan OSM (✅ Selesai)
- [x] Download 10.546 bangunan dari OpenStreetMap via Overpass API (quadrant query)
- [x] Simpan sebagai `pekanbaru_buildings.geojson` (3.1MB) + FlatGeobuf (2.8MB)
- [x] 3D MapLibre: `fill-extrusion` layer dengan height dari tag OSM
- [x] 2D Leaflet: polygon overlay abu-abu semi-transparan (toggle di sidebar)
- [x] Toggle bangunan di 3D viewer (tombol "Bangunan" di kontrol 3D)

### 2. Infrastruktur Deploy (✅ Selesai)
- [x] `requirements.txt` — semua dependency Python
- [x] `Dockerfile` — base OSGeo ubuntu-small + Gunicorn (port 8080)
- [x] `.gitignore` — tambah tile_cache.db
- [ ] ⏳ Deploy ke Railway / Fly.io (manual — perlu akun + CLI)

### 3. (Future) Fitur Tambahan
- [ ] Delineasi DAS on-demand (butuh regenerate flow direction)
- [ ] Notifikasi Telegram untuk early warning
- [ ] Legend untuk 3D viewer

---

