"""analyze_gaps.py の結果（8方位の到達率・踏切）を背景地図に重ねた図を書き出す。

  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/render_gaps_map.py output/run_YYYYmmdd_HHMM
"""
import json
import math
import os
import sys
from pathlib import Path

APP = "/Applications/QGIS-LTR.app/Contents"
os.environ.setdefault("PROJ_DATA", f"{APP}/Resources/proj")
os.environ.setdefault("GDAL_DATA", f"{APP}/Resources/gdal")
os.environ.setdefault("QGIS_PREFIX_PATH", f"{APP}/MacOS")

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsFillSymbol, QgsLineSymbol,
                       QgsMapRendererParallelJob, QgsMapSettings, QgsMarkerSymbol, QgsPointXY,
                       QgsRasterLayer, QgsRectangle, QgsVectorLayer)
from qgis.PyQt.QtCore import QPointF, QRectF, QSize, Qt
from qgis.PyQt.QtGui import QColor, QFont, QPainter

run_dir = Path(sys.argv[1]).resolve()
gdir = run_dir / "gaps"
summary = json.loads((gdir / "gaps_summary.json").read_text(encoding="utf-8"))
app = QgsApplication([], False)
app.initQgis()


def vec(path, sym):
    lyr = QgsVectorLayer(str(path), Path(path).stem, "ogr")
    assert lyr.isValid(), path
    lyr.renderer().setSymbol(sym)
    return lyr


basemap = QgsRasterLayer("type=xyz&url=https://cyberjapandata.gsi.go.jp/xyz/pale/%7Bz%7D/%7Bx%7D/%7By%7D.png"
                         "&zmax=18&zmin=2", "gsi", "wms")
iso = vec(run_dir / "iso_10min.gpkg", QgsFillSymbol.createSimple(
    {"color": "235,120,30,70", "outline_color": "200,90,10", "outline_width": "0.5"}))
gap = vec(run_dir / "circle_minus_iso.gpkg", QgsFillSymbol.createSimple({"color": "40,90,200,70", "outline_style": "no"}))
sectors = vec(gdir / "sectors.gpkg", QgsFillSymbol.createSimple(
    {"color": "0,0,0,0", "outline_color": "60,60,60,200", "outline_width": "0.3", "outline_style": "dot"}))
circle = vec(run_dir / "circle_800.gpkg", QgsFillSymbol.createSimple(
    {"color": "0,0,0,0", "outline_color": "30,70,180", "outline_width": "0.6", "outline_style": "dash"}))
xing = vec(gdir / "rail_crossings.gpkg", QgsMarkerSymbol.createSimple(
    {"name": "cross2", "color": "0,0,0", "outline_color": "0,0,0", "outline_width": "0.6", "size": "3.5"}))
origin = vec(run_dir / "origin_6677.gpkg", QgsMarkerSymbol.createSimple(
    {"name": "star", "color": "220,20,60", "outline_color": "white", "size": "5"}))

c = circle.extent().center()
h = 1000
size = QSize(1800, 1800)
ms = QgsMapSettings()
ms.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:6677"))
ms.setLayers([origin, xing, circle, sectors, iso, gap, basemap])
ms.setExtent(QgsRectangle(c.x() - h, c.y() - h, c.x() + h, c.y() + h))
ms.setOutputSize(size)
ms.setOutputDpi(200)
job = QgsMapRendererParallelJob(ms)
job.start(); job.waitForFinished()
img = job.renderedImage()

p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
f = QFont("Hiragino Sans"); f.setPixelSize(30); f.setBold(True)
p.setFont(f)
o = circle.extent().center()
for g in summary["gaps"]:
    a = math.radians((g["sector_id"] - 1) * 45)
    pt = ms.mapToPixel().transform(QgsPointXY(o.x() + 880 * math.sin(a), o.y() + 880 * math.cos(a)))
    label = f"{g['direction']} {g['reached_pct']:.0f}%\n迂回率 {g['median_detour_ratio']}"
    r = QRectF(pt.x() - 110, pt.y() - 42, 220, 84)
    p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 220)); p.drawRoundedRect(r, 10, 10)
    p.setPen(QColor(20, 20, 20)); p.drawText(r, Qt.AlignCenter, label)
f2 = QFont("Hiragino Sans"); f2.setPixelSize(26); p.setFont(f2)
ly = size.height() - 230
p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 225)); p.drawRoundedRect(QRectF(20, ly, 900, 150), 10, 10)
p.setPen(QColor(20, 20, 20))
p.drawText(40, ly + 40, "％：方位ごとの扇形のうち徒歩10分圏（オレンジ）に入る割合")
p.drawText(40, ly + 80, "迂回率：届かない部分（青）の道の頂点の 道路距離÷直線距離（中央値）")
p.drawText(40, ly + 120, "×：踏切・線路の横断（OSM）　★：起点")
f3 = QFont("Hiragino Sans"); f3.setPixelSize(22); p.setFont(f3)
p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, 225)); p.drawRect(QRectF(0, size.height() - 56, size.width(), 56))
p.setPen(QColor(40, 40, 40))
p.drawText(24, size.height() - 20, "背景：地理院タイル（淡色地図）／道路・踏切：© OpenStreetMap contributors（ODbL）／EPSG:6677")
p.end()
out = gdir / "map_gaps_by_direction.png"
img.save(str(out)); print(out)
app.exitQgis()
