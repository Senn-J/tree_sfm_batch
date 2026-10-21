# tree_sfm_batch

Automated processing of tree image datasets in Agisoft Metashape. The resulting point clouds are used for further analysis in R to determine bark roughness at breast height.

Bachelor thesis
Author: Johannes Senn
Contributor: Claude (Anthropic), AI assistant

## Contents

| File | Purpose |
|---|---|
| `tree_sfm_batch.py` | Batch processing in Metashape: alignment, referencing via the reference cube, point cloud, LAZ export |
| `Target_Koordinaten.csv` | Coordinates of the targets on the reference cube |

## Setup

A reference cube (approx. 9 × 7 × 7 cm) is attached to each tree at breast height. It carries 16 coded targets (circular 12-bit), 4 on each of four faces. The cube is levelled with a spirit level.

This defines the local coordinate system of all results:

- Units in metres, z points up, z = 0 is the ground
- The cube touches the stem with its face y = 0, the stem lies in −y direction
- Cube extent: x −0.094 to 0, y 0 to 0.072, z 1.228 to 1.3

## Requirements

- Agisoft Metashape Professional 2.3.1 (64 bit). The Python API is only included in the Professional edition. Other versions may have different API parameters.

## Processing in Metashape

### Input

One folder with one subfolder per tree, containing the images:

```
img/
├── GBC002304_Bernhardstraße/
│   ├── IMG_0001.jpg
│   └── ...
└── <next tree>/
```

### Usage

In the GUI via *Tools → Run Script*, select `tree_sfm_batch.py` and pass the arguments:

```
--root-dir F:/project/final_trees/img --targets-csv F:/project/Target_Koordinaten.csv
```

Or headless from the command line:

```
metashape.exe -r tree_sfm_batch.py --root-dir F:/project/final_trees/img --targets-csv F:/project/Target_Koordinaten.csv
```

| Argument | Required | Meaning |
|---|---|---|
| `--root-dir` | yes | Folder containing one subfolder per tree |
| `--targets-csv` | yes | CSV with target coordinates (semicolon-separated: `target number;x;y;z`) |
| `--seed` | no | Random seed for the selection of check points (default 42) |

### Steps per tree

1. Detect targets
2. Align photos (highest accuracy)
3. Assign target coordinates. Approx. 30 % of the targets are held back as check points. The selection is the same for all trees and reproducible via `--seed`.
4. Update reference, optimize cameras
5. Set bounding box: z 1 to 2 m, large enough for stems up to 1.5 m in diameter
6. Build depth maps (High, mild filtering) and point cloud
7. Export point cloud as LAZ (with color and confidence), save project

Runtime: approx. 10 minutes per tree with 42 images.

### Output

In the folder `<root-dir>_out/`, e.g. `img_out/`:

| File | Content |
|---|---|
| `<tree>.psx` | Metashape project |
| `<tree>.laz` | Point cloud in the cube coordinate system |
| `log.txt` | Table (tab-separated), updated after each tree |

Columns of `log.txt`:

| Column | Meaning |
|---|---|
| `tree_id` | Name of the tree folder |
| `duration_s` | Processing time in seconds |
| `photos_total`, `photos_aligned` | Number of images in total and aligned |
| `check_count`, `control_count` | Number of check and control points |
| `check_error_mean_mm`, `control_error_mean_mm` | Mean 3D deviation of the targets in mm |
| `check_labels` | Labels of the check points |
| `status`, `message` | `ok`, or `error` with the error message |

If a tree fails, it is logged with `status = error` and the script continues with the next tree.

### Notes

- In the GUI, the *Cancel* button only stops the current tree. To stop the whole run, close Metashape, or press Ctrl+C when running headless.
- Bounding box, share of check points and image formats can be adjusted as constants at the top of `tree_sfm_batch.py`.

## License

MIT License, see [LICENSE](LICENSE). The code may be freely used, modified and shared as long as the copyright notice is kept.
