import numpy as np, cv2, sys
np.random.seed(0)
h,w=2400,1700
page=np.full((h,w),255,np.uint8)
yy,xx=np.mgrid[0:h,0:w].astype(np.float32)
th=np.deg2rad(45);u=xx*np.cos(th)+yy*np.sin(th);v=-xx*np.sin(th)+yy*np.cos(th)
cell=10.0;d=np.sqrt(((u%cell)-cell/2)**2+((v%cell)-cell/2)**2)
for dens,box in [(0.15,(200,300,900,900)),(0.35,(200,1050,900,1650)),(0.60,(1000,300,1700,900))]:
    r=np.sqrt(dens/np.pi)*cell; y0,x0,y1,x1=box
    page[y0:y1,x0:x1]=np.where(d[y0:y1,x0:x1]<r,0,255)
cv2.rectangle(page,(150,250),(1550,2150),0,6); cv2.line(page,(150,950),(1550,950),0,4)
for i in range(12): cv2.line(page,(1050+i*40,1000),(1000+i*40,1650),0,1+i%3)
cv2.circle(page,(1300,1900),180,0,-1)
cv2.putText(page,"MANGA TEST",(250,2050),cv2.FONT_HERSHEY_SIMPLEX,2.0,0,4,cv2.LINE_AA)
cv2.putText(page,"thin lines and small text 12345",(250,1800),cv2.FONT_HERSHEY_SIMPLEX,0.8,0,1,cv2.LINE_AA)
gt=(page<128)
bw=cv2.imdecode(np.fromfile(sys.argv[1],np.uint8),cv2.IMREAD_GRAYSCALE)<128
print(sys.argv[1], "一致率 %.2f%%"%((gt==bw).mean()*100), " GT黒率 %.2f%%"%(gt.mean()*100), " 出力黒率 %.2f%%"%(bw.mean()*100))
for name,box in [("トーン15%",(200,300,900,900)),("トーン35%",(200,1050,900,1650)),("トーン60%",(1000,300,1700,900)),("細線",(1000,1000,1650,1530)),("小文字",(1750,250,1820,1300))]:
    y0,x0,y1,x1=box
    print("   %-9s GT黒 %5.1f%% -> 出力 %5.1f%%   一致 %5.2f%%"%(name,gt[y0:y1,x0:x1].mean()*100,bw[y0:y1,x0:x1].mean()*100,(gt[y0:y1,x0:x1]==bw[y0:y1,x0:x1]).mean()*100))
