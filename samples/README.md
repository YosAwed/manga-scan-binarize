# サンプル画像 (Samples)

このディレクトリには、クローン後すぐに本ツールの動作や設定の効き目を試せるテスト用スキャン画像が含まれています。  
すべてプログラム（`make_samples.py`）により人工的に合成された画像のため、**著作権フリー**で自由にお使いいただけます。

## 含まれるファイル

1. **`sample_page.jpg`** (単ページ原稿 / 1700×2400 / 600dpi相当)
   - 3段のコマ割り
   - 網点スクリーントーン（15%、35%、60%、グラデーション）
   - 効果線（集中線）、ハッチング（細線）、黒ベタ、白抜き文字
   - スキャナ特有の紙の地色、照明ムラ、光学ボケ、軽微なノイズ

2. **`sample_spread.jpg`** (見開き原稿 / 3200×2200 / 600dpi相当)
   - 右ページ（`_r`）と左ページ（`_l`）の2ページ構成
   - 本を開いたときのノド（中央綴じ目）の自然な影
   - スキャン台の白余白
   - `--split`（自動見開き分割）および `--trim`（白余白トリム）のテスト用

3. **`make_samples.py`**
   - 上記の画像をいつでも再生成できるPythonスクリプト。

4. **`sample_page.svg`** (ベクター化サンプル / SVG)
   - `sample_page.jpg` を本ツールで2値化し、potrace で自動ベクター化した出力サンプル。
   - 網点や細線、コマ枠が美しいベクターパスとして保持されていることを確認できます。


## お試しコマンド例

```sh
# 単ページを直接 SVG にベクター化（potrace 自動連携）
./mb samples/sample_page.jpg -o out.svg --dpi 600 --round-dots

# 単ページの2値化（1-bit PNG）
./mb samples/sample_page.jpg -o out.png --dpi 600

# 設定の効き比べシートを作成
./mb samples/sample_page.jpg --compare cmp.png

# 見開きを2ページに分割し、余白を落として直接 SVG で出力
./mb samples/sample_spread.jpg -O out/ --split --trim --svg --round-dots
```

