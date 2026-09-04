# -*- coding: utf-8 -*-
import os

from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .dialog import DemGradientDialog


class DemDebrisFlowGradientPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def tr(self, text):
        return QCoreApplication.translate('DemDebrisFlowGradientPlugin', text)

    def initGui(self):
        self.action = QAction(
            QIcon(os.path.join(os.path.dirname(__file__), 'icon.png')),
            self.tr('DEM泥石流纵比降计算'),
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToRasterMenu(self.tr('DEM泥石流分析'), self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginRasterMenu(self.tr('DEM泥石流分析'), self.action)
            self.iface.removeToolBarIcon(self.action)

    def run(self):
        if self.dialog is None:
            self.dialog = DemGradientDialog(self.iface)
        self.dialog.refresh_layers()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
