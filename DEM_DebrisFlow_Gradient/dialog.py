# -*- coding: utf-8 -*-
import csv
import math
import os
import traceback

import numpy as np
from osgeo import gdal, ogr, osr

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QGridLayout, QLabel, QComboBox, QPushButton,
    QFileDialog, QLineEdit, QDoubleSpinBox, QSpinBox, QProgressBar,
    QMessageBox, QDialogButtonBox, QGroupBox, QPlainTextEdit, QApplication
)
from qgis.core import (
    QgsProject, QgsMapLayerType, QgsWkbTypes, QgsCoordinateTransform,
    QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY,
    QgsFields, QgsField, QgsVectorFileWriter, QgsCoordinateTransformContext,
    QgsVectorLayer, QgsRectangle
)

from .hydrology import (
    priority_flood_fill, d8_flow_direction, flow_accumulation,
    choose_outlet, trace_main_channel, snap_outlet_to_max_acc,
    watershed_from_outlet
)


def _invert_gt(gt):
    inv = gdal.InvGeoTransform(gt)
    if inv is None:
        raise RuntimeError('无法计算DEM仿射变换逆矩阵。')
    return inv


def _world_to_pixel(inv_gt, x, y):
    px, py = gdal.ApplyGeoTransform(inv_gt, x, y)
    return int(math.floor(px)), int(math.floor(py))


def _pixel_center(gt, col, row):
    x, y = gdal.ApplyGeoTransform(gt, col + 0.5, row + 0.5)
    return float(x), float(y)


def _window_gt(gt, xoff, yoff):
    x0, y0 = gdal.ApplyGeoTransform(gt, xoff, yoff)
    return (x0, gt[1], gt[2], y0, gt[4], gt[5])


def _polygonize_mask(mask, gt, wkt):
    """把布尔流域掩膜转为QgsGeometry。"""
    rows, cols = mask.shape
    mem_drv = gdal.GetDriverByName('MEM')
    rds = mem_drv.Create('', cols, rows, 1, gdal.GDT_Byte)
    rds.SetGeoTransform(gt)
    rds.SetProjection(wkt or '')
    rb = rds.GetRasterBand(1)
    rb.WriteArray(mask.astype(np.uint8))
    rb.SetNoDataValue(0)

    vdrv = ogr.GetDriverByName('Memory')
    vds = vdrv.CreateDataSource('')
    srs = osr.SpatialReference()
    if wkt:
        srs.ImportFromWkt(wkt)
    lyr = vds.CreateLayer('basin', srs=srs, geom_type=ogr.wkbPolygon)
    lyr.CreateField(ogr.FieldDefn('DN', ogr.OFTInteger))
    gdal.Polygonize(rb, rb, lyr, 0, [], callback=None)

    geoms = []
    for f in lyr:
        if f.GetField('DN') == 1 and f.GetGeometryRef() is not None:
            geoms.append(f.GetGeometryRef().Clone())
    if not geoms:
        return QgsGeometry()
    merged = geoms[0]
    for g in geoms[1:]:
        u = merged.Union(g)
        if u is not None:
            merged = u
    return QgsGeometry.fromWkt(merged.ExportToWkt())


class DemGradientDialog(QDialog):
    MODE_BASIN = 0
    MODE_OUTLET = 1

    def __init__(self, iface):
        super().__init__(iface.mainWindow())
        self.iface = iface
        self.setWindowTitle('DEM泥石流纵比降计算 v1.0.1')
        self.resize(790, 690)
        self._build_ui()
        self.refresh_layers()

    def _build_ui(self):
        root = QVBoxLayout(self)

        mbox = QGroupBox('计算方式')
        mgrid = QGridLayout(mbox)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem('方式一：已有泥石流流域面', self.MODE_BASIN)
        self.mode_combo.addItem('方式二：沟口点自动划分流域', self.MODE_OUTLET)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        mgrid.addWidget(QLabel('计算模式：'), 0, 0)
        mgrid.addWidget(self.mode_combo, 0, 1, 1, 3)
        root.addWidget(mbox)

        box = QGroupBox('输入数据')
        grid = QGridLayout(box)
        self.dem_combo = QComboBox()
        self.basin_combo = QComboBox()
        self.basin_id_combo = QComboBox()
        self.outlet_combo = QComboBox()
        self.outlet_id_combo = QComboBox()
        self.basin_combo.currentIndexChanged.connect(self._refresh_basin_fields)
        self.outlet_combo.currentIndexChanged.connect(self._refresh_outlet_fields)

        self.dem_browse_btn = QPushButton('浏览…')
        self.basin_browse_btn = QPushButton('浏览…')
        self.outlet_browse_btn = QPushButton('浏览…')
        self.dem_browse_btn.clicked.connect(self._browse_dem)
        self.basin_browse_btn.clicked.connect(self._browse_basin)
        self.outlet_browse_btn.clicked.connect(self._browse_outlet)

        grid.addWidget(QLabel('DEM栅格：'), 0, 0)
        grid.addWidget(self.dem_combo, 0, 1, 1, 2)
        grid.addWidget(self.dem_browse_btn, 0, 3)
        self.basin_label = QLabel('泥石流流域面：')
        grid.addWidget(self.basin_label, 1, 0)
        grid.addWidget(self.basin_combo, 1, 1, 1, 2)
        grid.addWidget(self.basin_browse_btn, 1, 3)
        self.basin_id_label = QLabel('流域编号字段：')
        grid.addWidget(self.basin_id_label, 2, 0)
        grid.addWidget(self.basin_id_combo, 2, 1, 1, 3)
        self.outlet_label = QLabel('泥石流沟口点：')
        grid.addWidget(self.outlet_label, 3, 0)
        grid.addWidget(self.outlet_combo, 3, 1, 1, 2)
        grid.addWidget(self.outlet_browse_btn, 3, 3)
        self.outlet_id_label = QLabel('沟口编号字段：')
        grid.addWidget(self.outlet_id_label, 4, 0)
        grid.addWidget(self.outlet_id_combo, 4, 1, 1, 3)
        root.addWidget(box)

        pbox = QGroupBox('计算参数')
        pgrid = QGridLayout(pbox)
        self.min_area = QDoubleSpinBox()
        self.min_area.setDecimals(4)
        self.min_area.setRange(0.0, 1000000.0)
        self.min_area.setValue(0.01)
        self.min_area.setSuffix(' km²')
        self.min_area.setToolTip('主沟道反向追踪时的最小汇流面积阈值；0表示不限制。')
        pgrid.addWidget(QLabel('最小汇流面积：'), 0, 0)
        pgrid.addWidget(self.min_area, 0, 1)

        self.search_radius = QDoubleSpinBox()
        self.search_radius.setDecimals(1)
        self.search_radius.setRange(0.5, 500.0)
        self.search_radius.setValue(20.0)
        self.search_radius.setSuffix(' km')
        self.search_radius.setToolTip('方式二中，以沟口点为中心读取DEM的最大搜索半径。流域触及窗口边缘时应增大该值。')
        self.search_label = QLabel('流域搜索半径：')
        pgrid.addWidget(self.search_label, 1, 0)
        pgrid.addWidget(self.search_radius, 1, 1)

        self.snap_cells = QSpinBox()
        self.snap_cells.setRange(0, 100)
        self.snap_cells.setValue(5)
        self.snap_cells.setSuffix(' 像元')
        self.snap_cells.setToolTip('方式二中，将输入沟口点吸附到附近汇流累积量最大的像元。')
        self.snap_label = QLabel('沟口吸附半径：')
        pgrid.addWidget(self.snap_label, 1, 2)
        pgrid.addWidget(self.snap_cells, 1, 3)
        root.addWidget(pbox)

        obox = QGroupBox('输出')
        ogrid = QGridLayout(obox)
        self.output_format = QComboBox()
        self.output_format.addItem('GeoPackage (*.gpkg)', 'gpkg')
        self.output_format.addItem('Shapefile (*.shp)', 'shp')
        self.output_format.addItem('GeoJSON (*.geojson)', 'geojson')
        self.output_format.currentIndexChanged.connect(self._output_format_changed)
        ogrid.addWidget(QLabel('输出格式：'), 0, 0)
        ogrid.addWidget(self.output_format, 0, 1, 1, 2)
        self.line_edit = QLineEdit()
        self.basin_out_edit = QLineEdit()
        self.csv_edit = QLineEdit()
        b1 = QPushButton('浏览…')
        b2 = QPushButton('浏览…')
        b3 = QPushButton('浏览…')
        b1.clicked.connect(self._pick_line)
        b2.clicked.connect(self._pick_basin)
        b3.clicked.connect(self._pick_csv)
        ogrid.addWidget(QLabel('主沟道：'), 1, 0)
        ogrid.addWidget(self.line_edit, 1, 1)
        ogrid.addWidget(b1, 1, 2)
        self.basin_out_label = QLabel('自动流域面：')
        ogrid.addWidget(self.basin_out_label, 2, 0)
        ogrid.addWidget(self.basin_out_edit, 2, 1)
        self.basin_out_btn = b2
        ogrid.addWidget(b2, 2, 2)
        ogrid.addWidget(QLabel('统计CSV：'), 3, 0)
        ogrid.addWidget(self.csv_edit, 3, 1)
        ogrid.addWidget(b3, 3, 2)
        root.addWidget(obox)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText('运行日志…')
        root.addWidget(self.log, 1)

        buttons = QDialogButtonBox()
        self.run_btn = buttons.addButton('开始计算', QDialogButtonBox.ButtonRole.AcceptRole)
        close_btn = buttons.addButton('关闭', QDialogButtonBox.ButtonRole.RejectRole)
        self.run_btn.clicked.connect(self.run_analysis)
        close_btn.clicked.connect(self.reject)
        root.addWidget(buttons)
        self._mode_changed()

    def _mode_changed(self):
        is_basin = self.mode_combo.currentData() == self.MODE_BASIN
        for w in (self.basin_label, self.basin_combo, self.basin_browse_btn, self.basin_id_label, self.basin_id_combo):
            w.setEnabled(is_basin)
        for w in (self.outlet_label, self.outlet_combo, self.outlet_browse_btn, self.outlet_id_label, self.outlet_id_combo,
                  self.search_label, self.search_radius, self.snap_label, self.snap_cells,
                  self.basin_out_label, self.basin_out_edit, self.basin_out_btn):
            w.setEnabled(not is_basin)

    def refresh_layers(self):
        self.dem_combo.clear(); self.basin_combo.clear(); self.outlet_combo.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.type() == QgsMapLayerType.RasterLayer:
                self.dem_combo.addItem(lyr.name(), lyr.id())
            elif lyr.type() == QgsMapLayerType.VectorLayer:
                gt = QgsWkbTypes.geometryType(lyr.wkbType())
                if gt == QgsWkbTypes.GeometryType.PolygonGeometry:
                    self.basin_combo.addItem(lyr.name(), lyr.id())
                elif gt == QgsWkbTypes.GeometryType.PointGeometry:
                    self.outlet_combo.addItem(lyr.name(), lyr.id())
        self._refresh_basin_fields(); self._refresh_outlet_fields(); self._mode_changed()

    def _refresh_basin_fields(self):
        self.basin_id_combo.clear()
        lyr = QgsProject.instance().mapLayer(self.basin_combo.currentData())
        if lyr:
            for f in lyr.fields(): self.basin_id_combo.addItem(f.name())

    def _refresh_outlet_fields(self):
        self.outlet_id_combo.clear()
        lyr = QgsProject.instance().mapLayer(self.outlet_combo.currentData())
        if lyr:
            for f in lyr.fields(): self.outlet_id_combo.addItem(f.name())


    def _select_combo_layer(self, combo, layer_id):
        idx = combo.findData(layer_id)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _browse_dem(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择DEM栅格', '',
            '栅格数据 (*.tif *.tiff *.img *.vrt *.asc);;所有文件 (*.*)'
        )
        if not path:
            return
        from qgis.core import QgsRasterLayer
        lyr = QgsRasterLayer(path, os.path.splitext(os.path.basename(path))[0])
        if not lyr.isValid():
            QMessageBox.warning(self, '输入无效', '无法加载所选DEM栅格。')
            return
        QgsProject.instance().addMapLayer(lyr)
        self.refresh_layers()
        self._select_combo_layer(self.dem_combo, lyr.id())

    def _browse_basin(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择泥石流流域面', '',
            '矢量数据 (*.shp *.gpkg *.geojson);;Shapefile (*.shp);;GeoPackage (*.gpkg);;所有文件 (*.*)'
        )
        if not path:
            return
        lyr = QgsVectorLayer(path, os.path.splitext(os.path.basename(path))[0], 'ogr')
        if (not lyr.isValid() or
                QgsWkbTypes.geometryType(lyr.wkbType()) != QgsWkbTypes.GeometryType.PolygonGeometry):
            QMessageBox.warning(self, '输入无效', '所选文件必须是面矢量图层。')
            return
        QgsProject.instance().addMapLayer(lyr)
        self.refresh_layers()
        self._select_combo_layer(self.basin_combo, lyr.id())
        self._refresh_basin_fields()

    def _browse_outlet(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择泥石流沟口点', '',
            '矢量数据 (*.shp *.gpkg *.geojson);;Shapefile (*.shp);;GeoPackage (*.gpkg);;所有文件 (*.*)'
        )
        if not path:
            return
        lyr = QgsVectorLayer(path, os.path.splitext(os.path.basename(path))[0], 'ogr')
        if (not lyr.isValid() or
                QgsWkbTypes.geometryType(lyr.wkbType()) != QgsWkbTypes.GeometryType.PointGeometry):
            QMessageBox.warning(self, '输入无效', '所选文件必须是点矢量图层（Point/MultiPoint）。')
            return
        QgsProject.instance().addMapLayer(lyr)
        self.refresh_layers()
        self._select_combo_layer(self.outlet_combo, lyr.id())
        self._refresh_outlet_fields()

    def _vector_ext(self):
        return {'gpkg': '.gpkg', 'shp': '.shp', 'geojson': '.geojson'}[self.output_format.currentData()]

    def _vector_filter(self):
        key = self.output_format.currentData()
        return {
            'gpkg': 'GeoPackage (*.gpkg)',
            'shp': 'Shapefile (*.shp)',
            'geojson': 'GeoJSON (*.geojson)',
        }[key]

    def _replace_ext(self, path):
        if not path:
            return path
        return os.path.splitext(path)[0] + self._vector_ext()

    def _output_format_changed(self):
        if self.line_edit.text().strip():
            self.line_edit.setText(self._replace_ext(self.line_edit.text().strip()))
        if self.basin_out_edit.text().strip():
            self.basin_out_edit.setText(self._replace_ext(self.basin_out_edit.text().strip()))

    def _pick_line(self):
        path, _ = QFileDialog.getSaveFileName(self, '输出主沟道', '', self._vector_filter())
        if path:
            ext = self._vector_ext()
            if not path.lower().endswith(ext): path = os.path.splitext(path)[0] + ext
            self.line_edit.setText(path)
            base = os.path.splitext(path)[0]
            if not self.csv_edit.text(): self.csv_edit.setText(base + '_statistics.csv')
            if not self.basin_out_edit.text(): self.basin_out_edit.setText(base + '_basins' + ext)

    def _pick_basin(self):
        path, _ = QFileDialog.getSaveFileName(self, '输出自动划分流域面', '', self._vector_filter())
        if path:
            ext = self._vector_ext()
            if not path.lower().endswith(ext): path = os.path.splitext(path)[0] + ext
            self.basin_out_edit.setText(path)

    def _pick_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, '输出统计表', '', 'CSV (*.csv)')
        if path:
            if not path.lower().endswith('.csv'): path += '.csv'
            self.csv_edit.setText(path)

    def _msg(self, text):
        self.log.appendPlainText(text)
        self.iface.mainWindow().statusBar().showMessage(text)

    def run_analysis(self):
        try:
            self._run_analysis()
        except Exception as e:
            self._msg('错误：' + str(e)); self._msg(traceback.format_exc())
            QMessageBox.critical(self, '计算失败', str(e))
        finally:
            self.run_btn.setEnabled(True)

    def _open_dem(self):
        dem_layer = QgsProject.instance().mapLayer(self.dem_combo.currentData())
        if not dem_layer: raise RuntimeError('请选择DEM栅格。')
        ds = gdal.Open(dem_layer.source().split('|')[0], gdal.GA_ReadOnly)
        if ds is None: raise RuntimeError('无法打开DEM数据。')
        gt = ds.GetGeoTransform()
        if abs(gt[2]) > 1e-12 or abs(gt[4]) > 1e-12:
            raise RuntimeError('暂不支持旋转DEM，请先另存为北向上的规则栅格。')
        crs = QgsCoordinateReferenceSystem(); crs.createFromWkt(ds.GetProjection())
        if not crs.isValid(): crs = dem_layer.crs()
        return dem_layer, ds, ds.GetRasterBand(1), gt, _invert_gt(gt), ds.GetProjection(), crs

    def _make_writer(self, path, fields, geom_type, crs, layer_name):
        opts = QgsVectorFileWriter.SaveVectorOptions()
        low = path.lower()
        if low.endswith('.gpkg'):
            opts.driverName = 'GPKG'
        elif low.endswith('.geojson') or low.endswith('.json'):
            opts.driverName = 'GeoJSON'
        else:
            opts.driverName = 'ESRI Shapefile'
        opts.fileEncoding = 'UTF-8'
        if opts.driverName == 'GPKG': opts.layerName = layer_name
        w = QgsVectorFileWriter.create(path, fields, geom_type, crs, QgsCoordinateTransformContext(), opts)
        if w.hasError() != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError('无法创建输出：' + w.errorMessage())
        return w

    def _fields(self):
        # 采用简短中文字段名，兼顾 Shapefile DBF 字段名长度限制。
        f = QgsFields()
        f.append(QgsField('流域号', QVariant.String, len=80))
        f.append(QgsField('面积', QVariant.Double, len=20, prec=6))       # km²
        f.append(QgsField('沟顶高', QVariant.Double, len=20, prec=3))     # m
        f.append(QgsField('沟口高', QVariant.Double, len=20, prec=3))     # m
        f.append(QgsField('高差', QVariant.Double, len=20, prec=3))       # m
        f.append(QgsField('沟长', QVariant.Double, len=20, prec=3))       # m
        f.append(QgsField('纵比降', QVariant.Double, len=20, prec=3))     # ‰
        f.append(QgsField('汇流数', QVariant.Double, len=20, prec=3))     # 像元数
        return f

    def _run_analysis(self):
        mode = self.mode_combo.currentData()
        out_line = self.line_edit.text().strip(); out_csv = self.csv_edit.text().strip()
        if not out_line or not out_csv: raise RuntimeError('请设置主沟道和统计表输出路径。')
        if mode == self.MODE_OUTLET and not self.basin_out_edit.text().strip():
            raise RuntimeError('方式二请设置自动流域面输出路径。')

        self.run_btn.setEnabled(False); self.log.clear(); self.progress.setValue(0)
        dem_layer, ds, band, gt, inv_gt, dem_wkt, dem_crs = self._open_dem()
        nodata = band.GetNoDataValue()
        fields = self._fields()
        line_writer = self._make_writer(out_line, fields, QgsWkbTypes.Type.LineString, dem_crs, 'main_channel')
        basin_writer = None
        if mode == self.MODE_OUTLET:
            basin_writer = self._make_writer(self.basin_out_edit.text().strip(), fields, QgsWkbTypes.Type.MultiPolygon, dem_crs, 'auto_basins')

        cf = open(out_csv, 'w', newline='', encoding='utf-8-sig')
        cw = csv.writer(cf)
        cw.writerow(['流域编号','流域面积_km2','沟顶高程_m','沟口高程_m','相对高差_m','主沟长度_m','纵比降_‰','沟口汇流像元数','模式'])

        if mode == self.MODE_BASIN:
            success, total = self._run_by_basins(ds, band, gt, inv_gt, dem_wkt, dem_crs, nodata, fields, line_writer, cw)
        else:
            success, total = self._run_by_outlets(ds, band, gt, inv_gt, dem_wkt, dem_crs, nodata, fields, line_writer, basin_writer, cw)

        del line_writer
        if basin_writer is not None: del basin_writer
        cf.close(); ds = None
        self.progress.setValue(100)
        if os.path.exists(out_line):
            v = QgsVectorLayer(out_line, '泥石流主沟道_纵比降', 'ogr')
            if v.isValid(): QgsProject.instance().addMapLayer(v)
        if mode == self.MODE_OUTLET and os.path.exists(self.basin_out_edit.text().strip()):
            v = QgsVectorLayer(self.basin_out_edit.text().strip(), '自动划分泥石流流域', 'ogr')
            if v.isValid(): QgsProject.instance().addMapLayer(v)
        self._msg(f'全部完成：成功 {success}/{total} 条。')
        QMessageBox.information(self, '完成', f'处理完成。\n成功：{success}/{total}\n\n主沟道：{out_line}\n统计表：{out_csv}')

    def _mask_from_geom(self, geom, ds, band, gt, inv_gt, dem_wkt, nodata):
        bbox = geom.boundingBox()
        c0,r0 = _world_to_pixel(inv_gt,bbox.xMinimum(),bbox.yMaximum())
        c1,r1 = _world_to_pixel(inv_gt,bbox.xMaximum(),bbox.yMinimum())
        xoff=max(0,min(c0,c1)-2); yoff=max(0,min(r0,r1)-2)
        xend=min(ds.RasterXSize-1,max(c0,c1)+2); yend=min(ds.RasterYSize-1,max(r0,r1)+2)
        xsize=xend-xoff+1; ysize=yend-yoff+1
        if xsize<=2 or ysize<=2: return None
        dem=band.ReadAsArray(xoff,yoff,xsize,ysize)
        if dem is None: return None
        dem=dem.astype(np.float64); wgt=_window_gt(gt,xoff,yoff)
        mds=gdal.GetDriverByName('MEM').Create('',xsize,ysize,1,gdal.GDT_Byte)
        mds.SetGeoTransform(wgt); mds.SetProjection(dem_wkt or ''); mb=mds.GetRasterBand(1); mb.Fill(0)
        vds=ogr.GetDriverByName('Memory').CreateDataSource(''); srs=osr.SpatialReference()
        if dem_wkt: srs.ImportFromWkt(dem_wkt)
        vl=vds.CreateLayer('basin',srs=srs,geom_type=ogr.wkbUnknown)
        of=ogr.Feature(vl.GetLayerDefn()); of.SetGeometry(ogr.CreateGeometryFromWkt(geom.asWkt())); vl.CreateFeature(of)
        gdal.RasterizeLayer(mds,[1],vl,burn_values=[1],options=['ALL_TOUCHED=TRUE'])
        mask=mb.ReadAsArray().astype(bool)
        if nodata is not None: mask &= ~np.isclose(dem,nodata)
        mask &= np.isfinite(dem)
        return dem, mask, wgt, xoff, yoff

    def _pixel_area_m2(self, crs, gt, center_xy=None):
        if not crs.isGeographic():
            return abs(gt[1]*gt[5])
        if center_xy is None: return 1.0
        x,y=center_xy
        rect=QgsRectangle(x-abs(gt[1])/2,y-abs(gt[5])/2,x+abs(gt[1])/2,y+abs(gt[5])/2)
        return max(1.0,self._distance_area(crs).measureArea(QgsGeometry.fromRect(rect)))

    def _compute_result(self, basin_id, dem, mask, wgt, gt, crs, fields, line_writer, cw, basin_geom=None, forced_outlet=None):
        if mask.sum()<3: return False, None
        filled=priority_flood_fill(dem,mask)
        downstream=d8_flow_direction(filled,mask,gt[1],gt[5])
        acc=flow_accumulation(downstream,mask)
        outlet=forced_outlet if forced_outlet is not None else choose_outlet(mask,acc,filled)
        if outlet is None: return False, None
        pix_area=self._pixel_area_m2(crs,wgt,_pixel_center(wgt,outlet[1],outlet[0]))
        min_cells=max(1.0,float(self.min_area.value())*1e6/pix_area) if self.min_area.value()>0 else 1.0
        path=trace_main_channel(mask,downstream,acc,outlet,min_cells)
        if len(path)<2: return False, None
        pts=[]; elev=[]
        for r,c in reversed(path):
            x,y=_pixel_center(wgt,c,r); pts.append(QgsPointXY(x,y)); elev.append(float(dem[r,c]))
        line=QgsGeometry.fromPolylineXY(pts); length=self._measure_length(line,crs)
        if length<=0: return False, None
        top=max(elev); out=min(elev); relief=top-out; grad=relief/length*1000.0
        area_km2 = (float(mask.sum())*pix_area)/1e6 if basin_geom is None else self._measure_area_km2(basin_geom,crs)
        attrs=[str(basin_id),area_km2,top,out,relief,length,grad,float(acc[outlet[0],outlet[1]])]
        f=QgsFeature(fields); f.setGeometry(line); f.setAttributes(attrs); line_writer.addFeature(f)
        cw.writerow([str(basin_id),f'{area_km2:.6f}',f'{top:.3f}',f'{out:.3f}',f'{relief:.3f}',f'{length:.3f}',f'{grad:.3f}',f'{acc[outlet[0],outlet[1]]:.3f}', '沟口点自动划分' if basin_geom is None else '已有流域面'])
        return True, (attrs, outlet, downstream, acc)

    def _run_by_basins(self, ds, band, gt, inv_gt, dem_wkt, crs, nodata, fields, line_writer, cw):
        lyr=QgsProject.instance().mapLayer(self.basin_combo.currentData()); idf=self.basin_id_combo.currentText()
        if not lyr or not idf: raise RuntimeError('请选择泥石流流域面及编号字段。')
        xform=QgsCoordinateTransform(lyr.crs(),crs,QgsProject.instance()) if lyr.crs()!=crs else None
        feats=list(lyr.getFeatures()); total=len(feats); success=0
        for i,feat in enumerate(feats,1):
            bid=str(feat[idf]); self._msg(f'[{i}/{total}] 流域面模式：{bid}')
            geom=QgsGeometry(feat.geometry())
            if xform: geom.transform(xform)
            if not geom.isGeosValid(): geom=geom.makeValid()
            data=self._mask_from_geom(geom,ds,band,gt,inv_gt,dem_wkt,nodata)
            if data:
                dem,mask,wgt,_,_=data
                ok,res=self._compute_result(bid,dem,mask,wgt,gt,crs,fields,line_writer,cw,basin_geom=geom)
                if ok:
                    success+=1; self._msg(f'  完成：纵比降={res[0][6]:.2f}‰')
                else: self._msg('  跳过：未形成有效主沟道。')
            self.progress.setValue(int(i/max(1,total)*100)); QApplication.processEvents()
        return success,total

    def _run_by_outlets(self, ds, band, gt, inv_gt, dem_wkt, crs, nodata, fields, line_writer, basin_writer, cw):
        lyr=QgsProject.instance().mapLayer(self.outlet_combo.currentData()); idf=self.outlet_id_combo.currentText()
        if not lyr or not idf: raise RuntimeError('请选择泥石流沟口点及编号字段。')
        xform=QgsCoordinateTransform(lyr.crs(),crs,QgsProject.instance()) if lyr.crs()!=crs else None
        feats=list(lyr.getFeatures()); total=len(feats); success=0
        radius_km=float(self.search_radius.value())
        for i,feat in enumerate(feats,1):
            bid=str(feat[idf]); self._msg(f'[{i}/{total}] 沟口点模式：{bid}')
            g=QgsGeometry(feat.geometry())
            if xform: g.transform(xform)
            p=g.asPoint(); x=float(p.x()); y=float(p.y())
            if crs.isGeographic():
                lat=max(-89.0,min(89.0,y)); dy=radius_km/111.32; dx=radius_km/(111.32*max(0.15,math.cos(math.radians(lat))))
            else:
                dx=dy=radius_km*1000.0
            c0,r0=_world_to_pixel(inv_gt,x-dx,y+dy); c1,r1=_world_to_pixel(inv_gt,x+dx,y-dy)
            xoff=max(0,min(c0,c1)); yoff=max(0,min(r0,r1)); xend=min(ds.RasterXSize-1,max(c0,c1)); yend=min(ds.RasterYSize-1,max(r0,r1))
            xs=xend-xoff+1; ys=yend-yoff+1
            if xs<3 or ys<3: self._msg('  跳过：搜索窗口超出DEM。'); continue
            dem=band.ReadAsArray(xoff,yoff,xs,ys)
            if dem is None: self._msg('  跳过：DEM读取失败。'); continue
            dem=dem.astype(np.float64); wgt=_window_gt(gt,xoff,yoff)
            mask=np.isfinite(dem)
            if nodata is not None: mask &= ~np.isclose(dem,nodata)
            filled=priority_flood_fill(dem,mask); downstream=d8_flow_direction(filled,mask,gt[1],gt[5]); acc=flow_accumulation(downstream,mask)
            pc,pr=_world_to_pixel(_invert_gt(wgt),x,y)
            if pr<0 or pr>=ys or pc<0 or pc>=xs: self._msg('  跳过：沟口点不在读取窗口内。'); continue
            outlet=snap_outlet_to_max_acc((pr,pc),acc,mask,int(self.snap_cells.value()))
            basin_mask=watershed_from_outlet(mask,downstream,outlet)
            if basin_mask.sum()<3: self._msg('  跳过：自动划分流域失败。'); continue
            touches = basin_mask[0,:].any() or basin_mask[-1,:].any() or basin_mask[:,0].any() or basin_mask[:,-1].any()
            if touches: self._msg('  警告：自动流域触及搜索窗口边缘，建议增大“流域搜索半径”后复核。')
            basin_geom=_polygonize_mask(basin_mask,wgt,dem_wkt)
            # 在已划分流域内重新计算，确保主沟道只使用该流域像元
            ok,res=self._compute_result(bid,dem,basin_mask,wgt,gt,crs,fields,line_writer,cw,basin_geom=None,forced_outlet=outlet)
            if ok:
                attrs=res[0]
                if not basin_geom.isEmpty():
                    if QgsWkbTypes.isSingleType(basin_geom.wkbType()): basin_geom.convertToMultiType()
                    bf=QgsFeature(fields); bf.setGeometry(basin_geom); bf.setAttributes(attrs); basin_writer.addFeature(bf)
                success+=1; self._msg(f'  完成：自动流域={attrs[1]:.4f} km²，纵比降={attrs[6]:.2f}‰')
            else: self._msg('  跳过：未形成有效主沟道。')
            self.progress.setValue(int(i/max(1,total)*100)); QApplication.processEvents()
        return success,total

    def _distance_area(self, crs):
        from qgis.core import QgsDistanceArea
        d=QgsDistanceArea(); d.setSourceCrs(crs,QgsProject.instance().transformContext())
        ell=QgsProject.instance().ellipsoid()
        if ell: d.setEllipsoid(ell)
        return d

    def _measure_length(self, geom, crs):
        if crs.isGeographic(): return self._distance_area(crs).measureLength(geom)
        return geom.length()

    def _measure_area_km2(self, geom, crs):
        if crs.isGeographic(): return self._distance_area(crs).measureArea(geom)/1e6
        return geom.area()/1e6
