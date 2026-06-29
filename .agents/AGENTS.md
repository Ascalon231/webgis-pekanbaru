# Agent Rules for WebGIS Pekanbaru Hydrological Analysis

This file defines workspace-scoped rules for agents working on this repository.

## 1. Geographic & Projection Standards
- **CRS Validation**: Always check rasterio `src.crs` before processing. DEMNAS/BATNAS may have `None` CRS. Force to EPSG:4326 with `-a_srs EPSG:4326` in gdalwarp.
- **UTM for Analysis**: Use EPSG:32648 (UTM 48N) for Pekanbaru area (~101.45°E) when running pysheds flow routing.
- **EPSG:4326 for Tiles**: All raster tiles served to Leaflet must be in EPSG:4326 with bilinear resampling.
- **Tile Math**: Use Web Mercator tile-to-bounds conversion for `z/x/y` → lat/lng.

## 2. Hydrological Analysis with PySheds
- **Workflow order**: Sink Fill → Flow Direction (D8) → Flow Accumulation → Stream Extraction → Catchment Delineation.
- **Stream threshold**: Use 1000 cells (~10km² min drainage) as default.
- **PySheds patch**: `np.in1d` must be replaced with `np.isin` in `pysheds/grid.py` for NumPy ≥1.25 compatibility.
- **Pour point**: Use the maximum accumulation cell for catchment extraction.

## 3. Contour & Tile Rendering
- **Prefer raster tiles over GeoJSON** for contour display in browser. GeoJSON files >5MB cause slow page loads.
- **Contour styling** (server-side PIL): index contours (every 25m) = brown #5C3A1E width 3; intermediate = brown #A67B5B width 1.
- **Spatial index**: Use shapely STRtree with `predicate='intersects'` for efficient contour tile queries.
- **Cache**: All tiles must be cached in `TILE_CACHE` dict to avoid repeated computation.

## 4. Dependencies
- `pysheds` — hydrological algorithms
- `shapely` — spatial indexing for contour tiles
- `rasterio` + `numpy` — raster I/O and processing
- `Pillow` — tile image rendering
- `matplotlib` — colormap generation
- `gdal` (CLI) — contour extraction, reprojection
