# 動作確認用の合成ネットワーク（実在の町田の道ではない）。100m格子で、y=+100〜+200m の間に「線路」相当の切れ目を作り、x=+600m の歩道橋1か所だけ通れる。
import math, sys, json
out = sys.argv[1]
LON0, LAT0 = 139.4459, 35.5419
def ll(x, y):
    return LON0 + x / (111320 * math.cos(math.radians(LAT0))), LAT0 + y / 110574
nodes, ways = {}, []
def node(x, y):
    k = (round(x), round(y))
    if k not in nodes: nodes[k] = len(nodes) + 1
    return nodes[k]
R = 1500; step = 100
for y in range(-R, R + 1, step):   # 東西の道（格子）
    ways.append(([node(x, y) for x in range(-R, R + 1, step)], {"highway": "residential"}))
for x in range(-R, R + 1, step):   # 南北の道: y=100 と y=200 の間を切る（x=600 以外）
    south = [node(x, y) for y in range(-R, 101, step)]
    north = [node(x, y) for y in range(200, R + 1, step)]
    if x == 600:
        ways.append((south + north, {"highway": "footway", "bridge": "yes"}))
    else:
        ways.append((south, {"highway": "residential"})); ways.append((north, {"highway": "residential"}))
# 除外されるべき道: 高速道路と foot=no の近道（南北を直結してしまう）
ways.append(([node(-50, 100), node(-50, 200)], {"highway": "motorway"}))
ways.append(([node(50, 100), node(50, 200)], {"highway": "service", "foot": "no"}))
with open(out, "w") as f:
    f.write('<?xml version="1.0"?>\n<osm version="0.6" generator="synthetic-test">\n')
    for (x, y), i in nodes.items():
        lon, lat = ll(x, y); f.write(f'<node id="{i}" lat="{lat:.8f}" lon="{lon:.8f}" version="1"/>\n')
    for j, (nds, tags) in enumerate(ways, 1):
        f.write(f'<way id="{j}" version="1">' + "".join(f'<nd ref="{n}"/>' for n in nds)
                + "".join(f'<tag k="{k}" v="{v}"/>' for k, v in tags.items()) + "</way>\n")
    f.write("</osm>\n")
lon, lat = ll(0, 0)
json.dump({"type": "FeatureCollection", "crs": {"type":"name","properties":{"name":"urn:ogc:def:crs:OGC:1.3:CRS84"}},
  "features": [{"type": "Feature", "properties": {"name": "synthetic origin"}, "geometry": {"type": "Point", "coordinates": [lon, lat + 3/110574]}}]},
  open(out.replace(".osm", "_origin.geojson"), "w"))
