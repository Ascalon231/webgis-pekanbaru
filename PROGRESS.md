# WebGIS Hidrologi Pekanbaru — Progress Report

## Ringkasan Proyek
WebGIS interaktif untuk analisis hidrologi dan visualisasi kontur dari data
DEMNAS Pekanbaru + BATNAS, dengan integrasi data curah hujan real-time.

---

## Dataset

| Data | Sumber | Coverage | Resolusi | Ukuran |
|------|--------|----------|----------|--------|
| DEMNAS | BIG | 4 tiles (~101.25-101.75°E, 0.25-0.75°S) | ~8.3m | 172MB |
| DEMNAS Pekanbaru | Clip administrasi | Batas Kota Pekanbaru | ~8.3m | 31MB |
| BATNAS | BIG | 100-105°E, 0-5°N | ~185m | 35MB |
| Administrasi | BIG (514 kab/kota) | Nasional | - | 401MB |
| Riau boundary | Clip 514 → 12 kab/kota | Provinsi Riau | - | 7.8MB |
| Pekanbaru boundary | Clip 514 → 1 kota | Kota Pekanbaru | - | 186KB |

## Preprocessing Selesai

### DEM → UTM → Hidrologi (pysheds)
- [x] Reproject DEM ke UTM 48N (EPSG:32648, resolusi 10m)
- [x] Sink Fill → Flow Direction (D8) → Flow Accumulation
- [x] Stream network extraction (threshold 1000 cells)
- [x] Catchment delineation (max accumulation pour point)
- [x] Sink difference raster (genangan)
- [x] Patch `np.in1d` → `np.isin` di pysheds untuk NumPy ≥1.25

### Batas Administrasi
- [x] Extract Riau (12 kab/kota) dari 514 kab/kota nasional
- [x] Clip Pekanbaru dari Riau

### Kontur
- [x] Generate 3 interval: 1m, 5m, 10m dari DEMNAS Pekanbaru
- [x] Simplify geometri (tolerance 0.0001°)
- [x] Konversi ke raster tiles (PNG) — jauh lebih ringan dari GeoJSON langsung

### BATNAS — Analisis Muara Siak
- [x] Cross-section E-W dan N-S
- [x] Statistik kedalaman (min, max, mean)
- [x] Lokasi muara: ~102.1°E, 1.1°N

## Server (Flask)

### Endpoint Berfungsi
| Route | Method | Fungsi |
|-------|--------|--------|
| `/` | GET | Index page |
| `/tiles/<layer>/<z>/<x>/<y>.png` | GET | Raster tiles (dem, batnas, hillshade, batnas_hillshade, facc, sinkdiff) |
| `/tiles/contour/<interval>/<z>/<x>/<y>.png` | GET | Contour raster tiles (1m/5m/10m) |
| `/tiles/risk/<z>/<x>/<y>.png` | GET | **NEW** Zona Risiko Banjir |
| `/api/elevation` | GET | Query elevasi + flow acc di titik |
| `/api/risk-score` | GET | **NEW** Zona risiko + rekomendasi di titik |
| `/api/contours` | GET | Generate kontur on-demand (jarang dipakai) |
| `/api/siak` | GET | Analisis muara Siak |
| `/api/weather` | GET | **NEW** Proxy RainViewer (cache 120s) |
| `/api/info` | GET | Info layer yang tersedia |
| `/data/<filename>` | GET | Serve GeoJSON file |

### Teknis
- Flask threaded, port 5000
- Tile cache in-memory (`TILE_CACHE`)
- Contour via shapely STRtree + PIL rendering
- RainViewer API cached 120 detik
- Zona risiko: composite dari elevasi + flow acc + sink diff

## Frontend (Leaflet)

### Layer Tersedia
| Layer | Tipe | Default |
|-------|------|---------|
| Basemap CartoDB Positron | Tile | ✅ |
| Curah Hujan Real-time | RainViewer tile | ❌ |
| Prakiraan Hujan 2 Jam | RainViewer tile | ❌ |
| Kontur (1m/5m/10m) | Raster tile | ✅ 5m |
| Aliran Air Hujan | Raster tile (facc) | ✅ |
| Sungai | GeoJSON | ✅ |
| Genangan | Raster tile (sinkdiff) | ❌ |
| Zona Risiko | Raster tile (composite) | ❌ |
| Wilayah Aliran Siak | GeoJSON | ❌ |
| Analisis Muara | Panel | ❌ |

### Fitur Tambahan
- [x] Klik titik → info elevasi + akumulasi + zona risiko + rekomendasi
- [x] Animasi curah hujan (play/pause/slider)
- [x] Legenda dinamis per layer aktif
- [x] Toolbar bawah untuk toggle cepat
- [x] Tooltip pada hover batas administrasi

---

## Arsitektur

```
Browser (Leaflet) ←→ Flask Server ←→ Raster files (.tif)
                         ↕
                   RainViewer API
                         ↕
                   GeoJSON files
```

### Data Flow
1. **Tiles**: Browser request `/{layer}/{z}/{x}/{y}.png` → Server baca raster window → colormap → PNG
2. **Contour**: Server load GeoJSON + STRtree → query per tile → PIL render → PNG
3. **Zona Risiko**: Server baca 3 raster → normalisasi → kombinasi bobot → classify → PNG
4. **Weather**: Server proxy + cache RainViewer → browser animasi tile
5. **Query**: Browser klik → Flask query raster di koordinat → return JSON

### CRS Pipeline
```
DEMNAS (EPSG:4326, no CRS tag)
  ├── force EPSG:4326 (gdalwarp -a_srs)
  ├── reproject UTM 48N (pysheds)
  │   ├── Sink Fill → Flow Dir → Flow Acc → Stream → Catchment
  │   └── reproject EPSG:4326 (tile serving)
  └── kontur (gdal_contour)
      └── simplify → STRtree → raster tiles
```

## Known Issues
1. `ADm.geojson` 401MB di root project — tidak dipakai, perlu dibersihkan
2. `dem_fdir.tif`, `dem_filled.tif`, `dem_streams.tif` — file intermediate bisa dibersihkan
3. Tile cache tidak terbatas — potensi memory leak pada uptime lama
4. `serve_data` parsing ulang GeoJSON → perlu `send_file` untuk optimasi
5. RainViewer max zoom 7 — pixelated di zoom tinggi, tapi masih usable

## Next Steps
1. ✅ Integrasi RainViewer untuk curah hujan real-time
2. ✅ Zona risiko banjir (composite layer)
3. ✅ UI ramah awam dengan legenda jelas
4. ⏳ Deploy ke platform production
5. ⏳ Optimasi cache (LRU/TTL)
6. ⏳ Bersihkan file tidak terpakai
