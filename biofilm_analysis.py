#!/usr/bin/env python3
"""
Biofilm Quantitative Analysis (生物膜定量分析)
===============================================
Analyze crystal violet biofilm staining images using the B/(R+G+B) blue ratio
with adaptive Otsu thresholding and blank-reference percentile floors.

Method:
  1. Calculate B/(R+G+B) ratio for each pixel (blue ratio, luminance-invariant)
  2. Compute Otsu auto-threshold per image
  3. Final threshold = max(Otsu, blank_percentile_floor)
  4. Regions above threshold → biofilm-positive, outlined in red
  5. Report: area (px), blue ratio, integrated density

Usage:
  python3 biofilm_analysis.py --data_dir /path/to/images --blank 34.png --output ./results
"""

import os
import argparse
import cv2
import numpy as np
import pandas as pd
from datetime import datetime


def analyze_biofilm(data_dir, blank_file, output_dir, floor_default=90,
                    floor_override=None, min_region=30):
    """
    Analyze biofilm images.

    Parameters
    ----------
    data_dir : str
        Directory containing the images.
    blank_file : str
        Filename of the blank control.
    output_dir : str
        Output directory for annotated images and CSV results.
    floor_default : int, optional
        Default percentile floor (default: 90).
    floor_override : dict, optional
        Per-image floor overrides, e.g. {'sample.png': 99}.
    min_region : int, optional
        Minimum region area in pixels to retain.
    """
    if floor_override is None:
        floor_override = {}

    os.makedirs(output_dir, exist_ok=True)

    # ====== Read blank control ======
    blank_path = os.path.join(data_dir, blank_file)
    blank_bgr = cv2.imread(blank_path, cv2.IMREAD_COLOR)
    if blank_bgr is None:
        print(f'ERROR: Cannot read blank file: {blank_path}')
        return

    blank = blank_bgr.astype(np.float64)
    b0, g0, r0 = blank[:, :, 0], blank[:, :, 1], blank[:, :, 2]
    mask_non_bg = (b0 + g0 + r0) > 10
    total0 = b0 + g0 + r0 + 0.001
    blank_blue_ratio = (b0 / total0)[mask_non_bg]

    # Precompute needed percentiles
    needed = sorted(set([floor_default] + list(floor_override.values())))
    floor_cache = {p: np.percentile(blank_blue_ratio, p) for p in needed}

    print('=' * 60)
    print('Biofilm Quantitative Analysis')
    print(f'  Blank:      {blank_file}')
    for p, v in sorted(floor_cache.items()):
        print(f'  P{p:<3d}       {v:.4f}')
    print('=' * 60)
    print()

    # ====== Scan all image files ======
    all_files = sorted([
        f for f in os.listdir(data_dir)
        if not f.startswith('.') and f.lower().endswith(('.png', '.jpg', '.jpeg'))
    ])

    results = []

    for fn in all_files:
        if fn == blank_file:
            continue

        img_bgr = cv2.imread(os.path.join(data_dir, fn), cv2.IMREAD_COLOR)
        if img_bgr is None:
            print(f'  SKIP {fn} (cannot read)')
            continue

        img_f = img_bgr.astype(np.float64)
        h, w = img_bgr.shape[:2]
        b_ch, g_ch, r_ch = img_f[:, :, 0], img_f[:, :, 1], img_f[:, :, 2]
        non_bg = (b_ch + g_ch + r_ch) > 10
        total = b_ch + g_ch + r_ch + 0.001
        blue_ratio = b_ch / total

        # ---- Compute threshold ----
        br_8bit = (blue_ratio * 255).clip(0, 255).astype(np.uint8)
        otsu_th, _ = cv2.threshold(br_8bit, 0, 255, cv2.THRESH_OTSU)
        otsu_real = otsu_th / 255.0

        floor_pct = floor_override.get(fn, floor_default)
        floor_val = floor_cache[floor_pct]
        final_th = max(otsu_real, floor_val)

        # ---- Binary mask + morphological cleanup ----
        mask_raw = (blue_ratio > final_th) & non_bg
        mask_u8 = mask_raw.astype(np.uint8) * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask_c = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, kernel)
        mask_c = cv2.morphologyEx(mask_c, cv2.MORPH_CLOSE, kernel)

        # ---- Find contours ----
        contours, _ = cv2.findContours(mask_c, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if cv2.contourArea(c) >= min_region]

        # ---- Draw annotations ----
        img_draw = img_bgr.copy()
        if img_draw.shape[2] == 4:
            img_draw = cv2.cvtColor(img_draw, cv2.COLOR_BGRA2BGR)
        cv2.drawContours(img_draw, valid, -1, (0, 0, 255), 2)

        base, ext = os.path.splitext(fn)
        cv2.imwrite(os.path.join(output_dir, f'{base}_annotated.png'), img_draw)

        # ---- Statistics ----
        total_area = sum(cv2.contourArea(c) for c in valid)
        region_mask = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(region_mask, valid, -1, 255, -1)
        rb = region_mask > 0

        if rb.sum() > 0:
            mean_blue_ratio = blue_ratio[rb].mean()
            integrated_blue = blue_ratio[rb].sum()
        else:
            mean_blue_ratio = 0.0
            integrated_blue = 0.0

        well_px = non_bg.sum()
        pct = (total_area / well_px * 100) if well_px > 0 else 0.0

        cy, cx = h // 2, w // 2
        center_br = blue_ratio[cy, cx]

        results.append({
            'filename': fn,
            'floor': f'P{floor_pct}',
            'otsu_threshold': round(otsu_real, 4),
            'final_threshold': round(final_th, 4),
            'center_blue_ratio': round(center_br, 4),
            'area_px': total_area,
            'area_pct': round(pct, 2),
            'mean_blue_ratio': round(mean_blue_ratio, 4),
            'integrated_blue_ratio': round(integrated_blue, 1),
            'num_regions': len(valid),
        })

        print(f'  {fn:12s}  '
              f'th={final_th:.4f}(P{floor_pct})  '
              f'area={pct:5.1f}%  '
              f'blue={mean_blue_ratio:.4f}  '
              f'regions={len(valid):2d}')

    if not results:
        print('No results.')
        return

    df = pd.DataFrame(results)

    # Save CSV
    csv_path = os.path.join(output_dir, 'biofilm_results.csv')
    df.to_csv(csv_path, index=False)
    print(f'\nResults saved: {csv_path}')
    print(f'Total: {len(results)} images\n')

    # Print summary table
    display_cols = ['filename', 'floor', 'area_pct', 'mean_blue_ratio',
                    'integrated_blue_ratio', 'num_regions']
    print(df[display_cols].to_string(index=False))

    return df


def main():
    parser = argparse.ArgumentParser(
        description='Biofilm quantitative analysis using B/(R+G+B) blue ratio')
    parser.add_argument('--data_dir', required=True,
                        help='Directory with biofilm images (PNG/JPG)')
    parser.add_argument('--blank', default='blank.png',
                        help='Blank control filename (default: blank.png)')
    parser.add_argument('--output', '-o', default='./results',
                        help='Output directory (default: ./results)')
    parser.add_argument('--floor', type=int, default=90,
                        help='Default percentile floor (default: 90)')
    parser.add_argument('--min_region', type=int, default=30,
                        help='Minimum region area in pixels (default: 30)')
    args = parser.parse_args()

    analyze_biofilm(
        data_dir=args.data_dir,
        blank_file=args.blank,
        output_dir=args.output,
        floor_default=args.floor,
        min_region=args.min_region,
    )


if __name__ == '__main__':
    main()
