# -*- coding: utf-8 -*-
"""
/***************************************************************************
 NetCDFBrowser
                                 A QGIS plugin
 allows to browse multi-variable and multi-dimensional netCDF files
                             -------------------
        begin                : 2013-01-28
        copyright            : (C) 2013 by Etienne Tourigny
        email                : etourigny.dev at gmail dot com
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
 This script initializes the plugin, making it known to QGIS.
"""


def name():
    return "NetCDF Browser"


def description():
    return "allows to browse multi-variable and multi-dimensional netCDF files, requires GDAL >= 1.10"


def version():
    return "Version 0.1"


def icon():
    return "icon.png"


def qgisMinimumVersion():
    return "1.8"

def author():
    return "Etienne Tourigny"

def email():
    return "etourigny.dev at gmail dot com"

def classFactory(iface):
    # load NetCDFBrowser class from file NetCDFBrowser
    from netcdfbrowser import NetCDFBrowser
    return NetCDFBrowser(iface)
