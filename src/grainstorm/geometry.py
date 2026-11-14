"""Small-field GeoJSON polygon validation and approximate geometry."""
from __future__ import annotations

from math import cos, hypot, radians
from typing import Any


EARTH_RADIUS_M = 6_371_008.8


def polygon_summary(coordinates: list[list[list[float]]]) -> dict[str, Any]:
    """Return centroid and local equal-distance area for one outer GeoJSON ring."""
    if not isinstance(coordinates, list) or len(coordinates) != 1:
        raise ValueError("field_polygon must contain exactly one outer ring and no holes.")
    ring = coordinates[0]
    if not isinstance(ring, list) or len(ring) < 4:
        raise ValueError("field_polygon outer ring needs at least four positions including closure.")
    points = []
    for index, position in enumerate(ring):
        if not isinstance(position, list) or len(position) != 2:
            raise ValueError(f"field_polygon position {index} must be [longitude, latitude].")
        longitude, latitude = position
        if isinstance(longitude, bool) or isinstance(latitude, bool):
            raise ValueError("field_polygon coordinates must be numbers.")
        try:
            longitude, latitude = float(longitude), float(latitude)
        except (TypeError, ValueError) as exc:
            raise ValueError("field_polygon coordinates must be numbers.") from exc
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("field_polygon contains an invalid longitude or latitude.")
        points.append((longitude, latitude))
    if points[0] != points[-1]:
        raise ValueError("field_polygon outer ring must be closed: first and last positions must match.")
    unique = points[:-1]
    if len(set(unique)) < 3:
        raise ValueError("field_polygon needs at least three distinct vertices.")
    mean_lat = sum(point[1] for point in unique) / len(unique)
    scale_x = EARTH_RADIUS_M * cos(radians(mean_lat)) * radians(1)
    scale_y = EARTH_RADIUS_M * radians(1)
    projected = [(lon * scale_x, lat * scale_y) for lon, lat in points]
    twice_area = sum(projected[i][0] * projected[i + 1][1] -
                     projected[i + 1][0] * projected[i][1]
                     for i in range(len(projected) - 1))
    if abs(twice_area) < 1:
        raise ValueError("field_polygon area is too small or degenerate.")
    centroid_x = sum((projected[i][0] + projected[i + 1][0]) *
                     (projected[i][0] * projected[i + 1][1] - projected[i + 1][0] * projected[i][1])
                     for i in range(len(projected) - 1)) / (3 * twice_area)
    centroid_y = sum((projected[i][1] + projected[i + 1][1]) *
                     (projected[i][0] * projected[i + 1][1] - projected[i + 1][0] * projected[i][1])
                     for i in range(len(projected) - 1)) / (3 * twice_area)
    area_m2 = abs(twice_area) / 2
    perimeter_m = sum(hypot(projected[i + 1][0] - projected[i][0],
                            projected[i + 1][1] - projected[i][1])
                      for i in range(len(projected) - 1))
    return {
        "centroid": {"latitude": centroid_y / scale_y, "longitude": centroid_x / scale_x},
        "area_m2": round(area_m2, 2),
        "area_ha": round(area_m2 / 10_000, 4),
        "area_acres": round(area_m2 / 4_046.8564224, 4),
        "perimeter_m": round(perimeter_m, 2),
        "method": "local equirectangular approximation; suitable for farm-scale polygons",
    }
