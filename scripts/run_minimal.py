"""町田駅 徒歩10分圏 × 半径800m円 の最小構成パイプライン。

すべての処理は qgis_process（QGIS 本体）経由で、QuickOSM と QNEAT3 のアルゴリズムを呼ぶ。
独自のネットワーク計算は行わない。

使い方（QGIS 同梱の python で実行）:
  /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/run_minimal.py
    --origin data/origin.gpkg            起点（ポイント1つ。QGIS で自分で置く）
    [--osm-file data/xxx.osm]            既に取得済みの .osm を使う（再取得しない）
    [--out output/run_YYYYmmdd_HHMM]     出力先

起点レイヤ以外の条件は CONFIG にまとめてあり、実行ごとに logs/ に記録される。
"""
import argparse
import csv
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QP = ROOT / "scripts" / "qp.sh"

CONFIG = {
    "crs": "EPSG:6677",               # JGD2011 / 平面直角座標系 第IX系
    "download_buffer_m": 2000,        # 最大到達 1,200 m より広く取る
    "overpass_timeout_s": 120,
    "walk_speed_kmh": 4.8,            # 80 m/分
    "minutes": 10,
    "circle_radius_m": 800,
    "qneat3": {
        "STRATEGY": 0,                # 0 = Shortest（距離）。距離 = 時間 × 80 m/分 で換算
        "DEFAULT_DIRECTION": 2,       # 2 = Both。車の oneway は歩行者に適用しない
        "TOLERANCE": 0,               # 隙間を自動で埋めない（立体交差の誤接続を防ぐ）
        "CELL_SIZE": 10,              # 補間ラスタのセルサイズ (m)
        "ENTRY_COST_CALCULATION_METHOD": 0,  # Planar（投影座標系で使用）
    },
    "buffer_segments": 32,            # 1/4 円あたりの分割数
    # QNEAT3 は頂点ごとにコストを持つので、道の途中にも頂点を足して到達圏の形を細かくする。
    # 既存の線の上に点を足すだけで、新しい接続（交差）は作らない。0 にすると行わない。
    "densify_interval_m": 10,
}

# ── 歩行可能ネットワークの条件 ───────────────────────────────────────────────
# QuickOSM はタグを1列ずつに展開するが、OGR で .osm を直接読むと foot / access などは
# other_tags（hstore 文字列）に入る。どちらでも同じ式で読めるようにする。
EXCLUDE_HIGHWAY = ["motorway", "motorway_link", "construction", "proposed",
                   "raceway", "bus_guideway", "abandoned", "razed", "platform"]


def tag(key):
    return (f"coalesce(attribute(@feature,'{key}'),"
            f"map_get(hstore_to_map(coalesce(attribute(@feature,'other_tags'),'')),'{key}'),'')")


def qlist(xs):
    return ",".join(f"'{x}'" for x in xs)


WALKABLE_EXPR = (
    f"\"highway\" IS NOT NULL AND \"highway\" NOT IN ({qlist(EXCLUDE_HIGHWAY)})"
    f" AND {tag('foot')} NOT IN ('no','private')"
    f" AND NOT ({tag('access')} IN ('no','private')"
    f" AND {tag('foot')} NOT IN ('yes','designated','permissive'))"
)

# 除外はしないが、扱いを目で確認すべき道（改札内・屋内・営業時間・立体交差・階段）
REVIEW_EXPR = (
    f"{tag('indoor')} <> '' OR {tag('level')} <> '' OR {tag('opening_hours')} <> ''"
    f" OR {tag('bridge')} <> '' OR {tag('tunnel')} <> '' OR {tag('layer')} <> ''"
    f" OR {tag('covered')} <> '' OR \"highway\" IN ('steps','corridor','elevator')"
    f" OR {tag('railway')} <> '' OR {tag('public_transport')} <> ''"
)


def run(alg, inputs, log):
    """qgis_process を JSON モードで呼び、結果を返す。"""
    payload = json.dumps({"inputs": inputs})
    p = subprocess.run([str(QP), "--json", "run", alg, "-"], input=payload,
                       capture_output=True, text=True)
    out = p.stdout[p.stdout.find("{"):] if "{" in p.stdout else ""
    if p.returncode != 0 or not out:
        sys.exit(f"[失敗] {alg}\n{p.stdout}\n{p.stderr}")
    res = json.loads(out)
    log["steps"].append({"algorithm": alg, "inputs": inputs, "results": res.get("results")})
    print(f"  ✓ {alg}")
    return res["results"]


def versions():
    p = subprocess.run([str(QP), "--json", "--version"], capture_output=True, text=True)
    info = {"qgis_process_version": p.stdout.strip().splitlines()[:2]}
    plugdir = Path.home() / "Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins"
    for name in ("QNEAT3", "QuickOSM"):
        meta = plugdir / name / "metadata.txt"
        if meta.exists():
            for line in meta.read_text().splitlines():
                if line.startswith("version="):
                    info[name] = line.split("=", 1)[1]
    return info


def lines_layer(path):
    """.osm（OGR で直接読む）か、QuickOSM が保存した .gpkg（*_lines レイヤ）のライン層を返す。"""
    if not path.endswith(".gpkg"):
        return f"{path}|layername=lines"
    import sqlite3
    with sqlite3.connect(path) as db:
        names = [r[0] for r in db.execute("select table_name from gpkg_contents where table_name like '%\\_lines' escape '\\'")]
    if len(names) != 1:
        sys.exit(f"{path} にライン層が見つからない: {names}")
    return f"{path}|layername={names[0]}"


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def area_of(layer, out_dir, name, log):
    """レイヤの CRS（EPSG:6677, m）で面積を計算し、合計 m² を返す。"""
    csv_path = out_dir / f"area_{name}.csv"
    run("qgis:exportaddgeometrycolumns", {"INPUT": layer, "CALC_METHOD": 0, "OUTPUT": str(csv_path)}, log)
    return sum(float(r["area"]) for r in read_csv(csv_path) if r.get("area"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default=str(ROOT / "data/origin.gpkg"))
    ap.add_argument("--osm-file")
    ap.add_argument("--out")
    ap.add_argument("--server", default="https://overpass-api.de/api/interpreter",
                    help="Overpass API サーバー（QuickOSM の SERVER パラメータ）")
    a = ap.parse_args()

    now = dt.datetime.now().astimezone()
    out = Path(a.out) if a.out else ROOT / "output" / f"run_{now:%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    gpkg = lambda n: str(out / f"{n}.gpkg")
    (out / "_tmp").mkdir(exist_ok=True)
    tmp = lambda n: str(out / "_tmp" / f"{n}.gpkg")  # qgis_process は呼び出しごとに別プロセスなのでファイルで渡す
    log = {"run_started": now.isoformat(), "config": CONFIG, "walkable_expression": WALKABLE_EXPR,
           "review_expression": REVIEW_EXPR, "versions": versions(), "steps": []}

    dist = CONFIG["minutes"] * CONFIG["walk_speed_kmh"] * 1000 / 60  # 10分 → 800 m
    print(f"到達コスト: {CONFIG['minutes']}分 × {CONFIG['walk_speed_kmh']} km/h = {dist:.0f} m（距離で計算）")

    print("1. 起点を投影座標系へ")
    o = run("native:reprojectlayer", {"INPUT": a.origin, "TARGET_CRS": CONFIG["crs"],
                                      "OUTPUT": tmp("t1")}, log)
    origin = run("native:fieldcalculator", {"INPUT": o["OUTPUT"], "FIELD_NAME": "oid", "FIELD_TYPE": 1,
                                            "FORMULA": "@row_number", "OUTPUT": gpkg("origin_6677")}, log)["OUTPUT"]
    xy = run("qgis:exportaddgeometrycolumns", {"INPUT": origin, "CALC_METHOD": 0,
                                               "OUTPUT": str(out / "origin_xy.csv")}, log)
    pts = read_csv(xy["OUTPUT"])
    if len(pts) != 1:
        sys.exit(f"起点は1つにしてください（現在 {len(pts)} 個）")
    log["origin"] = pts[0]
    print(f"   起点 (EPSG:6677): x={float(pts[0]['xcoord']):.2f}, y={float(pts[0]['ycoord']):.2f}")

    print("2. OSM 道路データ（QuickOSM）")
    if a.osm_file:
        osm_file = a.osm_file
        log["osm_source"] = {"file": osm_file, "note": "既存ファイルを使用（再取得なし）"}
    else:
        area = run("native:buffer", {"INPUT": origin, "DISTANCE": CONFIG["download_buffer_m"],
                                     "SEGMENTS": 8, "OUTPUT": tmp("t2")}, log)
        area4326 = run("native:reprojectlayer", {"INPUT": area["OUTPUT"], "TARGET_CRS": "EPSG:4326",
                                                 "OUTPUT": gpkg("download_area_4326")}, log)["OUTPUT"]
        q = run("quickosm:buildqueryextent", {"KEY": "highway", "VALUE": "", "EXTENT": area4326,
                                              "TIMEOUT": CONFIG["overpass_timeout_s"], "SERVER": a.server}, log)
        (out / "overpass_query.oql").write_text(q["OUTPUT_OQL_QUERY"], encoding="utf-8")
        # QuickOSM は FILE の末尾5文字（".gpkg"）を外した名前を接頭辞にして GeoPackage を作る
        osm_file = str(ROOT / "data" / f"osm_highway_{now:%Y%m%d_%H%M}.gpkg")
        dl = run("quickosm:downloadosmdataextentquery", {"KEY": "highway", "VALUE": "", "EXTENT": area4326,
                                                     "TIMEOUT": CONFIG["overpass_timeout_s"], "SERVER": a.server,
                                                     "FILE": osm_file}, log)
        if not Path(osm_file).exists():
            sys.exit(f"QuickOSM の出力が見つからない: {osm_file}（結果: {dl}）")
        log["osm_source"] = {"file": osm_file, "downloaded_at": dt.datetime.now().astimezone().isoformat(),
                             "server": a.server,
                             "source": "OpenStreetMap contributors (ODbL) via Overpass API / QuickOSM"}

    print("3. 投影座標系へ変換・歩行可能な道の抽出")
    raw = run("native:reprojectlayer", {"INPUT": lines_layer(osm_file), "TARGET_CRS": CONFIG["crs"],
                                        "OUTPUT": gpkg("osm_highway_raw_6677")}, log)["OUTPUT"]
    ex = run("native:extractbyexpression", {"INPUT": raw, "EXPRESSION": WALKABLE_EXPR,
                                            "OUTPUT": gpkg("walk_network"), "FAIL_OUTPUT": gpkg("excluded_ways")}, log)
    network = ex["OUTPUT"]
    if CONFIG["densify_interval_m"]:
        network = run("native:densifygeometriesgivenaninterval",
                      {"INPUT": network, "INTERVAL": CONFIG["densify_interval_m"],
                       "OUTPUT": gpkg("walk_network_densified")}, log)["OUTPUT"]
    run("native:extractbyexpression", {"INPUT": network, "EXPRESSION": REVIEW_EXPR,
                                       "OUTPUT": gpkg("review_candidates")}, log)

    print("4. 起点とネットワークの接続距離を確認")
    sl = run("native:shortestline", {"SOURCE": origin, "DESTINATION": network, "METHOD": 0, "NEIGHBORS": 1,
                                     "OUTPUT": gpkg("origin_to_network")}, log)["OUTPUT"]
    # OSM 側にも "distance" タグの列があり得るので、接続距離は線の長さから別名の列で求める
    sl = run("native:fieldcalculator", {"INPUT": sl, "FIELD_NAME": "snap_m", "FIELD_TYPE": 0, "FIELD_PRECISION": 3,
                                        "FORMULA": "length($geometry)", "OUTPUT": gpkg("origin_to_network_len")}, log)["OUTPUT"]
    snap = read_csv(run("native:savefeatures", {"INPUT": sl, "OUTPUT": str(out / "origin_to_network.csv")}, log)["OUTPUT"])[0]
    snap_m = float(snap["snap_m"])
    log["origin_to_network_m"] = snap_m
    print(f"   最寄りの歩行可能な道まで {snap_m:.1f} m（highway={snap.get('highway')}, name={snap.get('name_2') or '(なし)'}）")
    keys = ("highway", "footway", "bridge", "tunnel", "layer", "level", "indoor", "covered", "opening_hours", "other_tags")
    log["origin_snap_way"] = {k: snap[k] for k in ("osm_id", "full_id", *keys) if snap.get(k)}
    print(f"   接続先: {log['origin_snap_way']}")
    print("   ※デッキ（2階）上の起点なら、接続先に bridge / layer=1 などがあるか確認する")
    if snap_m > 20:
        print("   ⚠ 20 m を超えています。起点の位置や、近くの道が除外されていないか確認してください。")

    print("5. QNEAT3 で徒歩到達圏")
    # QNEAT3 の "Iso-Area as Polygons" は matplotlib 3.8 以上の API を使うため、
    # QGIS 3.40 同梱の matplotlib 3.3 では失敗する（ContourSet.get_paths がない）。
    # そこで QNEAT3 の "Iso-Area as Interpolation"（到達コストのラスタ）を作り、
    # それを GDAL の等値線ポリゴン化で面にする。到達コスト計算そのものは QNEAT3 が行う。
    common = {"INPUT": network, "START_POINTS": origin, "ID_FIELD": "oid", "MAX_DIST": dist,
              "DEFAULT_SPEED": CONFIG["walk_speed_kmh"],
              **{k: v for k, v in CONFIG["qneat3"].items() if k != "CELL_SIZE"}}
    run("qneat3:isoareaaspointcloudfromlayer",
        {**common, "OUTPUT": gpkg(f"iso_{CONFIG['minutes']}min_pointcloud")}, log)
    # QNEAT3 の Polygons/Contours は内部で上限を 1.1 倍にした点群から補間し、その中に等値線を引く
    # （IsoAreaAsPolygonsFromLayer.py: calcIsoPoints(..., max_dist+(max_dist*0.1))）。同じにしないと、
    # 上限ちょうどの等値線が点群の外枠（凸包・外接矩形）になってしまう。
    cost = run("qneat3:isoareaasinterpolationfromlayer",
               {**common, "MAX_DIST": dist * 1.1, "CELL_SIZE": CONFIG["qneat3"]["CELL_SIZE"],
                "OUTPUT": str(out / f"iso_{CONFIG['minutes']}min_cost.tif")}, log)["OUTPUT"]
    bands = run("gdal:contour_polygon", {"INPUT": cost, "BAND": 1, "INTERVAL": dist,
                                         "FIELD_NAME_MIN": "cost_min", "FIELD_NAME_MAX": "cost_max",
                                         "OUTPUT": gpkg(f"iso_{CONFIG['minutes']}min_bands")}, log)["OUTPUT"]
    log["iso_method"] = (f"QNEAT3 Iso-Area as Interpolation (from Layer, MAX_DIST {dist * 1.1:.0f} m = 1.1倍) → GDAL contour_polygon "
                         f"(interval {dist:.0f} m) → cost_max <= {dist:.0f} を抽出・融合")
    iso_sel = run("native:extractbyexpression", {"INPUT": bands,
                                                 "EXPRESSION": f"\"cost_max\" <= {dist}",
                                                 "OUTPUT": tmp("t3")}, log)
    iso_poly = run("native:dissolve", {"INPUT": iso_sel["OUTPUT"], "OUTPUT": gpkg(f"iso_{CONFIG['minutes']}min")}, log)["OUTPUT"]

    print("6. 半径800mの円")
    circle = run("native:buffer", {"INPUT": origin, "DISTANCE": CONFIG["circle_radius_m"],
                                   "SEGMENTS": CONFIG["buffer_segments"],
                                   "OUTPUT": gpkg(f"circle_{CONFIG['circle_radius_m']}")}, log)["OUTPUT"]

    print("7. 重ね合わせと面積")
    only_circle = run("native:difference", {"INPUT": circle, "OVERLAY": iso_poly,
                                            "OUTPUT": gpkg("circle_minus_iso")}, log)["OUTPUT"]
    only_iso = run("native:difference", {"INPUT": iso_poly, "OVERLAY": circle,
                                         "OUTPUT": gpkg("iso_minus_circle")}, log)["OUTPUT"]
    areas = {
        f"円 半径{CONFIG['circle_radius_m']}m": area_of(circle, out, "circle", log),
        f"徒歩{CONFIG['minutes']}分圏（QNEAT3）": area_of(iso_poly, out, "iso", log),
        "円に入るが到達圏外": area_of(only_circle, out, "circle_minus_iso", log),
        "到達圏だが円の外": area_of(only_iso, out, "iso_minus_circle", log),
    }
    base = list(areas.values())[0]
    with open(out / "area_table.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["範囲", "面積_m2", "面積_km2", "円に対する比率_%"])
        for k, v in areas.items():
            w.writerow([k, round(v, 1), round(v / 1e6, 4), round(v / base * 100, 1)])
    for k, v in areas.items():
        print(f"   {k:<20} {v:>12,.0f} m²  ({v / base * 100:5.1f}%)")

    log["areas_m2"] = areas
    log["run_finished"] = dt.datetime.now().astimezone().isoformat()
    log_path = ROOT / "logs" / f"{out.name}.json"
    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n出力: {out}\n記録: {log_path}")


if __name__ == "__main__":
    main()
