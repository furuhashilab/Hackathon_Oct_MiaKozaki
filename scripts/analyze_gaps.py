"""「円には入るが到達圏外」の場所を部分ごとに分け、回り道の度合いを調べる。

  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/analyze_gaps.py output/run_YYYYmmdd_HHMM

- 円を起点から8方位（45°ずつ）の扇形に分け、方位ごとに 10分圏に入る割合と届かない面積を出す
- QNEAT3（Pointcloud）で 1,600 m まで道路距離を計算し、各面の中の道の頂点について
  「道路距離 ÷ 直線距離」（迂回率）の中央値を方位ごとに求める
- 円の中の踏切（railway=level_crossing）・線路の横断（railway=crossing）を一覧にする
"""
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_minimal import CONFIG, ROOT, lines_layer, read_csv, run  # noqa: E402

run_dir = Path(sys.argv[1]).resolve()
out = run_dir / "gaps"
(out / "_tmp").mkdir(parents=True, exist_ok=True)
gpkg = lambda n: str(out / f"{n}.gpkg")
tmp = lambda n: str(out / "_tmp" / f"{n}.gpkg")
log = {"steps": []}
PC_MAX = 1600    # 迂回率を見るための道路距離の上限 (m)

origin = read_csv(run_dir / "origin_xy.csv")[0]
ox, oy = float(origin["xcoord"]), float(origin["ycoord"])
radius = CONFIG["circle_radius_m"]


def compass(dx, dy):  # 起点から見た8方位
    deg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    names = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]
    return names[round(deg / 45) % 8], round(deg)


print("1. 起点から8方位（45°ずつ）の扇形で円を区切る")
names8 = ["北", "北東", "東", "南東", "南", "南西", "西", "北西"]
feats = []
for i, nm in enumerate(names8):
    a0, a1 = math.radians(i * 45 - 22.5), math.radians(i * 45 + 22.5)
    ring = [(ox, oy)] + [(ox + 1000 * math.sin(a0 + (a1 - a0) * k / 32), oy + 1000 * math.cos(a0 + (a1 - a0) * k / 32))
                         for k in range(33)] + [(ox, oy)]
    feats.append({"type": "Feature", "properties": {"sector_id": i + 1, "direction": nm},
                  "geometry": {"type": "Polygon", "coordinates": [[list(xy) for xy in ring]]}})
sect_path = out / "_tmp/sectors.geojson"
sect_path.write_text(json.dumps({"type": "FeatureCollection",
                                 "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::6677"}},
                                 "features": feats}), encoding="utf-8")
sectors = run("native:savefeatures", {"INPUT": str(sect_path), "OUTPUT": gpkg("sectors")}, log)["OUTPUT"]


def area_by_sector(layer, name):
    inter = run("native:intersection", {"INPUT": sectors, "OVERLAY": layer, "INPUT_FIELDS": ["sector_id", "direction"],
                                        "OVERLAY_FIELDS_PREFIX": "o_", "OUTPUT": gpkg(name)}, log)["OUTPUT"]
    rs = read_csv(run("qgis:exportaddgeometrycolumns", {"INPUT": inter, "CALC_METHOD": 0,
                                                        "OUTPUT": str(out / f"_tmp/{name}.csv")}, log)["OUTPUT"])
    acc = {}
    for r in rs:
        acc[int(r["sector_id"])] = acc.get(int(r["sector_id"]), 0) + float(r["area"])
    return acc, inter


circle_a, _ = area_by_sector(str(run_dir / f"circle_{radius}.gpkg"), "sector_circle")
iso_a, _ = area_by_sector(str(run_dir / "iso_10min.gpkg"), "sector_iso")
gap_a, parts = area_by_sector(str(run_dir / "circle_minus_iso.gpkg"), "sector_gap")

print(f"2. QNEAT3 で {PC_MAX} m までの道路距離")
network = str(run_dir / "walk_network_densified.gpkg")
pc = run("qneat3:isoareaaspointcloudfromlayer", {
    "INPUT": network, "START_POINTS": str(run_dir / "origin_6677.gpkg"), "ID_FIELD": "oid",
    "MAX_DIST": PC_MAX, "DEFAULT_SPEED": CONFIG["walk_speed_kmh"],
    **{k: v for k, v in CONFIG["qneat3"].items() if k != "CELL_SIZE"},
    "OUTPUT": gpkg(f"pointcloud_{PC_MAX}")}, log)["OUTPUT"]
joined = run("native:joinattributesbylocation", {"INPUT": pc, "JOIN": parts, "PREDICATE": [5],  # within
                                                 "JOIN_FIELDS": ["sector_id"], "METHOD": 0, "DISCARD_NONMATCHING": True,
                                                 "OUTPUT": tmp("pc_in_gaps")}, log)["OUTPUT"]
pts = read_csv(run("qgis:exportaddgeometrycolumns", {"INPUT": joined, "CALC_METHOD": 0,
                                                     "OUTPUT": str(out / "_tmp/pc_in_gaps.csv")}, log)["OUTPUT"])

print("3. 円の中の踏切・線路の横断")
pts_layer = lines_layer(str(ROOT / "data/osm_highway_20261012_2117.gpkg")).replace("_lines", "_points")
xing = run("native:extractbyexpression", {"INPUT": pts_layer,
                                          "EXPRESSION": "\"railway\" IN ('level_crossing','crossing')",
                                          "OUTPUT": tmp("xing")}, log)["OUTPUT"]
xing = run("native:reprojectlayer", {"INPUT": xing, "TARGET_CRS": CONFIG["crs"], "OUTPUT": gpkg("rail_crossings")}, log)["OUTPUT"]
xrows = read_csv(run("qgis:exportaddgeometrycolumns", {"INPUT": xing, "CALC_METHOD": 0,
                                                       "OUTPUT": str(out / "_tmp/xing.csv")}, log)["OUTPUT"])

# ── 集計 ──────────────────────────────────────────────────────────────
gaps = []
for i, nm in enumerate(names8, 1):
    mine = [p for p in pts if int(p["sector_id"]) == i]
    ratios, costs, eucl = [], [], []
    for p in mine:
        e = math.hypot(float(p["xcoord"]) - ox, float(p["ycoord"]) - oy)
        if e > 50:
            ratios.append(float(p["cost"]) / e); costs.append(float(p["cost"])); eucl.append(e)
    med = lambda xs: sorted(xs)[len(xs) // 2] if xs else None
    ca = circle_a.get(i, 0)
    gaps.append({
        "sector_id": i, "direction": nm, "circle_sector_m2": round(ca),
        "reached_m2": round(iso_a.get(i, 0)), "gap_m2": round(gap_a.get(i, 0)),
        "reached_pct": round(iso_a.get(i, 0) / ca * 100, 1) if ca else None,
        "gap_vertices": len(ratios),
        "median_network_m": round(med(costs)) if costs else None,
        "median_straight_m": round(med(eucl)) if eucl else None,
        "median_detour_ratio": round(med(ratios), 2) if ratios else None,
    })

crossings = []
for x in xrows:
    xx, yy = float(x["xcoord"]), float(x["ycoord"])
    d = math.hypot(xx - ox, yy - oy)
    if d <= radius * 1.2:
        name, deg = compass(xx - ox, yy - oy)
        crossings.append({"osm_id": x.get("full_id") or x.get("osm_id"), "railway": x["railway"],
                          "name": x.get("name") or "", "direction": name, "dist_m": round(d),
                          "x": round(xx, 1), "y": round(yy, 1)})
crossings.sort(key=lambda c: c["dist_m"])

with open(out / "gaps.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(gaps[0].keys()))
    w.writeheader(); w.writerows(gaps)
with open(out / "rail_crossings.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(crossings[0].keys()) if crossings else ["none"])
    w.writeheader(); w.writerows(crossings)
(out / "gaps_summary.json").write_text(json.dumps({"gaps": gaps, "crossings": crossings}, ensure_ascii=False, indent=2),
                                       encoding="utf-8")

print("\n方位ごとの到達率（円の扇形のうち10分圏に入る割合）と、届かない部分の迂回率")
for g in gaps:
    print(f"  {g['direction']:<3} 到達 {g['reached_pct']:>5}%  届かない {g['gap_m2']:>8,} m²  "
          f"頂点{g['gap_vertices']:>4}  道路{g['median_network_m']} m / 直線{g['median_straight_m']} m "
          f"→ 迂回率 {g['median_detour_ratio']}")
print(f"\n踏切・線路の横断（起点から {radius * 1.2:.0f} m 以内）")
for c in crossings:
    print(f"  {c['railway']:<15} {c['direction']:<3} {c['dist_m']:>4} m  {c['name']}  {c['osm_id']}")
