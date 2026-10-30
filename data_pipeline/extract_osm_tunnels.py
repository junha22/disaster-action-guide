"""Build sources/osm_tunnels.geojson from the Gwangju OSM extract. Manual, like build_valhalla_tiles.ps1.

    python data_pipeline/extract_osm_tunnels.py --osmium <path to osmium.exe>

Keeps car-road tunnels. Each one gets a block point: the spot on the way farthest from every surface
road, so excluding it from routing cannot close a road that runs over or beside the tunnel. The middle
of an underpass is usually right under the road it crosses (design.md 4.5).
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import zones  # noqa: E402,F401  (puts backend/ on sys.path)
from shapely import STRtree  # noqa: E402
from shapely.geometry import shape  # noqa: E402

from app.risk.geo import to_metric, to_wgs84  # noqa: E402

TUNNEL_ROADS = {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary",
                "tertiary_link", "unclassified", "residential"}
SURFACE_ROADS = TUNNEL_ROADS | {"motorway", "motorway_link", "living_street", "service"}
BLOCK_FRACTIONS = [i / 20 for i in range(1, 20)]
ATTRIBUTION = "© OpenStreetMap contributors (ODbL 1.0), https://www.openstreetmap.org/copyright"
DIGITS = 6


def tunnel_features(features: list[dict]) -> list[dict]:
    """Car tunnels from `osmium export` features, each with its block point, in OSM id order."""
    lines = [(f, to_metric(shape(f["geometry"]))) for f in features if f["geometry"]["type"] == "LineString"]
    surface = [m for f, m in lines
               if f["properties"].get("highway") in SURFACE_ROADS and f["properties"].get("tunnel") != "yes"]
    tree = STRtree(surface)
    result = []
    for feature, metric in lines:
        props = feature["properties"]
        if props.get("tunnel") != "yes" or props.get("highway") not in TUNNEL_ROADS:
            continue

        def clearance(fraction: float) -> float:
            point = metric.interpolate(fraction, normalized=True)
            return surface[tree.nearest(point)].distance(point)

        best = max(BLOCK_FRACTIONS, key=lambda f: (round(clearance(f), 1), -abs(f - 0.5)))
        point = to_wgs84(metric.interpolate(best, normalized=True))
        result.append({"type": "Feature",
                       "properties": {"osm_id": feature["id"], "highway": props["highway"], "name": props.get("name"),
                                      "block_point": [round(point.x, DIGITS), round(point.y, DIGITS)],
                                      "block_clearance_m": round(clearance(best), 1)},
                       "geometry": feature["geometry"]})
    return sorted(result, key=lambda f: int(f["properties"]["osm_id"][1:]))


def dumps(features: list[dict]) -> str:
    lines = [json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in features]
    return (f'{{"type":"FeatureCollection","attribution":{json.dumps(ATTRIBUTION, ensure_ascii=False)},"features":[\n'
            + ",\n".join(lines) + "\n]}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--osmium", default="osmium")
    parser.add_argument("--pbf", type=Path, default=HERE.parent / ".local-data/valhalla/gwangju.osm.pbf")
    parser.add_argument("--output", type=Path, default=HERE / "sources/osm_tunnels.geojson")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as folder:
        roads = Path(folder) / "roads.osm.pbf"
        exported = Path(folder) / "roads.geojson"
        subprocess.run([args.osmium, "tags-filter", str(args.pbf), "w/highway", "-o", str(roads), "--overwrite"],
                       check=True)
        subprocess.run([args.osmium, "export", str(roads), "-o", str(exported), "--overwrite", "-f", "geojson",
                        "--add-unique-id=type_id", "--geometry-types=linestring"], check=True)
        features = json.loads(exported.read_text(encoding="utf-8"))["features"]
    result = tunnel_features(features)
    args.output.write_text(dumps(result), encoding="utf-8", newline="\n")
    print(f"OSM_TUNNELS_OK: {len(result)} ways -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
