# DEM Debris Flow Gradient for QGIS

![QGIS](https://img.shields.io/badge/QGIS-3.x-589632?logo=qgis&logoColor=white)
![language](https://img.shields.io/badge/language-Python-3776AB?logo=python&logoColor=white)
![release](https://img.shields.io/badge/release-v1.0.0-2563EB)
![License](https://img.shields.io/badge/License-GPL--2.0--or--later-2E7D32)

**English | [简体中文](README_CN.md)**

A QGIS plugin for rapid calculation of debris-flow main-channel longitudinal gradient from DEM data.

## Features

The plugin provides two workflows:

1. **DEM + watershed polygons** — uses existing debris-flow watershed boundaries as independent calculation units.
2. **DEM + outlet points** — snaps outlet points to nearby high-flow-accumulation cells, automatically delineates watersheds, traces the main channel, and calculates longitudinal gradient.

Core workflow:

`DEM → depression filling → D8 flow direction → flow accumulation → outlet determination/snapping → watershed extraction → main-channel tracing → elevation difference → channel length → longitudinal gradient`

The longitudinal gradient is calculated as:

`Gradient (‰) = (top elevation - outlet elevation) / main-channel length × 1000`

## Method basis and reference

The overall technical idea refers to the paper by Zhang Su, *Rapid Calculation Method of Debris-Flow Watershed Longitudinal Gradient Based on DEM* (2018, no. 9, pp. 238–239). The paper uses DEM-based hydrological analysis to extract the debris-flow main channel and calculates longitudinal gradient from elevation difference and channel length.

The original paper assumes that debris-flow watershed boundaries are already available. Accordingly, the **DEM + watershed polygons** workflow follows the same general idea. This plugin further extends the workflow with a **DEM + outlet points** mode that automatically delineates watersheds when no watershed polygon data are available.

This plugin is an independent software implementation and extension; the paper is cited as a methodological reference.

## Outputs

- Main-channel vector
- Automatically delineated watershed polygons in outlet-point mode
- CSV statistics
- Vector output formats: GeoPackage, Shapefile, GeoJSON

Result attribute fields use concise Chinese labels in the current interface for practical GIS workflows.

## Requirements

- QGIS 3.28–3.x
- No additional third-party Python package installation is required beyond the libraries shipped with standard QGIS distributions.

## Installation

### QGIS Plugin Repository

After approval, search for **DEM Debris Flow Gradient** in **Plugins → Manage and Install Plugins**.

### ZIP installation

Download the official release ZIP and use **Plugins → Manage and Install Plugins → Install from ZIP**.

> Use the official release package `DEM_DebrisFlow_Gradient_v1.0.0.zip`. GitHub's **Code → Download ZIP** archive is not the QGIS installation package.

## Usage notes

- Use a projected CRS with metre-based units when calculating channel lengths and search distances.
- In outlet-point mode, place each point near the actual debris-flow channel outlet and use a unique ID field.
- Review automatically delineated watersheds and main channels against terrain, imagery and known drainage conditions.
- Results are analytical aids and should not replace professional engineering or hazard-assessment judgment.

## Follow and connect

<table>
  <tr>
    <th width="50%">WeChat Official Account</th>
    <th width="50%">Knowledge Planet</th>
  </tr>
  <tr>
    <td align="center" valign="middle"><a href="https://raw.githubusercontent.com/zhangyhrs/SHP2KMZ_Tool/main/assets/wechat-official-account.png"><img src="https://raw.githubusercontent.com/zhangyhrs/SHP2KMZ_Tool/main/assets/wechat-official-account.png" alt="WeChat Official Account" height="150"></a></td>
    <td align="center" valign="middle"><a href="https://raw.githubusercontent.com/zhangyhrs/SHP2KMZ_Tool/main/assets/knowledge-planet.jpg"><img src="https://raw.githubusercontent.com/zhangyhrs/SHP2KMZ_Tool/main/assets/knowledge-planet.jpg" alt="Knowledge Planet" height="150"></a></td>
  </tr>
</table>

## License

GPL-2.0-or-later.

## Author

Zhang Y.H.  
Email: zhangyhcumt@163.com
