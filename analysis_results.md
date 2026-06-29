# Workspace Analysis & Enhancements: WebGIS Pekanbaru Hydrological Analysis

This document provides a comprehensive analysis of the project workspace directory, identifying areas of improvement, listing clean-up actions, and describing the technical fixes implemented.

---

## 1. Directory Structure Analysis

The workspace represents a WebGIS dashboard for hydrological analysis and flood risk assessment of Pekanbaru City using BIG datasets (DEMNAS, BATNAS).

### Core Components
* **`server.py`**: A Flask server hosting geospatial analysis REST API endpoints and serving dynamic map tiles.
* **`templates/index.html`**: A Leaflet.js-based interactive mapping dashboard.
* **`PROGRESS.md`**: Tracks implemented steps and technical guidelines.
* **`.agents/`**: Holds agent configurations and project rules.
* **Raster Datasets (`.tif`)**:
  - `DEMNAS_0816-*.tif`: Four 10m-resolution Digital Elevation Model tiles covering Pekanbaru.
  - `BATNAS_*.tif`: National Bathymetry data for downstream estuary sea-level rise modeling.
  - `dem_facc_4326.tif` & `dem_sinkdiff_4326.tif`: Flow Accumulation and Depressions processed via PySheds.
* **Vector Datasets (`.geojson`)**:
  - `pekanbaru_boundary.geojson`: Administrative boundary outline for Pekanbaru City.
  - `streams.geojson` & `siak_catchment.geojson`: River networks and the main Siak watershed area.
  - `contours_*_simple.geojson`: Simplified elevation contour vectors.

---

## 2. Issues Identified & Solved

### 📂 A. Excessive Disk Usage from Leftover Files
> [!IMPORTANT]
> The workspace was carrying large, unused files left over from processing.
* **`Pekanbaru ADm.geojson` (420.1 MB)**: A massive geojson file representing the administrative boundaries of all cities in Riau/Indonesia, of which only Pekanbaru was needed. The actual active frontend uses `pekanbaru_boundary.geojson` (186 KB).
* **Intermediate files**: `dem_sinkdiff.tif` (5.3 MB), `dem_mosaic.vrt` (2 KB), and `dem_mosaic_wgs84.vrt` (2 KB) were leftover intermediate steps.
* **Fix**: Cleaned up these files, reclaiming over **425 MB** of disk space.

### 🧠 B. Memory Leak Risk in Flask Server
* **Observation**: `TILE_CACHE` was initialized as a standard python dictionary (`TILE_CACHE = {}`) and populated indefinitely as users navigated the map. Over time, active browsing across different zoom levels would cause memory usage to grow without bound.
* **Fix**: Replaced the dict with a custom, thread-safe `LRUCache` of size 4096 utilizing `collections.OrderedDict` and `threading.Lock`. This caps the memory usage of the tile server while keeping performance high.

### 🗺️ C. Spatial Distortion/Stretching Bug at DEM Boundaries
* **Observation**: When rendering tiles overlapping multiple DEM files (boundary regions), the system computed partial overlaps and read them directly into a 256x256 shape. If a window only partially overlapped a DEM tile, the returned data was scaled/stretched to 256x256, distorting coordinates and heights at boundary lines.
* **Fix**: Updated `read_raster_window` to support `boundless=True` with `fill_value=src.nodata` in `rasterio`. This enables reading the entire requested tile bounds seamlessly, ensuring no spatial distortion or coordinate shifts happen at boundaries.

### 🎨 D. Basic UI Styling
* **Observation**: The dashboard relied on browser-default fonts, standard white background cards, and a single light mode basemap, lacking the premium feel required for a state-of-the-art GIS portal.
* **Fix**:
  1. Imported **Plus Jakarta Sans** from Google Fonts.
  2. Implemented a dark **glassmorphism** UI style for the sidebar, info cards, legends, and buttons using `backdrop-filter: blur(12px)` and transparent slate colors.
  3. Styled the scrollbars and customized the Leaflet default elements (Zoom controls, Attributions) to match the dark theme perfectly.
  4. Added a **Basemap Switcher** allowing users to switch between **Dark Mode (Sleek)**, **Light Mode (Clean)**, and **Satellite Imagery**.
  5. Modernized the loading overlay using a CSS spinner animation with a blurred overlay.

---

## 3. Current File Mapping

All updated files and their links are listed below:

| File | Status | Description |
|---|---|---|
| [server.py](file:///home/ripan231/Projects/Webgis-%20Pekan%20Baru%20Pemodelan/server.py) | **Updated** | Fixed merge distortions, added thread-safe `LRUCache` for map tiles. |
| [templates/index.html](file:///home/ripan231/Projects/Webgis-%20Pekan%20Baru%20Pemodelan/templates/index.html) | **Updated** | Premium UI redesign, added Basemap switcher (Dark/Light/Satellite). |
| [PROGRESS.md](file:///home/ripan231/Projects/Webgis-%20Pekan%20Baru%20Pemodelan/PROGRESS.md) | **Reviewed** | Tracks general progress. Next step is deployment. |
