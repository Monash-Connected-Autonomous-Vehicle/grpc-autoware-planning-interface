import math
import xml.etree.ElementTree as ET
from pathlib import Path


def _read_simple_yaml_kv(path: Path):
    """
    Minimal YAML key:value reader for the small Autoware map yaml files.
    Assumes no nesting.
    """
    if not path.exists():
        return {}
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        k, v = stripped.split(":", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def _read_map_origin_lat_lon(map_dir: Path):
    """
    Reads origin from Autoware-style map_config.yaml.
    Falls back to (0,0) if not found (caller should validate).
    """
    config_path = map_dir / "map_config.yaml"
    origin_lat = None
    origin_lon = None
    if not config_path.exists():
        return origin_lat, origin_lon

    for line in config_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("latitude:"):
            try:
                origin_lat = float(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif stripped.startswith("longitude:"):
            try:
                origin_lon = float(stripped.split(":", 1)[1].strip())
            except ValueError:
                pass
    return origin_lat, origin_lon


def _read_map_projector_info(map_dir: Path):
    """
    Reads Autoware-style map_projector_info.yaml (projector_type, mgrs_grid, ...).
    Returns {} if missing.
    """
    return _read_simple_yaml_kv(map_dir / "map_projector_info.yaml")


def latlon_to_local_xy(latitude: float, longitude: float, origin_lat: float, origin_lon: float):
    """
    Local tangent-plane approximation (equirectangular).
    Returns x,y in meters relative to origin (east,north).
    """
    earth_radius_m = 6378137.0
    lat_rad = math.radians(latitude)
    lon_rad = math.radians(longitude)
    origin_lat_rad = math.radians(origin_lat)
    origin_lon_rad = math.radians(origin_lon)

    x = (lon_rad - origin_lon_rad) * math.cos((lat_rad + origin_lat_rad) / 2.0) * earth_radius_m
    y = (lat_rad - origin_lat_rad) * earth_radius_m
    return x, y


def closest_point_on_segment(px, py, ax, ay, bx, by):
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    denom = abx * abx + aby * aby
    if denom == 0.0:
        return ax, ay, 0.0
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / denom))
    return ax + t * abx, ay + t * aby, t


def polyline_lengths(points):
    lengths = [0.0]
    for i in range(1, len(points)):
        ax, ay = points[i - 1]
        bx, by = points[i]
        lengths.append(lengths[-1] + math.hypot(bx - ax, by - ay))
    return lengths


def sample_polyline(points, sample_count):
    if len(points) < 2 or sample_count < 2:
        return points[:]

    lengths = polyline_lengths(points)
    total = lengths[-1]
    if total == 0.0:
        return [points[0]] * sample_count

    samples = []
    targets = [total * i / (sample_count - 1) for i in range(sample_count)]
    seg_index = 0

    for target in targets:
        while seg_index < len(lengths) - 2 and lengths[seg_index + 1] < target:
            seg_index += 1

        start_len = lengths[seg_index]
        end_len = lengths[seg_index + 1]
        ratio = 0.0 if end_len == start_len else (target - start_len) / (end_len - start_len)
        ax, ay = points[seg_index]
        bx, by = points[seg_index + 1]
        samples.append((ax + ratio * (bx - ax), ay + ratio * (by - ay)))

    return samples


def yaw_to_quaternion(yaw: float):
    half_yaw = yaw * 0.5
    return 0.0, 0.0, math.sin(half_yaw), math.cos(half_yaw)


class LaneletMap:
    def __init__(self, osm_path: Path):
        self.osm_path = osm_path
        self.nodes = {}  # node_id -> (x,y) in map frame (meters)
        self.raw_latlon = {}  # node_id -> (lat,lon) for debugging
        self.lanelets = []
        self.origin_lat = None
        self.origin_lon = None
        self._lanelet2_map = None
        self._lanelet2 = None
        self._load()

    def _load(self):
        map_dir = self.osm_path.parent
        self.origin_lat, self.origin_lon = _read_map_origin_lat_lon(map_dir)
        if self.origin_lat is None or self.origin_lon is None:
            raise RuntimeError(
                f"Could not read map origin lat/lon from {map_dir / 'map_config.yaml'}; "
                "needed to project lanelet OSM lat/lon into map x/y."
            )

        # Try to load via Lanelet2 python bindings (preferred).
        # This enables robust nearest queries + correct orientation from the lane direction.
        self._try_load_lanelet2_map(map_dir)

        tree = ET.parse(self.osm_path)
        root = tree.getroot()

        for node in root.findall("node"):
            node_id = node.attrib["id"]
            lat = float(node.attrib["lat"])
            lon = float(node.attrib["lon"])
            self.raw_latlon[node_id] = (lat, lon)
            x, y = latlon_to_local_xy(lat, lon, self.origin_lat, self.origin_lon)
            self.nodes[node_id] = (x, y)

        for relation in root.findall("relation"):
            tags = {tag.attrib["k"]: tag.attrib["v"] for tag in relation.findall("tag")}
            if tags.get("type") != "lanelet":
                continue
            left_way = None
            right_way = None
            for member in relation.findall("member"):
                if member.attrib.get("role") == "left" and member.attrib.get("type") == "way":
                    left_way = member.attrib.get("ref")
                elif member.attrib.get("role") == "right" and member.attrib.get("type") == "way":
                    right_way = member.attrib.get("ref")
            if left_way and right_way:
                self.lanelets.append((left_way, right_way, tags))

        self.ways = {}
        for way in root.findall("way"):
            refs = [nd.attrib["ref"] for nd in way.findall("nd")]
            self.ways[way.attrib["id"]] = refs

    def _try_load_lanelet2_map(self, map_dir: Path):
        """
        Best-effort load through Lanelet2 python bindings.
        If unavailable (or projection class missing), we keep pure-python fallback.
        """
        try:
            import lanelet2  # type: ignore

            self._lanelet2 = lanelet2
        except Exception:
            self._lanelet2 = None
            self._lanelet2_map = None
            return

        projector_info = _read_map_projector_info(map_dir)
        projector_type = (projector_info.get("projector_type") or "").upper()
        mgrs_grid = projector_info.get("mgrs_grid")

        origin = self._lanelet2.io.Origin(self.origin_lat, self.origin_lon)

        projector = None
        # Autoware MGRS projector (preferred when map says MGRS).
        if projector_type == "MGRS" and mgrs_grid:
            projector = self._try_make_mgrs_projector(origin, mgrs_grid)

        # Fallback: use Lanelet2's standard UTM projector at the given origin.
        if projector is None:
            try:
                projector = self._lanelet2.projection.UtmProjector(origin)
            except Exception:
                projector = None

        if projector is None:
            self._lanelet2_map = None
            return

        try:
            self._lanelet2_map = self._lanelet2.io.load(str(self.osm_path), projector)
        except Exception:
            self._lanelet2_map = None

    def _try_make_mgrs_projector(self, origin, mgrs_grid: str):
        """
        Tries to construct Autoware's MGRS projector from Python bindings.
        Returns projector or None.
        """
        # Autoware provides `autoware_lanelet2_extension_python` in many setups.
        # Naming varies slightly across versions; we try a few common spellings.
        try:
            import autoware_lanelet2_extension_python as aw_ext_py  # type: ignore
        except Exception:
            return None

        candidates = []
        # Common module locations
        for mod_name in ("projection", "autoware_lanelet2_extension_python.projection"):
            mod = getattr(aw_ext_py, "projection", None) if mod_name == "projection" else None
            if mod is None and mod_name.endswith(".projection"):
                try:
                    mod = __import__(mod_name, fromlist=["*"])
                except Exception:
                    mod = None
            if mod is not None:
                candidates.append(mod)

        class_names = ("MGRSProjector", "MgrsProjector", "MGRSProjectorNode")  # last one is unlikely but harmless
        for mod in candidates:
            for cls_name in class_names:
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    continue
                try:
                    # Most bindings accept (origin, mgrs_grid) or just (mgrs_grid).
                    try:
                        return cls(origin, mgrs_grid)
                    except TypeError:
                        return cls(mgrs_grid)
                except Exception:
                    continue
        return None

    def nearest_valid_position(self, x: float, y: float):
        """
        Returns the nearest valid pose on the lane, facing the lane direction.

        Shape matches existing `find_nearest` return:
          {"x": float, "y": float, "yaw": float, "dist2": float, "tags": dict}
        Returns None if nothing can be resolved.
        """
        if self._lanelet2_map is None or self._lanelet2 is None:
            return self.find_nearest(x, y)

        ll2 = self._lanelet2
        q = ll2.core.BasicPoint2d(x, y)
        nearest = ll2.geometry.findNearest(self._lanelet2_map.laneletLayer, q, 1)
        if not nearest:
            return None

        # `findNearest` returns [(dist, primitive), ...]
        dist, lanelet = nearest[0]

        # Project query onto lanelet centerline using arc coordinates.
        centerline2d = ll2.geometry.to2D(lanelet.centerline)
        arc = ll2.geometry.toArcCoordinates(centerline2d, q)
        s = float(getattr(arc, "length", 0.0))

        # Clamp for safety.
        total_len = float(ll2.geometry.length(centerline2d))
        if total_len <= 0.0:
            return None
        s = max(0.0, min(total_len, s))

        try:
            proj_pt = ll2.geometry.fromArcCoordinates(centerline2d, arc)
        except Exception:
            proj_pt = ll2.geometry.fromArcCoordinates(centerline2d, s, 0.0)

        # Compute forward yaw from the local tangent direction.
        eps = 0.5  # meters
        s1 = max(0.0, s - eps)
        s2 = min(total_len, s + eps)
        p1 = ll2.geometry.interpolatedPointAtDistance(centerline2d, s1)
        p2 = ll2.geometry.interpolatedPointAtDistance(centerline2d, s2)
        yaw = math.atan2(p2.y - p1.y, p2.x - p1.x)

        dx = x - proj_pt.x
        dy = y - proj_pt.y
        return {
            "x": float(proj_pt.x),
            "y": float(proj_pt.y),
            "yaw": float(yaw),
            "dist2": float(dx * dx + dy * dy),
            "tags": {
                "lanelet_id": int(getattr(lanelet, "id", 0)),
            },
        }

    def find_nearest(self, x: float, y: float):
        best = None
        best_dbg = None
        lanelet_best_segments = []
        for lanelet_index, (left_way, right_way, tags) in enumerate(self.lanelets):
            left_refs = self.ways.get(left_way, [])
            right_refs = self.ways.get(right_way, [])
            if len(left_refs) < 2 or len(right_refs) < 2:
                continue

            left_polyline = [self.nodes[node_id] for node_id in left_refs if node_id in self.nodes]
            right_polyline = [self.nodes[node_id] for node_id in right_refs if node_id in self.nodes]
            if len(left_polyline) < 2 or len(right_polyline) < 2:
                continue

            sample_count = max(len(left_polyline), len(right_polyline), 8)
            left_samples = sample_polyline(left_polyline, sample_count)
            right_samples = sample_polyline(right_polyline, sample_count)
            centerline = [
                ((lx + rx) / 2.0, (ly + ry) / 2.0)
                for (lx, ly), (rx, ry) in zip(left_samples, right_samples)
            ]

            lanelet_best = None
            for i in range(len(centerline) - 1):
                ax, ay = centerline[i]
                bx, by = centerline[i + 1]
                sx, sy, _ = closest_point_on_segment(x, y, ax, ay, bx, by)
                dist2 = (x - sx) ** 2 + (y - sy) ** 2
                yaw = math.atan2(by - ay, bx - ax)
                if lanelet_best is None or dist2 < lanelet_best["dist2"]:
                    lanelet_best = {
                        "lanelet_index": lanelet_index,
                        "left_way": left_way,
                        "right_way": right_way,
                        "dist2": dist2,
                        "ax": ax,
                        "ay": ay,
                        "bx": bx,
                        "by": by,
                        "sx": sx,
                        "sy": sy,
                        "yaw": yaw,
                    }
                if best is None or dist2 < best["dist2"]:
                    best = {
                        "x": sx,
                        "y": sy,
                        "yaw": yaw,
                        "dist2": dist2,
                        "tags": tags,
                    }
                    best_dbg = dict(lanelet_best) if lanelet_best is not None else None

            if lanelet_best is not None:
                lanelet_best_segments.append(lanelet_best)

        return best
