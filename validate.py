import numpy as np, glob, os, re, sys
from multiprocessing import Pool
D=r"D:\Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games\thesettlers4\Map\User"
def decode(g,key):
    g.reset()
    out=g.alloc(0xb8); g.uc.mem_write(out,b"\0"*0xb8)
    k=g.alloc(64); g.uc.mem_write(k,(key+"\0").encode("utf-16-le"))
    g.call(0x50ADA0, ecx=out, edx=k)
    return bytes(g.uc.mem_read(out,0xb8))
def run(path):
    from s4gen import S4Generator
    from s4map import read_segments
    g=S4Generator()
    key=re.search(r"_(L[0-9A-V]{7})_",os.path.basename(path)).group(1)
    v,segs=read_segments(path,g); S={t:d for t,h,d in segs}
    n=int(round((len(S[13])//4)**.5))
    rA=np.frombuffer(S[13],np.uint8).reshape(n,n,4); rB=np.frombuffer(S[6],np.uint8).reshape(n,n,4)
    g.setup(decode(g,key)); ok,size,la,lb=g.generate()
    A=np.frombuffer(la,np.uint8).reshape(size,size,4); B=np.frombuffer(lb,np.uint8).reshape(size,size,4)
    if size!=n: return key,f"size mismatch {size} vs {n}"
    return key, "A "+" ".join(f"{(A[:,:,c]==rA[:,:,c]).mean():.4f}" for c in range(4))+" | B "+" ".join(f"{(B[:,:,c]==rB[:,:,c]).mean():.4f}" for c in range(4))
if __name__=="__main__":
    files=sorted(glob.glob(os.path.join(D,"UnitedLeague_*.map")))
    with Pool(7) as p:
        for k,r in p.imap_unordered(run,files): print(k,r,flush=True)
