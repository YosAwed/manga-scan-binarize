import numpy as np, cv2
h, w = 2400, 1700           # ~600dpi の B6 相当
page = np.full((h, w), 255, np.uint8)
# 網点トーン（濃度違い 3 段）: 60lpi @600dpi -> ピッチ10px
yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
th = np.deg2rad(45); u = xx*np.cos(th)+yy*np.sin(th); v = -xx*np.sin(th)+yy*np.cos(th)
cell = 10.0
d = np.sqrt(((u % cell)-cell/2)**2 + ((v % cell)-cell/2)**2)
for i, (dens, box) in enumerate([(0.15,(200,300,900,900)), (0.35,(200,1050,900,1650)), (0.60,(1000,300,1700,900))]):
    r = np.sqrt(dens/np.pi)*cell
    y0,x0,y1,x1 = box
    page[y0:y1, x0:x1] = np.where(d[y0:y1, x0:x1] < r, 0, 255)
# 線画: コマ枠 + 細線 + ベタ
cv2.rectangle(page, (150,250), (1550,2150), 0, 6)
cv2.line(page, (150,950), (1550,950), 0, 4)
for i in range(12):
    cv2.line(page, (1050+i*40, 1000), (1000+i*40, 1650), 0, 1+i%3)
cv2.circle(page, (1300,1900), 180, 0, -1)
cv2.putText(page, "MANGA TEST", (250, 2050), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 0, 4, cv2.LINE_AA)
cv2.putText(page, "thin lines and small text 12345", (250, 1800), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 0, 1, cv2.LINE_AA)
# スキャンの劣化を再現: 照明ムラ + 紙の地色 + ぼけ + ノイズ + JPEG
g = page.astype(np.float32)
g = cv2.GaussianBlur(g, (0,0), 0.9)
shade = 1.0 - 0.22*((xx/w-0.15)**2 + (yy/h-0.6)**2)*1.8      # 左上が明るく右下が暗い
g = g*shade*0.93 + 12                                        # 紙の地色は 235 前後
g += np.random.normal(0, 4.0, g.shape)
g = np.clip(g,0,255).astype(np.uint8)
ok, enc = cv2.imencode(".jpg", g, [cv2.IMWRITE_JPEG_QUALITY, 88]); enc.tofile("test_scan.jpg")
print("test_scan.jpg", g.shape, "bg mean", g[100:200,100:200].mean())
