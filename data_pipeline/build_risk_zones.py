"""Build backend/app/data/risk_zones.geojson from the sources listed in pipeline.yaml.

    python data_pipeline/build_risk_zones.py          # build, validate, write
    python data_pipeline/build_risk_zones.py --check  # fail if the committed file is out of date

Nothing is written when validation fails. Same input gives the same file.
"""
import argparse
from pathlib import Path
import sys

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from readers import READERS  # noqa: E402
from zones import PipelineError, build_collection, check, dumps  # noqa: E402


def build(config_path: Path) -> tuple[str, Path]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    records: list[dict] = []
    for source in config["sources"]:
        reader = READERS.get(source["reader"])
        if reader is None:
            raise PipelineError(f"unknown reader: {source['reader']}")
        options = {k: v for k, v in source.items() if k not in ("reader", "path")}
        records.extend(reader(base / source["path"], **options))
    collection = build_collection(records, config["default_radius_m"], config.get("flood_tiers"))
    check(collection)
    return dumps(collection), (base / config["output"]).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=HERE / "pipeline.yaml")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        text, output = build(args.config)
    except PipelineError as exc:
        print(f"RISK_ZONES_FAILED: {exc}", file=sys.stderr)
        return 1
    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else ""
        if current != text:
            print(f"RISK_ZONES_OUT_OF_DATE: {output}", file=sys.stderr)
            return 1
        print("RISK_ZONES_UP_TO_DATE")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8", newline="\n")
    print(f"RISK_ZONES_OK: {text.count(chr(10)) - 2} zones -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
