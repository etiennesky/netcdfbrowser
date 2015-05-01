# -*- coding: utf-8 -*-
"""
/***************************************************************************
 NetCDFBrowserDialog
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
"""


from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from qgis.gui import QgsGenericProjectionSelector

from ui_netcdfbrowser import Ui_NetCDFBrowser

import re, math

from osgeo import gdal

debug = 0
_units = ['days','hours','minutes','seconds','day','hour','minute','second']

# import num2date from netcdftime if available
has_netcdftime = True
try:
    from netcdftime import num2date
    if debug > 0:
        print('using external netcdftime')
except ImportError:
    has_netcdftime = False

# try local netcdftime copy (netcdftime2.py)
if not has_netcdftime:
    has_netcdftime = True
    try:
        from netcdftime2 import num2date
        if debug > 0:
            print('using internal netcdftime')
    except ImportError:
        has_netcdftime = False

if debug > 0 and not has_netcdftime:
    print('did not find netcdftime')

# this menu don't hide when items are clicked
# http://stackoverflow.com/questions/2050462/prevent-a-qmenu-from-closing-when-one-of-its-qaction-is-triggered
class MyMenu(QMenu):

    def __init__(self):
        QMenu.__init__(self)
        self.ignoreHide = False

    def setVisible(self,visible):
        if self.ignoreHide:
            self.ignoreHide = False
            return
        QWidget.setVisible(self,visible)

    def mouseReleaseEvent(self,event):
        action = self.actionAt(event.pos())
        if action is not None:
            #if (actions_with_showed_menu.contains (action))
            self.ignoreHide = True
        QMenu.mouseReleaseEvent(self,event)


def num(s):
    try:
        return int(s)
    except ValueError:
        return float(s)


class NetCDFBrowserDialog(QDialog):
    def __init__(self, iface):

        self.iface = iface
        self.prefix = ''
        self.variables = None
        self.dim_names = []
        self.dim_values = dict()
        self.dim_values2 = dict()
        self.dim_def = dict()
        self.dim_band = dict()
        self.dim1Count=0
        self.dim2Count=0
        self.layerCrs = QgsCoordinateReferenceSystem()
        self.selectedCrs = QgsCoordinateReferenceSystem()

        QDialog.__init__(self)
        # Set up the user interface from Designer.
        self.ui = Ui_NetCDFBrowser()
        self.ui.setupUi(self)

        self.ui.cboCrs.clear()
        self.ui.cboCrs.insertItem(0, self.tr("Layer (None)"))
        self.ui.cboCrs.insertItem(1, self.tr("Project (None)"))
        self.ui.cboCrs.insertItem(2, self.tr("Selected (None)"))

        QObject.connect(self.ui.cboVars, SIGNAL("currentIndexChanged(QString)"), self.updateVariable)   


    def exec_(self):
        self.on_pbnFileName_pressed()
        QDialog.exec_(self)


    def on_pbnFileName_pressed(self):
        fileName = QFileDialog.getOpenFileName(self, self.tr("Open File"), "",
                   self.tr("netCDF Files (*.nc *.cdf *.nc2 *.nc4)"));
        if fileName is not None:
            self.ui.leFileName.setText( fileName )
            self.updateFile()


    # TODO add a addLayers() function
    def addLayer(self,fileName,var,band):
        if debug>0:
            print('addLayer(%s,%s,%s)' % (fileName,var,band))

        uri = 'NETCDF:"%s":%s' % (fileName, var)
        #name = 'NETCDF:"%s":%s#%d' % (QFileInfo(fileName).fileName(), var, band)
        name = '%s_var=%s' % (QFileInfo(fileName).fileName(), var) if var else QFileInfo(fileName).fileName()
        if band:
            band = int(band)
            if len(self.dim_names) >= 1:
                values2 = self.dim_values2[self.dim_names[0]] if self.dim_names[0] in self.dim_values2 else None
                if values2 and len(values2) >= self.dim_band[band][0] :
                    tmp = str(values2[self.dim_band[band][0]-1])
                else:
                    tmp = str(self.dim_band[band][0]).zfill(int(math.ceil(math.log(self.dim_def[self.dim_names[0]][0],10))))
                name = "%s_%s=%s" % (name,self.dim_names[0],tmp)
            if len(self.dim_names) >= 2 :
                values2 = self.dim_values2[self.dim_names[1]] if self.dim_names[1] in self.dim_values2 else None
                if values2 and len(values2) >= self.dim_band[band][1] :
                    tmp = str(values2[self.dim_band[band][1]-1])
                else:
                    tmp = str(self.dim_band[band][1]).zfill(int(math.ceil(math.log(self.dim_def[self.dim_names[1]][0],10))))
                name = "%s_%s=%s" % (name,self.dim_names[1],tmp)
            num_bands = max(self.dim1Count,1) * max(self.dim1Count,1)
            tmp = str(band).zfill(int(math.ceil(math.log(num_bands,10))))
            name = '%s_band=%s' % (name, tmp)

        # temporarily override /Projections/defaultBehaviour to avoid dialog prompt
        # this is taken from qgsbrowserdockwidget.cpp
        # TODO - integrate this into qgis core
        if self.ui.cboCrs.currentIndex() != 0:
            settings = QSettings()
            defaultProjectionOption = settings.value( "/Projections/defaultBehaviour", "prompt" )
            if defaultProjectionOption == "prompt":
                settings.setValue( "/Projections/defaultBehaviour", "useProject" )

        rlayer = QgsRasterLayer( uri, name )
        if rlayer is None or not rlayer.isValid():
            print('NetCDF Browser Plugin : raster %s failed to load' % uri)
            return

        # restore /Projections/defaultBehaviour
        if self.ui.cboCrs.currentIndex() != 0:
            if defaultProjectionOption == "prompt":
                settings.setValue( "/Projections/defaultBehaviour", defaultProjectionOption );

        if debug>0:
            print('created layer')

        # set layer CRS
        if self.ui.cboCrs.currentIndex() == 1:
            # this has changed in 2.4 ... 
            rlayer.setCrs( self.iface.mapCanvas().mapRenderer().destinationCrs() )
        elif self.ui.cboCrs.currentIndex() == 2:
            rlayer.setCrs( self.selectedCrs )

        #rtype = self.ui.cboRenderer.currentIndex() == 0:
        rtype = 0
        # set rendering to gray so only selected band is shown
        if rtype == 0 and band:
            rlayer.setDrawingStyle("SingleBandGray")
            renderer = rlayer.renderer()
            renderer.setGrayBand(band)
        rlayer.setDefaultContrastEnhancement()

        QgsMapLayerRegistry.instance().addMapLayers([rlayer])


    def on_pbnAddSelection_pressed(self):
        if debug>0:
            print('on_pbnAddSelection_pressed')
            #print(str(len(self.dim_names)) + " - " + str(self.ui.cbxMultiSelection.isChecked()))

        if len(self.dim_names) == 0:

            fileName = self.ui.leFileName.text()
            var = self.ui.cboVars.currentText()
            band = self.ui.leBandSelection.text()
            self.addLayer(fileName,var,band)

        else:

            if len( self.ui.leBandSelection.text() ) == 0:
                return

            fileName = self.ui.leFileName.text()
            var = self.ui.cboVars.currentText()

            for band_str in self.ui.leBandSelection.text().strip().split(' '):
                self.addLayer(fileName,var,band_str)


    def updateFile(self):
        self.clear()
        fileName = self.ui.leFileName.text()
        if debug>0:
            print('updateFile '+fileName)
        if fileName == '':
            return

        self.prefix = ''
        self.variables = []

        gdal.PushErrorHandler('CPLQuietErrorHandler')
        ds = gdal.Open(fileName)
        gdal.PopErrorHandler()
        if ds is None:
            return
        md = ds.GetMetadata("SUBDATASETS")
        ds = None

        for key in sorted(md.iterkeys()):
            #SUBDATASET_1_NAME=NETCDF:"file.nc":var
            if re.match('^SUBDATASET_[0-9]+_NAME$', key) is None:
                continue
            m = re.search('^(NETCDF:".+"):(.+)', md[key])
            if m is None:
                continue
            self.prefix = m.group(1)
            self.variables.append(m.group(2))

        if debug>0:
            print('prefix: '+str(self.prefix))
            print('variables: '+str(self.variables))
        self.ui.cboVars.blockSignals(True)
        self.ui.cboVars.clear()
        for var in self.variables:
            self.ui.cboVars.addItem( var )
        self.updateVariable()
        self.ui.cboVars.blockSignals(False)

        if debug>0:
            print('done updateFile '+fileName)


    def clear(self):
        if debug>0:
            print('clear')
        self.ui.lblDim1.setText('     -     ')
        self.ui.lblDim2.setText('     -     ')
        self.ui.leBandSelection.clear()
        if self.ui.pbnDim1.menu():
            QObject.disconnect(self.ui.pbnDim1.menu(), SIGNAL("triggered(QAction *)"), self.on_pbnDimx_triggered)   
            self.ui.pbnDim1.setMenu(None)
        if self.ui.pbnDim2.menu():
            QObject.disconnect(self.ui.pbnDim2.menu(), SIGNAL("triggered(QAction *)"), self.on_pbnDimx_triggered)   
            self.ui.pbnDim2.setMenu(None)


    def warning(self):
        gdal_version = gdal.VersionInfo("RELEASE_NAME")
        if debug>1:
            print("gdal version: " + str(gdal.VersionInfo("VERSION_NUM")))
        if int(gdal.VersionInfo("VERSION_NUM")) < 1000000:
            msg = self.tr("No extra dimensions found, make sure you are using\nGDAL >= 1.10\nYou seem to have "+gdal_version)
        else:
            msg = self.tr("No extra dimensions found.")
        QMessageBox.warning(self, self.tr("NetCDF Browser Plugin"), msg, QMessageBox.Close)

    def warning2(self):
        print("NetCDFBrowser: No extra dimensions found, but empty dimensions may have been removed")

    def updateVariable(self):
        dim_map = dict()
        self.dim_names = []
        self.dim_values = dict()
        self.dim_values2 = dict()
        self.dim_def = dict()
        self.dim_band = dict()
        self.dim1Count = 0
        self.dim2Count = 0
        self.clear()
        uri = 'NETCDF:"%s":%s' % (self.ui.leFileName.text(), self.ui.cboVars.currentText())

        if debug>0:
            print('updateVariable '+str(uri))

        #look for extra dim definitions
        #  NETCDF_DIM_EXTRA={time,tile}
        #  NETCDF_DIM_tile_DEF={3,6}
        #  NETCDF_DIM_tile_VALUES={1,2,3}
        #  NETCDF_DIM_time_DEF={12,6}
        #  NETCDF_DIM_time_VALUES={1,32,60,91,121,152,182,213,244,274,305,335}

        # open file and get basic info
        gdal.PushErrorHandler('CPLQuietErrorHandler')
        ds = gdal.Open(uri)
        gdal.PopErrorHandler()
        if ds is None:
            return
        wkt = ds.GetProjection()
        md = ds.GetMetadata()
        ds = None
        if md is None:
            return

        # update CRS selectors
        projectCrs = self.iface.mapCanvas().mapRenderer().destinationCrs()
        self.ui.cboCrs.setItemText(1, 
                                   self.tr( "Project" ) + " (%s, %s)" % (projectCrs.description(), projectCrs.authid()) )
        
        if not wkt or not self.layerCrs.createFromWkt(wkt):
                self.layerCrs = QgsCoordinateReferenceSystem()
        if debug > 0:
            print('wkt: '+wkt+' layer desc:'+self.layerCrs.description())

        # if layer has valid crs, use that, if not use selected crs
        if self.layerCrs.description():
            self.ui.cboCrs.setItemText(0, 
                                       self.tr( "Layer" ) + " (%s, %s)" % (self.layerCrs.description(), self.layerCrs.authid()) )
            self.ui.cboCrs.setCurrentIndex(0)
        else:
            self.ui.cboCrs.setItemText(0, self.tr("Layer (None)"))
            if self.selectedCrs.description():
                self.ui.cboCrs.setItemText(2, 
                                           self.tr( "Selected" ) + " (%s, %s)" % (self.selectedCrs.description(), self.selectedCrs.authid()) )
            else:
                self.ui.cboCrs.setItemText(2, self.tr("Selected (None)"))
            self.ui.cboCrs.setCurrentIndex(2)

        ds = None

        # iterate over all md items looking for dim info
        for key in sorted(md.iterkeys()):
            if key.startswith('NETCDF_DIM_'):
                line="%s=%s" % (key,md[key])
                m = re.search('^(NETCDF_DIM_.+)={(.+)}', line)
                if m is not None:
                    dim_map[ m.group(1) ] = m.group(2)

        if not 'NETCDF_DIM_EXTRA' in dim_map:
            self.warning()
            return
        
        tok = dim_map['NETCDF_DIM_EXTRA']
        if tok is not None:
            for dim in tok.split(','):
                self.dim_names.append( dim )
                tok2 = dim_map.get('NETCDF_DIM_'+dim+'_VALUES')
                self.dim_values[ dim ] = []
                if tok2 is not None:
                    for s in tok2.split(','):
                        self.dim_values[ dim ].append(num(s))
                tok2 = dim_map.get('NETCDF_DIM_'+dim+'_DEF')
                self.dim_def[ dim ] = []
                if tok2 is not None:
                    for s in tok2.split(','):
                        self.dim_def[ dim ].append(num(s))

        # remove any dims which have only 1 element
        dim_names = self.dim_names
        self.dim_names = []
        for dim in dim_names:
            if self.dim_def[dim][0] <= 1:
                del self.dim_values[dim]
                del self.dim_def[dim]
            else:
                self.dim_names.append(dim)

        # transform time dimensions - currently requires netcdftime from python-netcdf4              
        if has_netcdftime:
            for dim in dim_names:
                #dim+"#standard_name" in md and md[dim+"#standard_name"] == "time":
                if dim in self.dim_values:
                    if dim+"#units" in md:
                        timestr = md[ dim+"#units" ]
                        units = timestr.split()[0].lower()
                        if units in _units:
                            try:
                                dates = num2date(self.dim_values[dim],units=timestr)
                            except ValueError:
                                continue
                            self.dim_values2[ dim ] = []
                            only_days = True
                            for date in dates:
                                val = date.isoformat(" ") # equivalent to strftime("%Y-%m-%d %H:%M:%S")
                                if not val.endswith(" 00:00:00"):
                                    only_days = False
                                self.dim_values2[ dim ].append(val)
                            if only_days:
                                for i in range(0,len(self.dim_values2[ dim ])):
                                    self.dim_values2[dim][i] = self.dim_values2[dim][i][0:10]

        if debug>1:
            print(str(dim_map))
            print(str(self.dim_names))
            print(str(self.dim_def))
            print(str(self.dim_values))
            print(str(self.dim_values2))


        # update UI
        self.ui.pbnDim1.setEnabled(False)
        self.ui.pbnDim2.setEnabled(False)

        if len(self.dim_names) > 0:
            dim = self.dim_names[0]
            self.ui.lblDim1.setText( dim )
            menu = MyMenu()
            action = QAction(self.tr('all/none'),menu)
            action.setCheckable(True)
            menu.addAction(action)
            for i in range(0,len(self.dim_values[dim])):
                self.dim2Count = self.dim2Count + 1
                value = self.dim_values2[dim][i] if dim in self.dim_values2 else self.dim_values[dim][i]
                action = QAction(str(value),menu)
                action.setCheckable(True)
                menu.addAction(action)                
            self.ui.pbnDim1.setMenu(menu)
            QObject.connect(self.ui.pbnDim1.menu(), SIGNAL("triggered(QAction *)"), self.on_pbnDimx_triggered)   
            # click first element of each dim
            if len(menu.actions()) > 1:
                menu.actions()[1].setChecked(True)
            self.ui.pbnDim1.setEnabled(True)

        if len(self.dim_names) > 1:
            dim = self.dim_names[1]
            self.ui.lblDim2.setText( dim )
            menu = MyMenu()
            action = QAction(self.tr('all/none'),menu)
            action.setCheckable(True)
            menu.addAction(action)
            for i in range(0,len(self.dim_values[dim])):
                self.dim2Count = self.dim2Count + 1
                value = self.dim_values[dim][i]
                action = QAction(str(value),menu)
                action.setCheckable(True)
                menu.addAction(action)
            self.ui.pbnDim2.setMenu(menu)
            QObject.connect(self.ui.pbnDim2.menu(), SIGNAL("triggered(QAction *)"), self.on_pbnDimx_triggered)   
            # click first element of each dim
            if len(menu.actions()) > 1:
                menu.actions()[1].setChecked(True)
            self.ui.pbnDim2.setEnabled(True)

        # make sure we found something, if not notify user
        if len(self.dim_names) == 0:
            self.warning2()
        self.updateURI()
        self.updateDims()


    def updateDims(self):
        # TODO minimize calls to this fct
        if debug>0:
            print('updateDims')
        self.updateDimsMulti()
            
    def updateDimsMulti(self):
        # update multi-band selection
        self.ui.leBandSelection.clear()
        if self.ui.pbnDim1.menu() is None and self.ui.pbnDim2.menu() is None:
            return
        sel1 = []
        i=0
        actions = [] if self.ui.pbnDim1.menu() is None else self.ui.pbnDim1.menu().actions()
        for action in actions:
            if action.text() != self.tr('all/none'):
                if action.isChecked():
                    sel1.append(i)
                i = i + 1
        sel2 = []
        i=0
        actions = [] if self.ui.pbnDim2.menu() is None else self.ui.pbnDim2.menu().actions()
        for action in actions:
            if action.text() != self.tr('all/none'):
                if action.isChecked():
                    sel2.append(i)
                i = i + 1

        sel_str = ''
        for dim1val in sel1:
            if self.ui.pbnDim2.menu() is None:
                band = dim1val+1
                self.dim_band[band] = [dim1val+1]
                sel_str = '%s%d ' % (sel_str,band)
            else:
                for dim2val in sel2:
                    band = self.bandNo(dim1val,dim2val)
                    self.dim_band[band] = [dim1val+1,dim2val+1]
                    sel_str = '%s%d ' % (sel_str,band)

        self.ui.leBandSelection.setText(sel_str)


    def bandNo(self,dim1val,dim2val):
        band = 0
        if dim2val > -1 :
            band += dim2val+1
        if dim1val > -1 :
            if len(self.dim_def) > 0 and len(self.dim_names) > 0:
                band += (dim1val) * int(self.dim_def[self.dim_names[1]][0])
        return band


    def updateURI(self):
        if debug>0:
            print('updateURI')
        # update URI
        fileInfo = QFileInfo(self.ui.leFileName.text())
        uri = 'NETCDF:"%s":%s' % (fileInfo.fileName(), self.ui.cboVars.currentText())
        self.ui.leURI.setText(uri)


    def on_pbnDimx_triggered(self,action):
        if action in self.ui.pbnDim1.menu().actions():
            pbn = self.ui.pbnDim1
        elif action in self.ui.pbnDim2.menu().actions():
            pbn = self.ui.pbnDim2
        else:
            return
        # 'all/none' action selects all/none
        if action.text() == self.tr('all/none'):
            pbn.blockSignals(True)
            for act in pbn.menu().actions():
                if act.text() != self.tr('all/none'):
                    act.setChecked(action.isChecked())
            pbn.blockSignals(False)
        
        # update selection
        self.updateDims()


    def on_pbnCrs_pressed(self):
        selector = QgsGenericProjectionSelector(self)
        selector.setMessage();
        if self.layerCrs.description():
            selector.setSelectedCrsId( self.layerCrs.srsid() );
        elif self.selectedCrs.description():
            selector.setSelectedCrsId( self.selectedCrs.srsid() );
        if selector.exec_():
            self.selectedCrs.createFromId( selector.selectedCrsId(), QgsCoordinateReferenceSystem.InternalCrsId );
            self.ui.cboCrs.setCurrentIndex(2)

        if self.selectedCrs.description():
            self.ui.cboCrs.setItemText(2, 
                                       self.tr( "Selected" ) + " (%s, %s)" % (self.selectedCrs.description(), self.selectedCrs.authid()) )
        else:
            self.ui.cboCrs.setItemText(2, self.tr("Selected (None)"))
            

