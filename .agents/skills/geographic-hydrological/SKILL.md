---
name: geographic-hydrological
description: |
  Geographic analysis and hydrological modeling from DEM data.
  Covers CRS/projection handling, DEM preprocessing, flow routing, watershed delineation,
  contour generation, and server-side tile rendering for WebGIS.
---

# Geographic & Hydrological Modeling Skill

This skill provides best practices for processing Digital Elevation Models (DEM),
performing hydrological analysis, and serving results via WebGIS (Flask + Leaflet).

---

## 1. CRS & Projection Design

### A. Always Validate CRS First
Many Indonesian DEM sources (DEMNAS, BATNAS) ship without embedded CRS.
The coordinates are de facto EPSG:4326 (WGS84), but `rasterio.crs` may return `None`.

```python
import rasterio
with rasterio.open('dem.tif') as src:
    print(src.crs)  # Often None
```

### B. Reproject for Hydrological Analysis
PySheds and flow routing algorithms require projected CRS (meters, not degrees).
Use UTM zone matching the area longitude:

```python
# Pekanbaru ~101.45°E → UTM 48N (EPSG:32648)
import subprocess
subprocess.run([
    'gdalwarp', '-t_srs', 'EPSG:32648', '-tr', '10', '10',
    '-r', 'bilinear', '-of', 'GTiff',
    'dem_4326.tif', 'dem_utm.tif'
])
```

### C. Reproject Back for Web Display
All Leaflet/MapLibre basemaps use EPSG:3857 (Web Mercator).
Always reproject analysis rasters back to EPSG:4326 (or 3857) for tile serving:

```python
subprocess.run([
    'gdalwarp', '-t_srs', 'EPSG:4326', '-tr', '0.0001', '0.0001',
    '-r', 'bilinear', 'dem_utm.tif', 'dem_4326.tif'
])
```

---

## 2. Hydrological Modeling with PySheds

### A. Workflow Order
1. Fill sinks -> `fill_depressions`
2. Compute flow direction -> `flowdir_d8` (or `flowdir_mfd`)
3. Computer flow accumulation -> `accumulation`
4. Extract stream network -> threshold on accumulation
5. Delineate catchment -> pour point on accumulation maxima

### B. PySheds Patch Note
PySheds uses `np.in1d` which was deprecated in NumPy 1.25+.
Patch by replacing with `np.isin` in the installed pysheds source:

```
# In pysheds/grid.py, replace:
#   np.in1d(...) -> np.isin(...)
```

### C. Stream Threshold
Use a threshold of ~1000 cells for stream extraction. Adjust based on:
- DEM resolution (10m → 1000 cells = 10km² drainage area minimum)
- Visual density of stream network

```python
branches = grid.extract_branches(fdir)
branches = branches[branches.cellcount > threshold]
```

### D. Catchment Extraction
Pour point location requires finding max accumulation cell:

```python
max_row, max_col = np.unravel_index(np.argmax(acc), acc.shape)
catch = grid.catchment(x=acc[max_col, max_row], y=fdir[max_row, max_col])
```

---

## 3. Contour Generation

### A. From Raster to GeoJSON
Use `gdal_contour` for fast contour extraction:

```bash
gdal_contour -i 5 -a elev dem.tif contours.shp
ogr2ogr -f GeoJSON -lco COORDINATE_PRECISION=6 contours.geojson contours.shp
```

### B. Simplification for Web
Simplify geometries to reduce file size before serving:

```bash
ogr2ogr -f GeoJSON -simplify 0.0001 contours_simple.geojson contours.geojson
```

### C. Tile-Based Rendering (Preferred)
For browser performance, render contour lines as raster tiles (PNG)
instead of sending raw GeoJSON (which can be 10-60MB):

```python
# Server-side: use shapely STRtree for spatial index + PIL for rendering
from shapely.geometry import shape, box
from shapely.strtree import STRtree
from PIL import Image, ImageDraw

# Load once, cache in memory
features = [{'geom': shape(f['geometry']), 'elev': f['properties']['elev']}
            for f in geojson['features']]
tree = STRtree([f['geom'] for f in features])

# Per-tile request
indices = tree.query(tile_bounds_box, predicate='intersects')
img = Image.new('RGBA', (256, 256), (0,0,0,0))
draw = ImageDraw.Draw(img)
for idx in indices:
    # Draw line with proper styling (index contours thicker/darker)
    ...
```

### D. Cartographic Styling
- Index contours (every 25m): thicker (2.5-3px), darker brown (#5C3A1E)
- Intermediate contours: thinner (1px), lighter brown (#A67B5B)
- Labels: on index contours only, at approximate midpoints

---

## 4. Tile Serving Architecture

### A. Raster Tile Endpoint Pattern
Serve analysis results (flow accumulation, sink diff, contours) as pre-rendered
256x256 PNG tiles for Leaflet:

```python
@app.route('/tiles/<layer>/<int:z>/<int:x>/<int:y>.png')
def serve_tile(layer, z, x, y):
    lng_left, lat_bottom, lng_right, lat_top = tile_to_bounds(x, y, z)
    # Read raster window at tile bounds
    data = read_raster_window(file, lng_left, lat_bottom, lng_right, lat_top)
    # Apply colormap and transparency
    colored = apply_colormap(data, cmap)
    alpha = np.where(np.isnan(data), 0, opacity)
    rgba = np.concatenate([colored, alpha[:,:,np.newaxis]], axis=2)
    return serve_png(Image.fromarray(rgba, 'RGBA'))
```

### B. Tile Caching
Always cache rendered tiles in a dict (keyed by layer+z+x+y).
This reduces repeated computation for the same tiles.

### C. Web Mercator Tile Math
```python
def tile_to_bounds(x, y, z):
    n = 2.0 ** z
    origin = 20037508.342789244
    min_x = (x / n) * 2 * origin - origin
    max_x = ((x + 1) / n) * 2 * origin - origin
    min_y = origin - ((y + 1) / n) * 2 * origin
    max_y = origin - (y / n) * 2 * origin
    return (lng_from_mercator(min_x), lat_from_mercator(min_y),
            lng_from_mercator(max_x), lat_from_mercator(max_y))
```

---

## 5. Known Issues & Mitigations

| Issue | Solution |
|-------|----------|
| DEM/raster has no CRS | Force EPSG:4326 in gdalwarp with `-a_srs EPSG:4326` |
| PySheds `np.in1d` error (NumPy ≥1.25) | Replace `in1d` with `isin` in pysheds source |
| Large GeoJSON contours (10-60MB) | Convert to raster tile endpoint |
| Proxy interference (http_proxy=127.0.0.1:8888) | Use `--noproxy '*'` for curl / unset proxy in Flask |
| Sink diff tile colors washed out | Clamp colormap to actual data range, not global |
| Flow accumulation log scale | Use `np.log10(data + 1)` before colormap |
| Contour tile rendering slow | Add tile cache; use STRtree with predicate='intersects' |
