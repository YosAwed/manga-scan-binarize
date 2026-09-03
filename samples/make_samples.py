#!/usr/bin/env python3
"""
make_samples.py -- GitHubですぐ試せるサンプル漫画スキャン画像を生成するスクリプト。

生成ファイル:
  - sample_page.jpg   : 単ページ原稿（コマ割り、網点トーン、効果線、照明ムラ、紙地色）
  - sample_spread.jpg : 見開き原稿（左右2ページ、中央綴じ目の影、余白トリム検証用）
"""

from pathlib import Path
import cv2
import numpy as np


def create_halftone(h, w, cell=10.0, angle_deg=45.0):
    """回転した網点座標グリッドの距離マップを返す。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    th = np.deg2rad(angle_deg)
    u = xx * np.cos(th) + yy * np.sin(th)
    v = -xx * np.sin(th) + yy * np.cos(th)
    dist = np.sqrt(((u % cell) - cell / 2) ** 2 + ((v % cell) - cell / 2) ** 2)
    return dist, cell


def apply_screentone(canvas, box, density, cell=10.0, angle_deg=45.0):
    """指定矩形領域に指定濃度の網点スクリーントーンを焼き込む。"""
    y0, x0, y1, x1 = box
    h, w = y1 - y0, x1 - x0
    dist, c = create_halftone(h, w, cell, angle_deg)
    r = np.sqrt(density / np.pi) * c
    tone = np.where(dist < r, 0, 255).astype(np.uint8)
    canvas[y0:y1, x0:x1] = np.minimum(canvas[y0:y1, x0:x1], tone)


def generate_single_page(out_path: Path):
    """単ページサンプル（2400x1700, 600dpi相当）"""
    h, w = 2400, 1700
    page = np.full((h, w), 255, dtype=np.uint8)

    # 1. 外枠・コマ割り（3段構成）
    # 上段: 横長コマ
    # 中段: 左右2コマ
    # 下段: 大ゴマ
    cv2.rectangle(page, (160, 200), (1540, 2200), 0, 8)  # 基本枠

    # コマ仕切り線
    cv2.line(page, (160, 750), (1540, 750), 0, 6)
    cv2.line(page, (160, 1450), (1540, 1450), 0, 6)
    cv2.line(page, (850, 750), (850, 1450), 0, 5)

    # 2. 上段コマ: 網点トーンの階調比較（15%, 35%, 60%）
    apply_screentone(page, (240, 200, 700, 600), density=0.15)
    cv2.putText(page, "Tone 15%", (240, 730), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2, cv2.LINE_AA)

    apply_screentone(page, (240, 650, 700, 1050), density=0.35)
    cv2.putText(page, "Tone 35%", (690, 730), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2, cv2.LINE_AA)

    apply_screentone(page, (240, 1100, 700, 1500), density=0.60)
    cv2.putText(page, "Tone 60%", (1140, 730), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 2, cv2.LINE_AA)

    # 3. 中段左コマ: 細線・ハッチング・グラデーション風トーン
    for i in range(18):
        cv2.line(page, (180 + i * 35, 780), (160 + i * 35, 1420), 0, 1 + i % 2)
    cv2.circle(page, (500, 1100), 120, 0, -1)  # 黒ベタ円
    # ベタの中に白抜き文字
    cv2.putText(page, "INK", (440, 1120), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 255, 4, cv2.LINE_AA)

    # 4. 中段右コマ: 集中線（効果線）と吹き出し
    cx, cy = 1200, 1100
    for deg in range(0, 360, 6):
        rad = np.deg2rad(deg)
        r1, r2 = 90 + (deg % 12) * 4, 300
        x1 = int(cx + r1 * np.cos(rad))
        y1 = int(cy + r1 * np.sin(rad))
        x2 = int(cx + r2 * np.cos(rad))
        y2 = int(cy + r2 * np.sin(rad))
        cv2.line(page, (x1, y1), (x2, y2), 0, 2 if deg % 12 == 0 else 1)

    # 吹き出し（楕円）
    cv2.ellipse(page, (cx, cy), (130, 85), 0, 0, 360, 255, -1)
    cv2.ellipse(page, (cx, cy), (130, 85), 0, 0, 360, 0, 4)
    cv2.putText(page, "SAMPLE", (cx - 75, cy + 12), cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 3, cv2.LINE_AA)

    # 5. 下段コマ: 網点トーン背景 + 小文字・細線テスト
    apply_screentone(page, (1480, 180, 2180, 1520), density=0.25)
    # 白抜きボックス
    cv2.rectangle(page, (300, 1600), (1400, 2050), 255, -1)
    cv2.rectangle(page, (300, 1600), (1400, 2050), 0, 4)
    cv2.putText(page, "manga-scan-binarize", (350, 1720), cv2.FONT_HERSHEY_SIMPLEX, 2.2, 0, 5, cv2.LINE_AA)
    cv2.putText(page, "High-fidelity Halftone Screentone Preservation", (350, 1820),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2, cv2.LINE_AA)
    cv2.putText(page, "Fine lines (1px) & tiny text for vectorization test", (350, 1920),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, 0, 1, cv2.LINE_AA)
    cv2.putText(page, "1234567890 ABCDEFGHIJKLMNOPQRSTUVWXYZ", (350, 1990),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 1, cv2.LINE_AA)

    # 6. スキャナの劣化シミュレーション（紙の地色、照明ムラ、ノイズ、JPEG）
    g = page.astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 0.8)  # スキャナ光学系のわずかなボケ

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # 左上が明るく右下が暗い照明ムラ
    shade = 1.0 - 0.20 * ((xx / w - 0.2) ** 2 + (yy / h - 0.7) ** 2) * 1.5
    # 紙の地色: 232 前後
    g = g * shade * 0.92 + 15.0
    # 軽微なスキャナノイズ
    rng = np.random.default_rng(42)
    g += rng.normal(0, 3.5, g.shape)
    g = np.clip(g, 0, 255).astype(np.uint8)

    # 保存 (品質 85 JPEG でリポジトリ容量を抑えつつ十分な画質を確保)
    _, enc = cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 85])
    enc.tofile(str(out_path))

    print(f"Generated single page: {out_path} ({w}x{h}, {out_path.stat().st_size / 1024:.1f} KB)")


def generate_spread(out_path: Path):
    """見開きサンプル（2200x3200、中央に綴じ目影、余白付き）"""
    h, w = 2200, 3200
    page = np.full((h, w), 255, dtype=np.uint8)

    gutter_x = w // 2  # 1600
    gutter_half = 60   # 綴じ目の白余白

    # 右ページ (x: gutter_x + gutter_half .. w - 100)
    # 左ページ (x: 100 .. gutter_x - gutter_half)
    r_x0, r_x1 = gutter_x + gutter_half, w - 150
    l_x0, l_x1 = 150, gutter_x - gutter_half
    y0, y1 = 150, h - 150

    # 右ページ コマ枠
    cv2.rectangle(page, (r_x0, y0), (r_x1, y1), 0, 6)
    cv2.line(page, (r_x0, y0 + 900), (r_x1, y0 + 900), 0, 5)
    apply_screentone(page, (y0 + 50, r_x0 + 50, y0 + 850, r_x1 - 50), density=0.20)
    cv2.putText(page, "RIGHT PAGE (_r)", (r_x0 + 150, y0 + 500),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 4, cv2.LINE_AA)
    cv2.putText(page, "Japanese Manga starts here", (r_x0 + 150, y0 + 600),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2, cv2.LINE_AA)

    # 右ページ下段: ベタと細線
    cv2.circle(page, (r_x0 + 400, y0 + 1400), 200, 0, -1)
    for i in range(25):
        cv2.line(page, (r_x0 + 700 + i * 25, y0 + 1000),
                 (r_x0 + 650 + i * 25, y0 + 1800), 0, 1 + i % 3)

    # 左ページ コマ枠
    cv2.rectangle(page, (l_x0, y0), (l_x1, y1), 0, 6)
    cv2.line(page, (l_x0, y0 + 900), (l_x1, y0 + 900), 0, 5)
    apply_screentone(page, (y0 + 50, l_x0 + 50, y0 + 850, l_x1 - 50), density=0.35)
    cv2.putText(page, "LEFT PAGE (_l)", (l_x0 + 150, y0 + 500),
                cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 4, cv2.LINE_AA)
    cv2.putText(page, "Split & Trim Demonstration", (l_x0 + 150, y0 + 600),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, 0, 2, cv2.LINE_AA)

    # 左ページ下段: トーン階調
    apply_screentone(page, (y0 + 1000, l_x0 + 100, y0 + 1800, l_x0 + 600), density=0.55)
    cv2.rectangle(page, (l_x0 + 700, y0 + 1050), (l_x1 - 80, y0 + 1750), 0, 4)
    cv2.putText(page, "GUTTER TEST", (l_x0 + 750, y0 + 1300),
                cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3, cv2.LINE_AA)

    # スキャン劣化: 綴じ目（gutter）の自然な影 + 照明ムラ
    g = page.astype(np.float32)
    g = cv2.GaussianBlur(g, (0, 0), 0.8)

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # 綴じ目中央の影（最低でも輝度205以上を保ち、ink_level=200と混同させない）
    gutter_shadow = 1.0 - 0.12 * np.exp(-((xx - gutter_x) / 100) ** 2)
    # 全体のゆるやかな傾斜照明
    wide_shade = 1.0 - 0.08 * ((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2)

    g = g * gutter_shadow * wide_shade * 0.93 + 15.0
    rng = np.random.default_rng(123)
    g += rng.normal(0, 3.0, g.shape)
    g = np.clip(g, 0, 255).astype(np.uint8)


    _, enc = cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 85])
    enc.tofile(str(out_path))

    print(f"Generated spread: {out_path} ({w}x{h}, {out_path.stat().st_size / 1024:.1f} KB)")


def main():
    samples_dir = Path(__file__).resolve().parent
    generate_single_page(samples_dir / "sample_page.jpg")
    generate_spread(samples_dir / "sample_spread.jpg")


if __name__ == "__main__":
    main()
