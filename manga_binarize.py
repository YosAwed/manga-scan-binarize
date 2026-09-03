#!/usr/bin/env python3
"""
manga_binarize.py -- 漫画スキャンの高品質2値化（網点をそのまま残す / ベクトル化向け）

処理の流れ:
  1. グレースケール化
  2. (任意) 傾き補正 deskew
  3. フラットフィールド補正 …… 紙の色ムラ・スキャナの照明ムラを除去
  4. アンシャープマスク …… 網点と線のエッジを立てる
  5. しきい値 …… 既定は地色補正後の大域 Otsu（網点の濃度を最も忠実に再現）
     ムラが局所的に強い原稿は --method sauvola（窓は網点ピッチの5倍以上）
  6. ゴマ塩ノイズ除去 / ピンホール埋め
  7. 1bit PNG / TIFF(G4) で保存

使い方:
  python manga_binarize.py in.tif -o out.png
  python manga_binarize.py scans/*.tif -O out_dir/ --dpi 600
  python manga_binarize.py in.tif --compare cmp.png     # 設定の効き比べ
"""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np

try:
    from PIL import Image
    HAVE_PIL = True
except ImportError:
    HAVE_PIL = False


# ---------------------------------------------------------------- utilities
def odd(n):
    n = int(round(n))
    return n if n % 2 == 1 else n + 1


def read_gray(path):
    """日本語パス対応で読み込み、グレースケールを返す。"""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise IOError(f"読み込めません: {path}")
    if img.dtype == np.uint16:
        img = (img / 257).astype(np.uint8)
    if img.ndim == 3:
        if img.shape[2] == 4:  # アルファは白背景に合成
            a = img[:, :, 3:4].astype(np.float32) / 255.0
            img = (img[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def read_dpi(path, fallback):
    if not HAVE_PIL:
        return fallback
    try:
        with Image.open(str(path)) as im:
            d = im.info.get("dpi")
            if d and d[0] and 72 < float(d[0]) <= 2400:
                return float(d[0])
    except Exception:
        pass
    return fallback


# ---------------------------------------------------------------- steps
def deskew_angle(gray, max_deg=5.0):
    """コマ枠・文字行の水平/垂直成分から傾きを推定する。"""
    small = cv2.resize(gray, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(small, 50, 150)
    minlen = int(min(small.shape[:2]) * 0.25)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 1800, 80,
                            minLineLength=minlen, maxLineGap=6)
    if lines is None or len(lines) == 0:
        return 0.0
    lines = np.asarray(lines).reshape(-1, 4)   # OpenCV 4系は (N,1,4)、5系は (N,4)
    angs = []
    for x1, y1, x2, y2 in lines:
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        a = (a + 90) % 180 - 90          # -90..90
        if abs(a) <= max_deg:            # ほぼ水平の線
            angs.append(a)
        elif abs(abs(a) - 90) <= max_deg:  # ほぼ垂直の線
            angs.append(a - np.sign(a) * 90)
    if len(angs) < 4:
        return 0.0
    return float(np.median(angs))


def rotate(gray, deg):
    if abs(deg) < 0.05:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def _block_max(gray, target=128):
    """長辺が target 程度になるようブロック最大値でプーリングする。"""
    h, w = gray.shape
    f = max(1, int(round(max(h, w) / target)))
    hh, ww = h // f * f, w // f * f
    g = gray[:hh, :ww].reshape(hh // f, f, ww // f, f)
    return g.max(axis=(1, 3)).astype(np.float32), f


def flat_field_fit(gray, degree=4, iters=4):
    """紙面（＝明るい側の包絡）に多項式曲面を当てて地色を推定する。

    クロージングによる推定は、ボケた広いトーン面の中では「そのトーンの明るい所」
    を紙と誤認してトーンごと白く飛ばしてしまう。ここでは画像全体の明るい画素だけ
    に低次曲面を当てるので、トーン面の濃さを保ったまま綴じ目の影や照明ムラだけを
    取り除ける。
    """
    bm, _ = _block_max(gray)
    bh, bw = bm.shape
    yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float64)
    yy = yy / max(bh - 1, 1) * 2 - 1
    xx = xx / max(bw - 1, 1) * 2 - 1
    terms = [xx ** i * yy ** j for i in range(degree + 1)
             for j in range(degree + 1 - i)]
    A = np.stack([t.ravel() for t in terms], axis=1)
    norm = np.linalg.norm(A, axis=0)          # 列を正規化して条件数を下げる
    norm[norm == 0] = 1.0
    A = A / norm
    z = bm.ravel().astype(np.float64)
    w = np.ones_like(z)
    fit = z
    # macOS の Accelerate BLAS は正常な入力でも matmul で偽の FP 警告を出すので抑制。
    # 破綻の検出は下の isfinite チェックで行う。
    with np.errstate(all="ignore"):
        for _ in range(iters):
            coef, *_ = np.linalg.lstsq(A * w[:, None], z * w, rcond=None)
            if not np.all(np.isfinite(coef)):
                return None
            fit = A @ coef
            w = np.where(z >= fit - 2.0, 1.0, 0.15)   # 暗い側(インク)を外して再推定
    if not np.all(np.isfinite(fit)):
        return None
    bg = np.clip(fit.reshape(bh, bw), 1, 255).astype(np.float32)
    return cv2.resize(bg, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_CUBIC)


def flat_field(gray, radius):
    """紙の地色（背景）を推定して割り算し、地を均一な白にする。

    背景推定はクロージング（白側を伸ばす）。半径は網点ピッチより大きく、
    照明ムラの周期より小さく取る。縮小画像上で行うので大きな半径でも速い。
    """
    f = 4
    small = cv2.resize(gray, None, fx=1 / f, fy=1 / f, interpolation=cv2.INTER_AREA)
    k = odd(max(3, radius / f))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bg = cv2.morphologyEx(small, cv2.MORPH_CLOSE, ker)
    bg = cv2.GaussianBlur(bg, (0, 0), max(1.0, k / 4))
    bg = cv2.resize(bg, (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_CUBIC)
    out = gray.astype(np.float32) / np.maximum(bg.astype(np.float32), 1.0) * 235.0
    return np.clip(out, 0, 255).astype(np.uint8)


def apply_flat_field(gray, a, scale):
    bg = flat_field_fit(gray) if a.bg_mode == "fit" else None
    if bg is None:                              # fit が破綻したらクロージングに退避
        return flat_field(gray, a.bg_radius * scale)
    out = gray.astype(np.float32) / bg * float(np.percentile(bg, 90))
    return np.clip(out, 0, 255).astype(np.uint8)


def unsharp(gray, amount, sigma):
    if amount <= 0:
        return gray
    blur = cv2.GaussianBlur(gray, (0, 0), sigma)
    out = gray.astype(np.float32) * (1 + amount) - blur.astype(np.float32) * amount
    return np.clip(out, 0, 255).astype(np.uint8)


def sauvola(gray, window, k, r=128.0):
    """Sauvola 局所しきい値。 T = m * (1 + k * (s/r - 1))

    window が網点ピッチより小さいと、トーン部が局所的に正規化されて
    どの濃度も 50% グレーに潰れる。網点を残すには窓を大きく取ること。
    """
    w = odd(max(3, window))
    g = gray.astype(np.float32)
    mean = cv2.boxFilter(g, cv2.CV_32F, (w, w), normalize=True,
                         borderType=cv2.BORDER_REFLECT)
    sq = cv2.boxFilter(g * g, cv2.CV_32F, (w, w), normalize=True,
                       borderType=cv2.BORDER_REFLECT)
    std = np.sqrt(np.maximum(sq - mean * mean, 0))
    th = mean * (1.0 + k * (std / r - 1.0))
    return np.where(g > th, 255, 0).astype(np.uint8)


def threshold(gray, method, window, k):
    if method == "otsu":
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return bw
    if method == "fixed":
        _, bw = cv2.threshold(gray, int(k), 255, cv2.THRESH_BINARY)
        return bw
    return sauvola(gray, window, k)


def trim_margins(gray, ink_level=200, pad=8, min_ink_ratio=0.002):
    """周囲の白余白を落とす。行/列ごとのインク率で本体の外接矩形を取る。"""
    ink = (gray < ink_level)
    rows = ink.mean(axis=1) > min_ink_ratio
    cols = ink.mean(axis=0) > min_ink_ratio
    if not rows.any() or not cols.any():
        return gray
    y0, y1 = np.argmax(rows), len(rows) - np.argmax(rows[::-1])
    x0, x1 = np.argmax(cols), len(cols) - np.argmax(cols[::-1])
    h, w = gray.shape
    y0, x0 = max(0, y0 - pad), max(0, x0 - pad)
    y1, x1 = min(h, y1 + pad), min(w, x1 + pad)
    return gray[y0:y1, x0:x1]


def find_gutter(gray, ink_level=200, search=0.30):
    """見開きの綴じ目（中央付近で最も長く続く白い列）を探し、その中心xを返す。"""
    h, w = gray.shape
    ink = (gray < ink_level).mean(axis=0)
    c = w // 2
    lo, hi = int(c - w * search / 2), int(c + w * search / 2)
    blank = ink[lo:hi] < 0.004
    if not blank.any():
        return None
    best_len = best_start = cur = 0
    for i, b in enumerate(np.append(blank, False)):
        if b:
            cur += 1
        else:
            if cur > best_len:
                best_len, best_start = cur, i - cur
            cur = 0
    if best_len < w * 0.004:          # 白帯が細すぎるなら見開きではないと判断
        return None
    return lo + best_start + best_len // 2


def split_spread(gray, ink_level=200):
    """見開きを右ページ・左ページに分ける（日本の漫画の読み順で右が先）。"""
    x = find_gutter(gray, ink_level)
    if x is None:
        return None
    return [("_r", gray[:, x:]), ("_l", gray[:, :x])]


def dither_hybrid(gray, lo, hi):
    """低解像度でトーンが既にグレーに潰れている原稿向け。

    十分濃い画素は黒、十分薄い画素は白に確定させて線画を守り、
    中間調だけを誤差拡散ディザで打ち直す。網点は再現せず作り直す扱い。
    """
    if HAVE_PIL:
        d = np.array(Image.fromarray(gray).convert("1"))       # Floyd-Steinberg
        bw = np.where(d, 255, 0).astype(np.uint8)
    else:                                                      # 保険: 大域しきい値
        _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bw[gray <= lo] = 0
    bw[gray >= hi] = 255
    return bw


def local_std(gray, win=5):
    g = gray.astype(np.float32)
    m = cv2.boxFilter(g, cv2.CV_32F, (win, win), borderType=cv2.BORDER_REFLECT)
    sq = cv2.boxFilter(g * g, cv2.CV_32F, (win, win), borderType=cv2.BORDER_REFLECT)
    return np.sqrt(np.maximum(sq - m * m, 0))


def tone_auto(gray, a, window, k, dpi):
    """網点が解像できている所はしきい値、ボケてグレーに潰れた所はディザ。

    局所標準偏差で「まだ模様が残っている領域」と「平坦なグレーになった領域」を
    分け、前者はしきい値で元の網点・線トーンをそのまま残し、後者はディザで
    濃度だけ合わせる。線画は両者とも lo/hi の確定で守られる。
    """
    std = local_std(gray, odd(max(3, 5 * dpi / 600)))
    textured = (std >= a.auto_std).astype(np.uint8)
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (odd(9 * dpi / 600),) * 2)
    textured = cv2.morphologyEx(textured, cv2.MORPH_CLOSE, ker)
    textured = cv2.dilate(textured, ker) > 0

    th = threshold(gray, a.method, window, k)
    dt = dither_hybrid(gray, a.dither_lo, a.dither_hi)
    bw = np.where(textured, th, dt).astype(np.uint8)
    bw[gray <= a.dither_lo] = 0
    bw[gray >= a.dither_hi] = 255
    return bw


def despeckle(bw, min_black, min_white):
    """孤立した黒点（ゴマ塩）と、黒ベタ中の白抜けピンホールを消す。

    網点そのものを消さないよう、既定値は 1px ノイズだけを落とす程度。
    """
    out = bw
    if min_black > 0:
        ink = (out == 0).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
        kill = np.zeros(n, bool)
        kill[1:] = stats[1:, cv2.CC_STAT_AREA] < min_black
        out = np.where(kill[lab], 255, out).astype(np.uint8)
    if min_white > 0:
        paper = (out == 255).astype(np.uint8)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(paper, 8)
        kill = np.zeros(n, bool)
        kill[1:] = stats[1:, cv2.CC_STAT_AREA] < min_white
        out = np.where(kill[lab], 0, out).astype(np.uint8)
    return out


def round_dots(bw):
    """3x3 メディアン。1px のトゲ・階段を落とし、ベクトル化時のアンカーを減らす。"""
    return cv2.medianBlur(bw, 3)


def split_layers(bw, max_dot_area):
    """黒の連結成分を面積で振り分け、線画とトーンに分離する（実験的）。

    漫画では線画は広く繋がった 1 つの塊になり、網点は小さな独立成分になる。
    面積だけで判定すると、途切れた細線の断片までトーン側に落ちるので、
    外接矩形が縦横ともに網点1個の大きさに収まることも条件にする。
    ベタに近い濃いトーンは塊化するので線画側に残る。
    """
    ink = (bw == 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    max_dim = np.sqrt(max_dot_area) * 1.6
    is_tone = np.zeros(n, bool)
    is_tone[1:] = ((stats[1:, cv2.CC_STAT_AREA] <= max_dot_area)
                   & (stats[1:, cv2.CC_STAT_WIDTH] <= max_dim)
                   & (stats[1:, cv2.CC_STAT_HEIGHT] <= max_dim))
    tone_mask = is_tone[lab]
    line = np.where(ink.astype(bool) & ~tone_mask, 0, 255).astype(np.uint8)
    tone = np.where(tone_mask, 0, 255).astype(np.uint8)
    return line, tone


# ---------------------------------------------------------------- pipeline
def binarize(gray, a, dpi):
    s = dpi / 600.0
    if a.deskew:
        gray = rotate(gray, deskew_angle(gray))
    if not a.no_flatfield:
        gray = apply_flat_field(gray, a, s)
    if a.preblur > 0:          # 網点を意図的に潰して線画だけ残したいとき
        gray = cv2.GaussianBlur(gray, (0, 0), a.preblur * s)
    gray = unsharp(gray, a.sharpen, max(0.5, a.sharpen_radius * s))
    if a.tone == "dither":
        bw = dither_hybrid(gray, a.dither_lo, a.dither_hi)
    elif a.tone == "auto":
        bw = tone_auto(gray, a, a.window * s, a.k, dpi)
    else:
        bw = threshold(gray, a.method, a.window * s, a.k)
    bw = despeckle(bw, int(round(a.min_black * s * s)), int(round(a.min_white * s * s)))
    if a.round_dots:
        bw = round_dots(bw)
    return bw


def save_svg(bw, path, dpi, potrace_args=None):
    """potrace を呼び出して 1-bit 二値化画像を直接 SVG に変換・保存する。"""
    potrace_bin = shutil.which("potrace")
    if not potrace_bin:
        raise RuntimeError(
            "potrace が見つかりません。直接 SVG を出力するには potrace が必要です。\n"
            "  macOS: brew install potrace\n"
            "  Ubuntu/Debian: sudo apt install potrace\n"
            "※ 代わりに --format pbm で出力し、後から potrace に渡すことも可能です。"
        )
    # デフォルトの推奨軽量化パラメータ: -s -t 2 -a 1.3 -O 0.4
    if potrace_args is None:
        cmd = [potrace_bin, "-s", "-t", "2", "-a", "1.3", "-O", "0.4"]
    else:
        cmd = [potrace_bin, "-s"] + potrace_args

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".pbm", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        if HAVE_PIL:
            Image.fromarray(bw).convert("1").save(str(tmp_path))
        else:
            cv2.imencode(".pbm", bw)[1].tofile(str(tmp_path))

        cmd += [str(tmp_path), "-o", str(path)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"potrace の実行に失敗しました: {res.stderr}")
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def save_bilevel(bw, path, dpi, fmt=None, potrace_args=None):
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip(".")).lower()
    if fmt == "svg":
        save_svg(bw, path, dpi, potrace_args)
        return
    if HAVE_PIL:
        im = Image.fromarray(bw).convert("1")
        if fmt in ("tif", "tiff"):
            im.save(str(path), compression="group4", dpi=(dpi, dpi))
        elif fmt == "pbm":          # potrace が直接読める形式。dpi は持てない
            im.save(str(path))
        else:
            im.save(str(path), dpi=(dpi, dpi), optimize=True, bits=1)
    else:                                    # PIL が無ければ 8bit で保存
        cv2.imencode("." + fmt, bw)[1].tofile(str(path))



# ---------------------------------------------------------------- compare
PRESETS = {
    # 表示名             method     window  k     sharpen  flatfield
    "otsu (default)":  ("otsu",     61,  0.20,  0.6,  True),
    "otsu no-flatfld": ("otsu",     61,  0.20,  0.6,  False),
    "otsu sharp1.4":   ("otsu",     61,  0.20,  1.4,  True),
    "otsu nosharp":    ("otsu",     61,  0.20,  0.0,  True),
    "sauvola k.15":    ("sauvola",  61,  0.15,  0.6,  True),
    "sauvola k.20":    ("sauvola",  61,  0.20,  0.6,  True),
    "sauvola k.30":    ("sauvola",  61,  0.30,  0.6,  True),
    "sauvola win25":   ("sauvola",  25,  0.20,  0.6,  True),
}


def make_compare(gray, a, dpi, out):
    """中央（または --crop 指定）の一部を等倍で切り出し、設定違いを並べる。"""
    h, w = gray.shape
    cw = ch = min(a.crop_size, h, w)
    if a.crop:
        x, y = a.crop
    else:
        x, y = (w - cw) // 2, (h - ch) // 2
    x, y = max(0, min(x, w - cw)), max(0, min(y, h - ch))
    src = gray[y:y + ch, x:x + cw]

    tiles = []
    for name, (method, window, k, sharp, ff) in PRESETS.items():
        b = argparse.Namespace(**vars(a))
        b.method, b.window, b.k, b.sharpen, b.deskew = method, window, k, sharp, False
        b.no_flatfield = not ff
        t = cv2.cvtColor(binarize(src.copy(), b, dpi), cv2.COLOR_GRAY2BGR)
        cv2.rectangle(t, (0, 0), (cw - 1, 26), (255, 255, 255), -1)
        cv2.putText(t, name, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1,
                    cv2.LINE_AA)
        cv2.rectangle(t, (0, 0), (cw - 1, ch - 1), (0, 0, 255), 1)
        tiles.append(t)
    orig = cv2.cvtColor(src, cv2.COLOR_GRAY2BGR)
    cv2.rectangle(orig, (0, 0), (cw - 1, 26), (255, 255, 255), -1)
    cv2.putText(orig, "original", (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255),
                1, cv2.LINE_AA)
    tiles.insert(0, orig)

    cols = 3
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    blank = np.full_like(tiles[0], 255)
    rows[-1] += [blank] * (cols - len(rows[-1]))
    sheet = np.vstack([np.hstack(r) for r in rows])
    cv2.imencode(".png", sheet)[1].tofile(str(out))
    print(f"比較シート: {out}  (crop x={x} y={y} {cw}x{ch})")


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(
        description="漫画スキャンの2値化（網点保持・ベクトル化向け）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("inputs", nargs="+", help="入力画像")
    p.add_argument("-o", "--output", help="出力ファイル（入力1枚のとき）")
    p.add_argument("-O", "--outdir", help="出力ディレクトリ（複数枚のとき）")
    p.add_argument("--suffix", default="_bw", help="出力ファイル名に付ける接尾辞")
    p.add_argument("--format", default="png", choices=["png", "tif", "tiff", "pbm", "svg"],
                   help="出力形式 png / tif(G4圧縮) / pbm(potrace 直接) / svg(potrace 連携)")
    p.add_argument("--svg", action="store_true",
                   help="直接 SVG 形式で出力する（potrace を自動実行）")
    p.add_argument("--potrace-args",
                   help="potrace に渡す追加引数（例: '-t 3 -a 1.0 -O 0.2'）")
    p.add_argument("--dpi", type=float, default=0,
                   help="解像度。0ならファイルから読み、無ければ600とみなす")


    p.add_argument("--method", default="otsu", choices=["otsu", "sauvola", "fixed"],
                   help="しきい値の方式。地色補正後は otsu が網点を最も忠実に残す。"
                        "影・ムラが局所的に強い原稿では sauvola")
    p.add_argument("--window", type=float, default=61,
                   help="Sauvola の窓サイズ(px@600dpi)。網点ピッチの5倍以上を推奨")
    p.add_argument("--k", type=float, default=0.20,
                   help="Sauvola の k。小さいほど黒が増える（fixed では 0-255 の閾値）")
    p.add_argument("--bg-radius", type=float, default=600,
                   help="地色推定の半径(px@600dpi)。広いトーン面より大きく取らないと"
                        "トーンごと白く飛ばしてしまう")
    p.add_argument("--bg-mode", default="fit", choices=["fit", "close"],
                   help="地色推定の方式。fit=明るい側に多項式曲面を当てる（トーンを飛ばさない）"
                        " / close=クロージング（局所的な影に強いがトーンを飛ばしやすい）")
    p.add_argument("--no-flatfield", action="store_true", help="地色補正をしない")
    p.add_argument("--preblur", type=float, default=0,
                   help="しきい値の前にぼかす半径(px@600dpi)。網点を潰して線画だけ"
                        "残したいときに --method fixed と併用する")
    p.add_argument("--sharpen", type=float, default=0.6, help="アンシャープ量 0で無効")
    p.add_argument("--sharpen-radius", type=float, default=1.2,
                   help="アンシャープ半径(px@600dpi)")
    p.add_argument("--min-black", type=float, default=2,
                   help="この面積(px@600dpi)未満の孤立黒点を消す")
    p.add_argument("--min-white", type=float, default=2,
                   help="この面積(px@600dpi)未満の白抜けを埋める")
    p.add_argument("--tone", default="keep", choices=["keep", "auto", "dither"],
                   help="keep=網点をそのまま2値化 / "
                        "auto=解像できている網点はそのまま、ボケた部分だけディザ / "
                        "dither=中間調を全部誤差拡散で打ち直す")
    p.add_argument("--auto-std", type=float, default=30,
                   help="--tone auto の判定。局所標準偏差がこれ以上なら網点が残っていると見なす")
    p.add_argument("--dither-lo", type=float, default=70,
                   help="--tone dither でこれ以下の濃さは黒に確定（線画を守る）")
    p.add_argument("--dither-hi", type=float, default=235,
                   help="--tone dither でこれ以上の明るさは白に確定")
    p.add_argument("--trim", action="store_true", help="周囲の白余白を落とす")
    p.add_argument("--split", action="store_true",
                   help="見開き1枚を綴じ目で2ページに分割する（右ページ_r・左ページ_l）")
    p.add_argument("--deskew", action="store_true", help="傾きを自動補正する")
    p.add_argument("--round-dots", action="store_true",
                   help="3x3メディアンで輪郭を丸める（ベクトル化のアンカー削減）")
    p.add_argument("--layers", action="store_true",
                   help="線画とトーンを別ファイルに分離出力する（実験的）")
    p.add_argument("--max-dot-area", type=float, default=120,
                   help="--layers でトーン扱いにする連結成分の最大面積(px@600dpi)")

    p.add_argument("--compare", metavar="OUT.PNG", help="設定比較シートを作る")
    p.add_argument("--crop", type=int, nargs=2, metavar=("X", "Y"),
                   help="比較シートの切り出し左上座標")
    p.add_argument("--crop-size", type=int, default=700, help="比較シートの切り出し辺長")
    a = p.parse_args()

    paths = [Path(x) for x in a.inputs]
    for path in paths:
        if not path.exists():
            sys.exit(f"見つかりません: {path}")
        full = read_gray(path)
        dpi = a.dpi or read_dpi(path, 600.0)

        if a.compare:
            make_compare(full, a, dpi, a.compare)
            return

        if a.trim:
            full = trim_margins(full)
        pages = [("", full)]
        if a.split:
            sp = split_spread(full)
            if sp is None:
                print(f"{path.name}: 綴じ目が見つからないので分割しません")
            else:
                pages = [(tag, trim_margins(g) if a.trim else g) for tag, g in sp]

        # フォーマットの解決
        fmt = a.format.lower()
        if a.svg:
            fmt = "svg"
        elif a.output and Path(a.output).suffix:
            ext = Path(a.output).suffix.lstrip(".").lower()
            if ext in ("svg", "pbm", "png", "tif", "tiff"):
                fmt = ext

        potrace_args = a.potrace_args.split() if a.potrace_args else None

        for tag, gray in pages:
            bw = binarize(gray, a, dpi)

            if a.output and len(paths) == 1 and len(pages) == 1:
                out = Path(a.output)
            else:
                d = Path(a.outdir) if a.outdir else path.parent
                d.mkdir(parents=True, exist_ok=True)
                base = Path(a.output).stem if (a.output and len(paths) == 1) else path.stem
                out = d / f"{base}{tag}{a.suffix}.{fmt}"
            save_bilevel(bw, out, dpi, fmt, potrace_args=potrace_args)
            ink = float((bw == 0).mean() * 100)
            ncc = cv2.connectedComponents((bw == 0).astype(np.uint8), 8)[0] - 1
            print(f"{path.name}{tag} -> {out}  {bw.shape[1]}x{bw.shape[0]} "
                  f"{dpi:.0f}dpi  黒率 {ink:.1f}%  黒の連結成分 {ncc:,}個"
                  f"{'  ← そのままトレースするとパスが重い' if ncc > 20000 else ''}")

            if a.layers:
                sc = dpi / 600.0
                line, tone = split_layers(bw, a.max_dot_area * sc * sc)
                for lt, img in (("_line", line), ("_tone", tone)):
                    lp = out.with_name(out.stem + lt + out.suffix)
                    save_bilevel(img, lp, dpi, fmt, potrace_args=potrace_args)
                    print(f"   {lt[1:]}: {lp}")



if __name__ == "__main__":
    main()
