"""
Batch processing of tree image datasets in Agisoft Metashape

Developed for a supervised Bachelor thesis
Author:       Johannes Senn
Contributor:  Claude (Anthropic), AI assistant
Date:         2026-10-19
Metashape:    Professional 2.3.1 (64 bit)

Steps per tree (one subfolder with images per tree in --root-dir):
    1. Detect targets (circular 12-bit, reference cube at approx. 1.3 m)
    2. Align photos
    3. Assign target coordinates, approx. 30 % as check points (same for all trees)
    4. Update reference, optimize cameras
    5. Set bounding box in the target system (z 1-2 m, stem in -y direction)
    6. Build depth maps and point cloud
    7. Export point cloud as .laz (with color and confidence), save project

Output in <root-dir>_out/:
    <tree>.psx   Metashape project per tree
    <tree>.laz   Point cloud per tree (coordinates in the target system, m)
    log.txt      Table (tab-separated, marker errors in mm), updated after each tree

Usage:
    GUI:      Tools > Run Script, script tree_sfm_batch.py, arguments:
              --root-dir F:/project/final_trees/img --targets-csv F:/project/Target_Koordinaten.csv
    Headless: metashape.exe -r tree_sfm_batch.py --root-dir F:/project/final_trees/img --targets-csv F:/project/Target_Koordinaten.csv
    Optional: --seed <number> for a different (reproducible) selection of check points

Targets CSV (semicolon-separated, coordinates in m):
    target number;x;y;z
    target 1;0;0;1.278
"""

import argparse
import csv
import math
import os
import random
import time
import traceback

import Metashape


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".heic", ".tif", ".tiff")
CHECK_FRACTION = 0.3

# Bounding box in the target system (m): stem in -y direction, max. 1.5 m diameter, z 1-2 m
REGION_CENTER = [-0.047, -0.75, 1.5]
REGION_SIZE = [1.7, 1.7, 1.0]

LOG_COLUMNS = [
    "tree_id",
    "duration_s",
    "photos_total",
    "photos_aligned",
    "check_count",
    "control_count",
    "check_error_mean_mm",
    "control_error_mean_mm",
    "check_labels",
    "status",
    "message",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Batch processing of tree image folders with Agisoft Metashape")
    parser.add_argument("--root-dir", required=True, help="Folder containing one subfolder per tree")
    parser.add_argument("--targets-csv", required=True, help="CSV with target labels and local coordinates (target number;x;y;z)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for the selection of check points")
    return parser.parse_args()


def load_targets(path):
    """Reads the targets CSV and returns {label: [x, y, z]} (labels in lower case)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Targets CSV not found: {path}")

    targets = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            label = (row.get("label") or row.get("target") or row.get("target number") or row.get("name") or "").strip()
            coords = [(row.get(axis) or row.get(axis.upper()) or row.get(f"{axis} coordinate") or "").strip() for axis in "xyz"]
            if label and all(coords):
                targets[label.lower()] = [float(value) for value in coords]
    return targets


def choose_check_labels(targets, seed):
    """Selects CHECK_FRACTION of the targets as check points, random but reproducible."""
    count = max(1, round(len(targets) * CHECK_FRACTION))
    return set(random.Random(seed).sample(sorted(targets), count))


def marker_error(chunk, marker):
    """3D deviation (m) between estimated position and reference coordinate."""
    if marker.position is None or marker.reference.location is None:
        return None
    estimated = chunk.transform.matrix.mulp(marker.position)
    return (estimated - marker.reference.location).norm()


def mean_error_mm(chunk, markers):
    errors = [marker_error(chunk, marker) for marker in markers]
    errors = [error for error in errors if error is not None]
    if not errors:
        return ""
    return round(sum(errors) / len(errors) * 1000, 2)


def set_region(chunk, center, size):
    """Sets the bounding box in target coordinates (m), aligned with the target system axes."""
    T = chunk.transform.matrix
    scale = math.sqrt(T[0, 0] ** 2 + T[0, 1] ** 2 + T[0, 2] ** 2)
    rotation = Metashape.Matrix([[T[i, j] for j in range(3)] for i in range(3)]) * (1.0 / scale)

    region = chunk.region
    region.center = T.inv().mulp(Metashape.Vector(center))
    region.size = Metashape.Vector(size) * (1.0 / scale)
    region.rot = rotation.t()
    chunk.region = region


def write_log(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\t".join(LOG_COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(str(row.get(column, "")) for column in LOG_COLUMNS) + "\n")


def process_tree(folder, output_dir, targets, check_labels):
    """Processes one tree folder and returns its log row (None if it contains no images)."""
    tree_id = os.path.basename(folder)
    photos = [
        os.path.join(folder, name) for name in os.listdir(folder)
        if name.lower().endswith(IMAGE_EXTENSIONS)
    ]
    if not photos:
        return None

    doc = Metashape.Document()
    chunk = doc.addChunk()
    chunk.label = tree_id
    chunk.addPhotos(photos)

    # 1. Detect targets
    chunk.detectMarkers(target_type=Metashape.CircularTarget12bit)

    # 2. Align photos (highest accuracy)
    chunk.matchPhotos(
        downscale=0,
        generic_preselection=True,
        reference_preselection=False,
        keypoint_limit=80000,
        tiepoint_limit=8000,
        filter_stationary_points=True,
        guided_matching=False,
    )
    chunk.alignCameras(reset_alignment=True, adaptive_fitting=False)

    # 3. Assign target coordinates, check points are disabled
    for marker in chunk.markers:
        label = marker.label.lower()
        if label in targets:
            marker.reference.location = Metashape.Vector(targets[label])
            marker.reference.enabled = label not in check_labels

    # 4. Update reference and optimize cameras
    chunk.updateTransform()
    chunk.optimizeCameras(
        fit_f=True, fit_cx=True, fit_cy=True, fit_b1=True, fit_b2=True,
        fit_k1=True, fit_k2=True, fit_k3=True, fit_p1=True, fit_p2=True,
    )
    chunk.updateTransform()

    # 5. Set bounding box (before the point cloud so that it limits it)
    set_region(chunk, REGION_CENTER, REGION_SIZE)

    # 6. Build depth maps and point cloud
    chunk.buildDepthMaps(downscale=2, filter_mode=Metashape.FilterMode.MildFiltering)
    chunk.buildPointCloud(point_colors=True, point_confidence=True)

    # 7. Export point cloud and save project
    chunk.exportPointCloud(
        path=os.path.join(output_dir, f"{tree_id}.laz"),
        format=Metashape.PointCloudFormatLAZ,
        source_data=Metashape.DataSource.PointCloudData,
        save_point_color=True,
        save_point_confidence=True,
    )
    doc.save(os.path.join(output_dir, f"{tree_id}.psx"))

    check_markers = [marker for marker in chunk.markers if not marker.reference.enabled]
    control_markers = [marker for marker in chunk.markers if marker.reference.enabled]

    return {
        "photos_total": len(photos),
        "photos_aligned": sum(1 for camera in chunk.cameras if camera.transform is not None),
        "check_count": len(check_markers),
        "control_count": len(control_markers),
        "check_error_mean_mm": mean_error_mm(chunk, check_markers),
        "control_error_mean_mm": mean_error_mm(chunk, control_markers),
        "check_labels": ",".join(marker.label for marker in check_markers),
    }


def main():
    args = parse_args()

    root_dir = os.path.abspath(args.root_dir)
    if not os.path.isdir(root_dir):
        raise FileNotFoundError(f"Input folder not found: {root_dir}")

    output_dir = root_dir + "_out"
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "log.txt")

    targets = load_targets(args.targets_csv)
    if not targets:
        raise ValueError(f"No valid targets in {args.targets_csv}")
    check_labels = choose_check_labels(targets, args.seed)
    print(f"Check points (seed {args.seed}): {', '.join(sorted(check_labels))}")

    log_rows = []
    tree_folders = sorted(entry.path for entry in os.scandir(root_dir) if entry.is_dir())

    for folder in tree_folders:
        start_time = time.perf_counter()

        try:
            row = process_tree(folder, output_dir, targets, check_labels)
            if row is None:
                continue
            row["status"] = "ok"
        except Exception as exc:
            traceback.print_exc()
            row = {"status": "error", "message": str(exc).replace("\t", " ").replace("\n", " ")}

        row["tree_id"] = os.path.basename(folder)
        row["duration_s"] = round(time.perf_counter() - start_time, 3)
        log_rows.append(row)
        write_log(log_path, log_rows)


main()
