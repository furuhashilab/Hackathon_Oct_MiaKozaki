"""run_minimal.py の出力から、到達圏と円の比較図（PNG）を書き出す。

  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/render_map.py output/run_YYYYmmdd_HHMM
"""
import os
import sys
from pathlib import Path

APP = "/Applications/QGIS-LTR.app/Contents"
os.environ.setdefault("PROJ_DATA", f"{APP}/Resources/proj")
os.environ.setdefault("GDAL_DATA", f"{APP}/Resources/gdal")
os.environ.setdefault("QGIS_PREFIX_PATH", f"{APP}/MacOS")

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsFillSymbol, QgsLineSymbol,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsMarkerSymbol, QgsRasterLayer,
                       QgsRectangle, QgsVectorLayer)
from qgis.PyQt.QtCore import QSize, Qt, QRectF
from qgis.PyQt.QtGui import QColor, QFont, QPainter

run_dir = Path(sys.argv[1]).resolve()
minutes, radius = 10, 800

app = QgsApplication([], False)
app.initQgis()


def vec(name, symbol):
    lyr = QgsVectorLayer(str(run_dir / f"{name}.gpkg"), name, "ogr")
    if not lyr.isValid():
        sys.exit(f"読めない: {name}")
    lyr.renderer().setSymbol(symbol)
    return lyr


basemap = QgsRasterLayer("type=xyz&url=https://cyberjapandata.gsi.go.jp/xyz/pale/%7Bz%7D/%7Bx%7D/%7By%7D.png"
                         "&zmax=18&zmin=2", "地理院タイル（淡色地図）", "wms")
network = vec("walk_network", QgsLineSymbol.createSimple({"color": "90,90,90,140", "width": "0.25"}))
iso = vec(f"iso_{minutes}min", QgsFillSymbol.createSimple(
    {"color": "235,120,30,110", "outline_color": "200,90,10,255", "outline_width": "0.6"}))
gap = vec("circle_minus_iso", QgsFillSymbol.createSimple(
    {"color": "40,90,200,45", "outline_style": "no"}))
circle = vec(f"circle_{radius}", QgsFillSymbol.createSimple(
    {"color": "0,0,0,0", "outline_color": "30,70,180,255", "outline_width": "0.7", "outline_style": "dash"}))
origin = vec("origin_6677", QgsMarkerSymbol.createSimple(
    {"name": "star", "color": "220,20,60,255", "outline_color": "white", "size": "5"}))

c = circle.extent().center()
h = radius * 1.25
size = QSize(1800, 1800)
ms = QgsMapSettings()
ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:6677"))
ms.setLayers([origin, circle, iso, gap, network, basemap])
ms.setExtent(QgsRectangle(c.x() - h, c.y() - h, c.x() + h, c.y() + h))
ms.setOutputSize(size)
ms.setOutputDpi(200)
ms.setBackgroundColor(QColor("white"))

job = QgsMapRendererParallelJob(ms)
job.start()
job.waitForFinished()
img = job.renderedImage()

# 凡例・出典
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setPen(Qt.NoPen)
p.setBrush(QColor(255, 255, 255, 225))
p.drawRoundedRect(QRectF(30, 30, 760, 200), 12, 12)
items = [
    (QColor(235, 120, 30, 160), "solid", f"徒歩{minutes}分圏（QNEAT3・道路距離 {minutes * 80} m）"),
    (QColor(30, 70, 180), "dash", f"半径{radius}mの円"),
    (QColor(40, 90, 200, 70), "solid", "円の中で10分では届かない範囲"),
    (QColor(220, 20, 60), "star", "起点：JR町田駅 北口（デッキ）"),
]
f = QFont("Hiragino Sans")
f.setPixelSize(30)
p.setFont(f)
for i, (col, kind, label) in enumerate(items):
    y = 50 + i * 44
    p.setBrush(col if kind != "dash" else Qt.NoBrush)
    pen = p.pen()
    p.setPen(QColor(30, 70, 180) if kind == "dash" else Qt.NoPen)
    if kind == "dash":
        pp = p.pen(); pp.setStyle(Qt.DashLine); pp.setWidth(4); p.setPen(pp)
    p.drawRect(QRectF(55, y, 44, 30))
    p.setPen(QColor(20, 20, 20))
    p.drawText(115, y + 27, label)
f2 = QFont("Hiragino Sans")
f2.setPixelSize(22)
p.setFont(f2)
p.setPen(Qt.NoPen)
p.setBrush(QColor(255, 255, 255, 225))
p.drawRect(QRectF(0, size.height() - 62, size.width(), 62))
p.setPen(QColor(40, 40, 40))
p.drawText(30, size.height() - 30,
           "背景：地理院タイル（淡色地図）／道路：© OpenStreetMap contributors（ODbL）／EPSG:6677")
p.end()

out = run_dir / f"map_iso{minutes}_vs_circle{radius}.png"
img.save(str(out))
print(out)
app.exitQgis()
