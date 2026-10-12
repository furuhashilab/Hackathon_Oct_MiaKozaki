#!/bin/bash
# qgis_process を proj.db・GDAL データ（osmconf.ini）の場所を指定して呼ぶラッパー
APP=/Applications/QGIS-LTR.app
export PROJ_DATA="$APP/Contents/Resources/proj"
export PROJ_LIB="$PROJ_DATA"
export GDAL_DATA="$APP/Contents/Resources/gdal"
exec "$APP/Contents/MacOS/bin/qgis_process" "$@"
