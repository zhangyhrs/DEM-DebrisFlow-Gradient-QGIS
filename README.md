# DEM Debris Flow Gradient

[中文说明](README_CN.md)

A QGIS plugin for rapid calculation of debris-flow main-channel longitudinal gradient from DEM data.

## Features

The plugin provides two workflows:

1. **DEM + watershed polygons** — use existing debris-flow watershed boundaries as independent calculation units.
2. **DEM + outlet points** — snap outlet points to nearby high-flow-accumulation cells, automatically delineate watersheds, trace the main channel, and calculate longitudinal gradient.

Core workflow:

`DEM → depression filling → D8 flow direction → flow accumulation → outlet determination/snapping → watershed extraction → main-channel tracing → elevation difference → channel length → longitudinal gradient`

The longitudinal gradient is calculated as:

`Gradient (‰) = (top elevation - outlet elevation) / main-channel length × 1000`

## Method basis and reference

The overall technical idea of this plugin refers to the paper by Zhang Su, **“基于 DEM 的泥石流流域纵比降的快速计算方法”** (*Rapid calculation method of debris-flow watershed longitudinal gradient based on DEM*). The paper uses DEM-based hydrological analysis to extract the debris-flow main channel and calculates longitudinal gradient from elevation difference and channel length.

The original paper assumes that debris-flow watershed boundaries are already available. Accordingly, the plugin's **DEM + watershed polygons** workflow follows the same general idea. The plugin further extends this workflow with a **DEM + outlet points** mode that automatically delineates watersheds when no watershed polygon data are available.

Reference:

> Zhang Su. 基于 DEM 的泥石流流域纵比降的快速计算方法[J]. 2018(09): 238-239.

This plugin is an independent software implementation and extension; the paper is cited as a methodological reference.

## Outputs

- Main-channel vector
- Automatically delineated watershed polygons in outlet-point mode
- CSV statistics
- Vector output formats: GeoPackage, Shapefile, GeoJSON

Vector result fields use concise Chinese names for practical GIS work: 流域号、面积、沟顶高、沟口高、高差、沟长、纵比降、汇流数.

## Requirements

- QGIS 3.28–3.x
- No additional third-party Python package installation is required beyond the libraries shipped with standard QGIS distributions.

## Installation

### QGIS Plugin Repository

After approval, search for **DEM Debris Flow Gradient** in **Plugins → Manage and Install Plugins**.

### ZIP installation

Download the official release ZIP and use **Plugins → Manage and Install Plugins → Install from ZIP**.

> Use the release package `DEM_DebrisFlow_Gradient_v1.0.0.zip`. GitHub's **Code → Download ZIP** is a source archive and is not the QGIS installation package.

## Usage notes

- Use a projected CRS with metre-based units when calculating channel lengths and search distances.
- In outlet-point mode, place each point near the actual debris-flow channel outlet and use a unique ID field.
- Review automatically delineated watersheds and main channels against terrain, imagery and known drainage conditions.
- Results are analytical aids and should not replace professional engineering or hazard-assessment judgment.

## License

GPL-2.0-or-later.

## Author

Zhang Y.H.  
Email: zhangyhcumt@163.com
