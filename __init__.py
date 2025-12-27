# -*- coding: utf-8 -*-
"""
QGIS Plugin entry point for Edit Tracking Tools
"""

from .edit_tracking_tools import EditTrackingToolsPlugin


def classFactory(iface):
    """
    QGIS calls this function to create an instance of the plugin.
    :param iface: A QGIS interface instance.
    """
    return EditTrackingToolsPlugin(iface)
