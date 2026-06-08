from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import matplotlib.pyplot as plt
import numpy as np
import requests
import xarray as xr
from netCDF4 import Dataset
from pyproj import CRS, Transformer


VNIR_CHANNELS = [
    "vis_04",
    "vis_05",
    "vis_06",
    "vis_08",
    "vis_09",
    "nir_13",
    "nir_16",
    "nir_22",
]

THERMAL_CHANNELS = [
    "ir_38",
    "wv_63",
    "wv_73",
    "ir_87",
    "ir_97",
    "ir_105",
    "ir_123",
    "ir_133",
]

VISIBLE_CHANNEL = "vis_06"
THERMAL_CHANNEL = "ir_105"
PLOT_CHANNELS = [VISIBLE_CHANNEL, THERMAL_CHANNEL]
AU_KM = 149_597_870.7

ITALY_BBOX = {
    "lon_min": 6.0,
    "lon_max": 19.0,
    "lat_min": 36.0,
    "lat_max": 48.0,
}

ROME_BBOX = {
    "lon_min": 12.20,
    "lon_max": 12.85,
    "lat_min": 41.65,
    "lat_max": 42.10,
}

CENTRAL_ITALY_BBOX = {
    "lon_min": 10.50,
    "lon_max": 14.50,
    "lat_min": 40.50,
    "lat_max": 43.30,
}

TARGET_LAT = 41.94466461616052
TARGET_LON = 12.522143138431044

BODY_GLOB = "*CHK-BODY*.nc"
COASTLINE_GEOJSON_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_coastline.geojson"
)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
CHUNK_TOKEN_RE = re.compile(r"_(\d{4})\.nc$")


@dataclass(frozen=True)
class CropChunk:
    file_token: str
    row_slice_start: int
    row_slice_stop: int
    x_slice_start: int
    x_slice_stop: int
    output_row_start: int
    output_row_stop: int


@dataclass(frozen=True)
class CropPlan:
    channel: str
    x: np.ndarray
    y: np.ndarray
    chunks: tuple[CropChunk, ...]


def resolve_base_dir(dataset_dirname: str) -> Path:
    candidates = [
        Path.cwd() / dataset_dirname,
        Path.cwd().parent / dataset_dirname,
        Path(r"C:/Users/Daniele.LOKI/Documents/medicanes/MTG_data") / dataset_dirname,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    tried = "\n".join(str(path) for path in candidates)
    raise FileNotFoundError(
        f"Dataset non trovato. Working directory attuale: {Path.cwd()}\n"
        f"Percorsi provati:\n{tried}"
    )


def list_products(base_dir: Path) -> list[Path]:
    products = sorted(path for path in base_dir.iterdir() if path.is_dir())
    if not products:
        raise FileNotFoundError(f"Nessun prodotto trovato in {base_dir}")
    return products


def list_body_files(product_dir: Path) -> list[Path]:
    files = sorted(product_dir.glob(BODY_GLOB))
    if not files:
        raise FileNotFoundError(f"Nessun file {BODY_GLOB} trovato in {product_dir}")
    return files


def chunk_token(nc_file: Path) -> str:
    match = CHUNK_TOKEN_RE.search(nc_file.name)
    if not match:
        raise ValueError(f"Impossibile ricavare il token chunk da {nc_file.name}")
    return match.group(1)


def body_files_by_token(product_dir: Path) -> dict[str, Path]:
    return {chunk_token(nc_file): nc_file for nc_file in list_body_files(product_dir)}


def load_group(nc_file: Path, group: str) -> xr.Dataset:
    with xr.open_dataset(nc_file, group=group, engine="netcdf4") as ds:
        return ds.load()


def load_channel_measured(nc_file: Path, channel: str) -> xr.Dataset:
    return load_group(nc_file, f"data/{channel}/measured")


def earth_sun_distance_au(nc_file: Path) -> float:
    with Dataset(nc_file) as root:
        celestial = root.groups["state"].groups["celestial"]
        distance = celestial.variables["earth_sun_distance"][:]
        return float(np.asarray(distance, dtype="float64").mean()) / AU_KM


def projection_metadata(nc_file: Path) -> dict:
    root = Dataset(nc_file)
    try:
        proj = root.groups["data"].variables["mtg_geos_projection"]
        return {name: getattr(proj, name) for name in proj.ncattrs()}
    finally:
        root.close()


@lru_cache(maxsize=32)
def _projection_transformer_cached(nc_file: str) -> tuple[Transformer, float]:
    meta = projection_metadata(Path(nc_file))
    h = float(meta["perspective_point_height"])
    a = float(meta["semi_major_axis"])
    b = float(meta["semi_minor_axis"])
    lon_0 = float(meta["longitude_of_projection_origin"])
    sweep = str(meta["sweep_angle_axis"])
    crs_geos = CRS.from_proj4(
        f"+proj=geos +h={h} +lon_0={lon_0} +sweep={sweep} +a={a} +b={b} +units=m +no_defs"
    )
    transformer = Transformer.from_crs("EPSG:4326", crs_geos, always_xy=True)
    return transformer, h


def projection_transformer(nc_file: Path) -> tuple[Transformer, float]:
    return _projection_transformer_cached(str(Path(nc_file).resolve()))


def calibrated_image_from_dataset(
    ds: xr.Dataset, channel: str, earth_sun_distance_au_value: float
) -> np.ndarray:
    image = ds["effective_radiance"].astype("float64").values
    image = np.where(np.isfinite(image) & (image > 0), image, np.nan)

    if channel in VNIR_CHANNELS:
        solar_irradiance = float(ds["channel_effective_solar_irradiance"])
        reflectance = np.pi * image * (earth_sun_distance_au_value**2) / solar_irradiance
        return np.clip(reflectance, 0.0, 1.2)

    wn = float(ds["radiance_to_bt_conversion_coefficient_wavenumber"])
    c1 = float(ds["radiance_to_bt_conversion_constant_c1"])
    c2 = float(ds["radiance_to_bt_conversion_constant_c2"])
    a = float(ds["radiance_to_bt_conversion_coefficient_a"])
    b = float(ds["radiance_to_bt_conversion_coefficient_b"])
    planck_temperature = (c2 * wn) / np.log1p((c1 * (wn**3)) / image)
    return a * planck_temperature + b


def _scalar_from_group(group, name: str) -> float:
    return float(np.asarray(group.variables[name][...]).item())


def calibrated_image_from_group(
    group, channel: str, image: np.ndarray, earth_sun_distance_au_value: float
) -> np.ndarray:
    if np.ma.isMaskedArray(image):
        image = image.filled(np.nan)
    image = np.asarray(image, dtype="float64")
    image = np.where(np.isfinite(image) & (image > 0), image, np.nan)

    if channel in VNIR_CHANNELS:
        solar_irradiance = _scalar_from_group(group, "channel_effective_solar_irradiance")
        reflectance = np.pi * image * (earth_sun_distance_au_value**2) / solar_irradiance
        return np.clip(reflectance, 0.0, 1.2)

    wn = _scalar_from_group(group, "radiance_to_bt_conversion_coefficient_wavenumber")
    c1 = _scalar_from_group(group, "radiance_to_bt_conversion_constant_c1")
    c2 = _scalar_from_group(group, "radiance_to_bt_conversion_constant_c2")
    a = _scalar_from_group(group, "radiance_to_bt_conversion_coefficient_a")
    b = _scalar_from_group(group, "radiance_to_bt_conversion_coefficient_b")
    planck_temperature = (c2 * wn) / np.log1p((c1 * (wn**3)) / image)
    return a * planck_temperature + b


def robust_limits(image: np.ndarray, lower: float = 2.0, upper: float = 98.0) -> tuple[float, float]:
    finite = image[np.isfinite(image)]
    if finite.size == 0:
        return 0.0, 1.0
    vmin, vmax = np.nanpercentile(finite, [lower, upper])
    if not np.isfinite(vmin) or not np.isfinite(vmax) or math.isclose(vmin, vmax):
        vmin = float(np.nanmin(finite))
        vmax = float(np.nanmax(finite))
    if math.isclose(vmin, vmax):
        vmax = vmin + 1.0
    return float(vmin), float(vmax)


def channel_label(channel: str) -> tuple[str, str]:
    if channel in VNIR_CHANNELS:
        return "Reflectance", "gray"
    return "Brightness temperature [K]", "inferno"


def channel_title(channel: str) -> str:
    if channel == "vis_06":
        return "vis_06 (visible)"
    if channel == "ir_105":
        return "ir_105 (window IR, ~10.5 um)"
    return channel


def normalize_image(image: np.ndarray, lower: float = 2.0, upper: float = 98.0) -> np.ndarray:
    vmin, vmax = robust_limits(image, lower=lower, upper=upper)
    norm = (image - vmin) / (vmax - vmin)
    return np.clip(norm, 0.0, 1.0)


def ir105_rgb(ir_image: np.ndarray) -> np.ndarray:
    ir_clipped = np.clip(ir_image, 210.0, 300.0)
    ir_norm = 1.0 - (ir_clipped - 210.0) / (300.0 - 210.0)
    cmap = plt.get_cmap("turbo")
    rgb = cmap(ir_norm)[..., :3]
    return np.clip(rgb, 0.0, 1.0)


def upsample_like(source_image: np.ndarray, target_shape: tuple[int, int]) -> np.ndarray:
    if source_image.shape == target_shape:
        return source_image
    target_y, target_x = target_shape
    src_y, src_x = source_image.shape
    y_idx = np.linspace(0, src_y - 1, target_y).round().astype(int)
    x_idx = np.linspace(0, src_x - 1, target_x).round().astype(int)
    return source_image[y_idx][:, x_idx]


def sandwich_composite(vis_image: np.ndarray, ir_image: np.ndarray) -> np.ndarray:
    ir_image = upsample_like(ir_image, vis_image.shape)
    vis_norm = normalize_image(vis_image, lower=1.0, upper=99.0)
    ir_rgb = ir105_rgb(ir_image)
    texture = 0.40 + 0.85 * vis_norm
    composite = ir_rgb * texture[..., None]
    return np.clip(composite, 0.0, 1.0)


def plot_rgb_image(ax, rgb: np.ndarray, title: str) -> None:
    ax.imshow(np.clip(rgb, 0.0, 1.0))
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])


def mosaic_channel(product_dir: Path, channel: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    body_files = list_body_files(product_dir)
    d_au = earth_sun_distance_au(body_files[0])

    chunk_info = []
    row_starts = []
    row_ends = []
    for nc_file in body_files:
        ds = load_channel_measured(nc_file, channel)
        row_start = int(ds["start_position_row"]) - 1
        row_end = int(ds["end_position_row"])
        col_start = int(ds["start_position_column"]) - 1
        col_end = int(ds["end_position_column"])
        image = calibrated_image_from_dataset(ds, channel, d_au)
        x = ds["x"].values.astype("float64")
        y = ds["y"].values.astype("float64")
        chunk_info.append((row_start, row_end, col_start, col_end, image, x, y))
        row_starts.append(row_start)
        row_ends.append(row_end)

    global_row_start = min(row_starts)
    global_row_end = max(row_ends)
    total_rows = global_row_end - global_row_start
    total_cols = max(info[3] for info in chunk_info)

    mosaic = np.full((total_rows, total_cols), np.nan, dtype="float64")
    y_full = np.full(total_rows, np.nan, dtype="float64")
    x_full = None

    for row_start, row_end, col_start, col_end, image, x, y in chunk_info:
        rs = row_start - global_row_start
        re = row_end - global_row_start
        mosaic[rs:re, col_start:col_end] = image
        y_full[rs:re] = y
        if x_full is None:
            x_full = x

    return mosaic, x_full, y_full


def bbox_projection_bounds(sample_file: Path, bbox: dict) -> tuple[float, float, float, float]:
    transformer, h = projection_transformer(sample_file)
    lons = [bbox["lon_min"], bbox["lon_max"], bbox["lon_max"], bbox["lon_min"]]
    lats = [bbox["lat_min"], bbox["lat_min"], bbox["lat_max"], bbox["lat_max"]]
    x_m, y_m = transformer.transform(lons, lats)
    x_ang = -np.asarray(x_m, dtype="float64") / h
    y_ang = np.asarray(y_m, dtype="float64") / h
    return float(np.nanmin(x_ang)), float(np.nanmax(x_ang)), float(np.nanmin(y_ang)), float(np.nanmax(y_ang))


def crop_image_by_bbox(
    image: np.ndarray, x: np.ndarray, y: np.ndarray, sample_file: Path, bbox: dict
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xmin, xmax, ymin, ymax = bbox_projection_bounds(sample_file, bbox)
    x_idx = np.where((x >= xmin) & (x <= xmax))[0]
    y_idx = np.where((y >= ymin) & (y <= ymax))[0]
    if x_idx.size == 0 or y_idx.size == 0:
        raise ValueError("La bounding box selezionata non interseca il mosaico disponibile")
    xs = slice(x_idx.min(), x_idx.max() + 1)
    ys = slice(y_idx.min(), y_idx.max() + 1)
    return image[ys, xs], x[xs], y[ys]


def make_crop_plan(product_dir: Path, channel: str, bbox: dict) -> CropPlan:
    body_files = list_body_files(product_dir)
    sample_file = body_files[0]
    xmin, xmax, ymin, ymax = bbox_projection_bounds(sample_file, bbox)

    with Dataset(sample_file) as root:
        group = root.groups["data"].groups[channel].groups["measured"]
        x_full = np.asarray(group.variables["x"][:], dtype="float64")

    x_idx = np.where((x_full >= xmin) & (x_full <= xmax))[0]
    if x_idx.size == 0:
        raise ValueError("La bounding box selezionata non interseca la griglia x disponibile")
    x_slice = slice(x_idx.min(), x_idx.max() + 1)
    x_crop = x_full[x_slice]

    chunks: list[CropChunk] = []
    global_row_starts = []
    global_row_ends = []
    for nc_file in body_files:
        with Dataset(nc_file) as root:
            group = root.groups["data"].groups[channel].groups["measured"]
            y_full = np.asarray(group.variables["y"][:], dtype="float64")
            y_idx = np.where((y_full >= ymin) & (y_full <= ymax))[0]
            if y_idx.size == 0:
                continue

            row_slice = slice(y_idx.min(), y_idx.max() + 1)
            row_start = int(_scalar_from_group(group, "start_position_row")) - 1
            global_row_start = row_start + row_slice.start
            global_row_end = row_start + row_slice.stop
            y_crop = y_full[row_slice]

        chunks.append(
            CropChunk(
                file_token=chunk_token(nc_file),
                row_slice_start=row_slice.start,
                row_slice_stop=row_slice.stop,
                x_slice_start=x_slice.start,
                x_slice_stop=x_slice.stop,
                output_row_start=global_row_start,
                output_row_stop=global_row_end,
            )
        )
        global_row_starts.append(global_row_start)
        global_row_ends.append(global_row_end)

    if not chunks:
        raise ValueError("La bounding box selezionata non interseca la griglia y disponibile")

    output_row_start = min(global_row_starts)
    output_row_end = max(global_row_ends)
    output_rows = output_row_end - output_row_start
    y_crop_full = np.full(output_rows, np.nan, dtype="float64")

    for chunk in chunks:
        nc_file = body_files_by_token(product_dir)[chunk.file_token]
        with Dataset(nc_file) as root:
            group = root.groups["data"].groups[channel].groups["measured"]
            y_full = np.asarray(group.variables["y"][:], dtype="float64")
            row_slice = slice(chunk.row_slice_start, chunk.row_slice_stop)
            rs = chunk.output_row_start - output_row_start
            re = chunk.output_row_stop - output_row_start
            y_crop_full[rs:re] = y_full[row_slice]

    normalized_chunks = tuple(
        CropChunk(
            file_token=chunk.file_token,
            row_slice_start=chunk.row_slice_start,
            row_slice_stop=chunk.row_slice_stop,
            x_slice_start=chunk.x_slice_start,
            x_slice_stop=chunk.x_slice_stop,
            output_row_start=chunk.output_row_start - output_row_start,
            output_row_stop=chunk.output_row_stop - output_row_start,
        )
        for chunk in chunks
    )
    return CropPlan(channel=channel, x=x_crop, y=y_crop_full, chunks=normalized_chunks)


def crop_channel_with_plan(product_dir: Path, plan: CropPlan) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    files_by_token = body_files_by_token(product_dir)
    output = np.full((len(plan.y), len(plan.x)), np.nan, dtype="float64")
    d_au = None

    for chunk in plan.chunks:
        nc_file = files_by_token[chunk.file_token]
        with Dataset(nc_file) as root:
            if d_au is None:
                celestial = root.groups["state"].groups["celestial"]
                distance = celestial.variables["earth_sun_distance"][:]
                d_au = float(np.asarray(distance, dtype="float64").mean()) / AU_KM

            group = root.groups["data"].groups[plan.channel].groups["measured"]
            row_slice = slice(chunk.row_slice_start, chunk.row_slice_stop)
            x_slice = slice(chunk.x_slice_start, chunk.x_slice_stop)
            radiance = group.variables["effective_radiance"][row_slice, x_slice]
            image = calibrated_image_from_group(group, plan.channel, radiance, d_au)

        output[chunk.output_row_start : chunk.output_row_stop, :] = image

    return output, plan.x, plan.y


def crop_channel_by_bbox(
    product_dir: Path, channel: str, bbox: dict
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    plan = make_crop_plan(product_dir, channel, bbox)
    return crop_channel_with_plan(product_dir, plan)


def plot_image(ax, image: np.ndarray, channel: str, title: str) -> None:
    label, cmap = channel_label(channel)
    vmin, vmax = robust_limits(image)
    im = ax.imshow(image, cmap=cmap, vmin=vmin, vmax=vmax)
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label=label)


def _cache_dir() -> Path:
    cache_dir = Path.cwd() / ".cache_mtg"
    cache_dir.mkdir(exist_ok=True)
    return cache_dir


def _download_json(url: str, cache_file: Path, *, method: str = "GET", data=None) -> dict:
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    if method == "GET":
        response = requests.get(url, timeout=120)
    else:
        response = requests.post(url, data=data, timeout=180, headers={"User-Agent": "mtg-fci-tools/1.0"})
    response.raise_for_status()
    cache_file.write_text(response.text, encoding="utf-8")
    return response.json()


def _extract_geojson_lines(geometry: dict) -> list[np.ndarray]:
    geom_type = geometry["type"]
    coords = geometry["coordinates"]
    if geom_type == "LineString":
        return [np.asarray(coords, dtype="float64")]
    if geom_type == "MultiLineString":
        return [np.asarray(line, dtype="float64") for line in coords]
    return []


def fetch_coastline_lines() -> list[np.ndarray]:
    cache_file = _cache_dir() / "ne_10m_coastline.geojson"
    geojson = _download_json(COASTLINE_GEOJSON_URL, cache_file)
    lines: list[np.ndarray] = []
    for feature in geojson.get("features", []):
        lines.extend(_extract_geojson_lines(feature["geometry"]))
    return lines


def fetch_gra_lines() -> list[np.ndarray]:
    cache_file = _cache_dir() / "roma_gra_overpass.json"
    query = """
[out:json][timeout:90];
way["name"="Grande Raccordo Anulare"](41.60,12.15,42.12,12.90);
out geom;
"""
    payload = _download_json(OVERPASS_URL, cache_file, method="POST", data={"data": query})
    lines: list[np.ndarray] = []
    for element in payload.get("elements", []):
        if element.get("type") == "way" and "geometry" in element:
            coords = [(node["lon"], node["lat"]) for node in element["geometry"]]
            lines.append(np.asarray(coords, dtype="float64"))
    return lines


def lonlat_to_image_pixels(
    lonlat_line: np.ndarray, x_grid: np.ndarray, y_grid: np.ndarray, sample_file: Path
) -> tuple[np.ndarray, np.ndarray]:
    transformer, h = projection_transformer(sample_file)
    x_m, y_m = transformer.transform(lonlat_line[:, 0], lonlat_line[:, 1])
    x_ang = -np.asarray(x_m, dtype="float64") / h
    y_ang = np.asarray(y_m, dtype="float64") / h

    x_order = np.argsort(x_grid)
    y_order = np.argsort(y_grid)
    x_pixels = np.interp(x_ang, x_grid[x_order], x_order, left=np.nan, right=np.nan)
    y_pixels = np.interp(y_ang, y_grid[y_order], y_order, left=np.nan, right=np.nan)
    return x_pixels, y_pixels


def filter_lonlat_lines_by_bbox(
    lines: Iterable[np.ndarray], bbox: dict, *, pad_degrees: float = 0.25
) -> list[np.ndarray]:
    lon_min = bbox["lon_min"] - pad_degrees
    lon_max = bbox["lon_max"] + pad_degrees
    lat_min = bbox["lat_min"] - pad_degrees
    lat_max = bbox["lat_max"] + pad_degrees
    selected = []
    for line in lines:
        if line.ndim != 2 or line.shape[1] != 2 or len(line) < 2:
            continue
        lon = line[:, 0]
        lat = line[:, 1]
        if lon.max() < lon_min or lon.min() > lon_max:
            continue
        if lat.max() < lat_min or lat.min() > lat_max:
            continue
        selected.append(line)
    return selected


def _format_lon_label(lon: float) -> str:
    suffix = "E" if lon >= 0 else "W"
    return f"{abs(lon):.0f}{suffix}"


def _format_lat_label(lat: float) -> str:
    suffix = "N" if lat >= 0 else "S"
    return f"{abs(lat):.0f}{suffix}"


def plot_lonlat_grid(
    ax,
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    sample_file: Path,
    bbox: dict,
    *,
    lon_step: float = 2.0,
    lat_step: float = 2.0,
    color: str = "white",
    linewidth: float = 0.5,
    alpha: float = 0.35,
    fontsize: int = 8,
) -> None:
    lon_values = np.arange(
        math.ceil(bbox["lon_min"] / lon_step) * lon_step,
        bbox["lon_max"] + lon_step * 0.5,
        lon_step,
    )
    lat_values = np.arange(
        math.ceil(bbox["lat_min"] / lat_step) * lat_step,
        bbox["lat_max"] + lat_step * 0.5,
        lat_step,
    )

    x_ticks = []
    x_labels = []
    for lon in lon_values:
        lat_line = np.linspace(bbox["lat_min"], bbox["lat_max"], 181)
        lon_line = np.full_like(lat_line, lon, dtype="float64")
        line = np.column_stack([lon_line, lat_line])
        x_pixels, y_pixels = lonlat_to_image_pixels(line, x_grid, y_grid, sample_file)
        valid = np.isfinite(x_pixels) & np.isfinite(y_pixels)
        if valid.sum() < 2:
            continue
        ax.plot(x_pixels[valid], y_pixels[valid], color=color, linewidth=linewidth, alpha=alpha)
        x_ticks.append(float(np.nanmean(x_pixels[valid])))
        x_labels.append(_format_lon_label(float(lon)))

    y_ticks = []
    y_labels = []
    for lat in lat_values:
        lon_line = np.linspace(bbox["lon_min"], bbox["lon_max"], 181)
        lat_line = np.full_like(lon_line, lat, dtype="float64")
        line = np.column_stack([lon_line, lat_line])
        x_pixels, y_pixels = lonlat_to_image_pixels(line, x_grid, y_grid, sample_file)
        valid = np.isfinite(x_pixels) & np.isfinite(y_pixels)
        if valid.sum() < 2:
            continue
        ax.plot(x_pixels[valid], y_pixels[valid], color=color, linewidth=linewidth, alpha=alpha)
        y_ticks.append(float(np.nanmean(y_pixels[valid])))
        y_labels.append(_format_lat_label(float(lat)))

    ax.set_xticks(x_ticks)
    ax.set_xticklabels(x_labels, fontsize=fontsize)
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels, fontsize=fontsize)
    ax.tick_params(
        axis="both",
        which="both",
        direction="out",
        top=True,
        bottom=True,
        left=True,
        right=True,
        labeltop=True,
        labelbottom=True,
        labelleft=True,
        labelright=True,
        colors=color,
        length=3,
        pad=2,
    )


def plot_lonlat_point(
    ax,
    lon: float,
    lat: float,
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    sample_file: Path,
    *,
    color: str = "red",
    marker: str = "o",
    markersize: float = 8.0,
    markeredgecolor: str = "white",
    markeredgewidth: float = 0.8,
    alpha: float = 0.95,
) -> None:
    line = np.asarray([[lon, lat]], dtype="float64")
    x_pixels, y_pixels = lonlat_to_image_pixels(line, x_grid, y_grid, sample_file)
    if not (np.isfinite(x_pixels[0]) and np.isfinite(y_pixels[0])):
        return
    ax.plot(
        [float(x_pixels[0])],
        [float(y_pixels[0])],
        linestyle="none",
        marker=marker,
        markersize=markersize,
        color=color,
        markeredgecolor=markeredgecolor,
        markeredgewidth=markeredgewidth,
        alpha=alpha,
        zorder=20,
    )


def plot_lonlat_lines(
    ax,
    lines: Iterable[np.ndarray],
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    sample_file: Path,
    *,
    color: str = "cyan",
    linewidth: float = 1.0,
    alpha: float = 0.9,
) -> None:
    for line in lines:
        if line.ndim != 2 or line.shape[1] != 2 or len(line) < 2:
            continue
        x_pixels, y_pixels = lonlat_to_image_pixels(line, x_grid, y_grid, sample_file)
        valid = np.isfinite(x_pixels) & np.isfinite(y_pixels)
        if valid.sum() < 2:
            continue
        ax.plot(x_pixels[valid], y_pixels[valid], color=color, linewidth=linewidth, alpha=alpha)
