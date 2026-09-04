def classFactory(iface):
    from .plugin import DemDebrisFlowGradientPlugin
    return DemDebrisFlowGradientPlugin(iface)
