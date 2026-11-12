import os
W='C:/Users/marcu/Videos/cursor-os-base-fi1-kernel2/'
def rd(p): return open(W+p,encoding='utf-8',newline='').read()
def wr(p,s): open(W+p,'w',encoding='utf-8',newline='').write(s)
def rep(p,old,new,count=1):
    s=rd(p)
    n=s.count(old)
    assert n==count, (p, n, old[:80])
    wr(p,s.replace(old,new))

import re as _re
def rep(p,old,new,count=1):
    s=rd(p)
    n=s.count(old)
    if n==count:
        wr(p,s.replace(old,new)); return
    pat='\n'.join(_re.escape(l.rstrip())+r'[ \t]*' for l in old.split('\n'))
    m=list(_re.finditer(pat,s))
    assert len(m)==count, (p, n, len(m), old[:80])
    for mm in reversed(m):
        s=s[:mm.start()]+new+s[mm.end():]
    wr(p,s)
