"""run_minimal.py の出力を、確認用に色分けした QGIS プロジェクトにまとめる。

  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/make_result_project.py output/run_YYYYmmdd_HHMM
  → machida-walk/result_run_YYYYmmdd_HHMM.qgz
"""
import os
import sys
from pathlib import Path

APP = "/Applications/QGIS-LTR.app/Contents"
os.environ.setdefault("PROJ_DATA", f"{APP}/Resources/proj")
os.environ.setdefault("GDAL_DATA", f"{APP}/Resources/gdal")
os.environ.setdefault("QGIS_PREFIX_PATH", f"{APP}/MacOS")

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsFillSymbol, QgsLineSymbol,
                       QgsMarkerSymbol, QgsProject, QgsRasterLayer, QgsRectangle,
                       QgsReferencedRectangle, QgsVectorLayer)

ROOT = Path(__file__).resolve().parent.parent
run_dir = Path(sys.argv[1]).resolve()

app = QgsApplication([], False)
app.initQgis()
p = QgsProject.instance()
crs = QgsCoordinateReferenceSystem("EPSG:6677")
p.setCrs(crs)


def vec(file, title, symbol, visible=True):
    lyr = QgsVectorLayer(str(file), title, "ogr")
    if not lyr.isValid():
        sys.exit(f"読めない: {file}")
    lyr.renderer().setSymbol(symbol)
    p.addMapLayer(lyr)
    p.layerTreeRoot().findLayer(lyr.id()).setItemVisibilityChecked(visible)
    return lyr


basemap = QgsRasterLayer("type=xyz&url=https://cyberjapandata.gsi.go.jp/xyz/pale/%7Bz%7D/%7Bx%7D/%7By%7D.png"
                         "&zmax=18&zmin=2", "地理院 淡色地図", "wms")
p.addMapLayer(basemap)
vec(run_dir / "walk_network.gpkg", "歩行可能な道（walk_network）",
    QgsLineSymbol.createSimple({"color": "80,80,80,160", "width": "0.3"}))
vec(run_dir / "circle_minus_iso.gpkg", "円の中で10分では届かない範囲",
    QgsFillSymbol.createSimple({"color": "40,90,200,60", "outline_style": "no"}))
vec(run_dir / "iso_10min.gpkg", "徒歩10分圏（QNEAT3）",
    QgsFillSymbol.createSimple({"color": "235,120,30,90", "outline_color": "200,90,10", "outline_width": "0.6"}))
vec(run_dir / "iso_10min_pointcloud.gpkg", "到達した頂点とコスト（pointcloud）",
    QgsMarkerSymbol.createSimple({"name": "circle", "color": "200,90,10", "size": "0.8", "outline_style": "no"}),
    visible=False)
vec(run_dir / "review_candidates.gpkg", "要確認の道（屋内・階段・橋・営業時間など）",
    QgsLineSymbol.createSimple({"color": "140,40,180", "width": "0.8"}), visible=False)
vec(run_dir / "excluded_ways.gpkg", "除外した道（excluded_ways）",
    QgsLineSymbol.createSimple({"color": "220,30,30", "width": "0.8", "line_style": "dash"}), visible=False)
circle = vec(run_dir / "circle_800.gpkg", "半径800mの円",
             QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "30,70,180",
                                         "outline_width": "0.7", "outline_style": "dash"}))
vec(ROOT / "data" / "origin.gpkg|layername=origin", "起点（origin）",
    QgsMarkerSymbol.createSimple({"name": "star", "color": "220,20,60", "outline_color": "white", "size": "5"}))

# レイヤパネルでは後から追加したものが上に来るので、そのままの順で描画される
c = circle.extent().center()
h = 1000
p.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(QgsRectangle(c.x() - h, c.y() - h, c.x() + h, c.y() + h), crs))
p.writeEntry("Paths", "/Absolute", False)
out = ROOT / f"result_{run_dir.name}.qgz"
print(out if p.write(str(out)) else "保存に失敗")
app.exitQgis()
