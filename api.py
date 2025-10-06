from flask import Flask, request, jsonify
from flask_cors import CORS
import httpx, asyncio, time

app = Flask(__name__)
CORS(app)  # luego puedes restringir orígenes

HEADERS = {"User-Agent":"Mozilla/5.0 (Android) IPTV-Checker","Accept":"*/*"}

def parse_m3u8(text: str):
    out=[]; lines=text.splitlines()
    for i,l in enumerate(lines):
        if l.startswith("#EXTINF"):
            name = l.split(",",1)[-1].strip() or "SIN NOMBRE"
            if i+1 < len(lines):
                u = lines[i+1].strip()
                if u.startswith("http"): out.append((name,u))
    return out

async def head_or_range(client,u,timeout=10):
    try:
        r = await client.head(u, headers=HEADERS, timeout=timeout, follow_redirects=True)
        return r.status_code, (r.headers.get("content-type") or "").lower()
    except Exception:
        pass
    try:
        r = await client.get(u, headers={**HEADERS,"Range":"bytes=0-0"},
                             timeout=timeout, follow_redirects=True)
        return r.status_code, (r.headers.get("content-type") or "").lower()
    except Exception:
        return 0, ""

def etiqueta(sc,ct):
    if sc==200 and any(x in ct for x in [
        "application/vnd.apple.mpegurl","application/x-mpegurl","audio/x-mpegurl","video/mp2t","mpegurl","mp2t"
    ]): return "ONLINE"
    if "text/html" in ct: return "BLOQ"
    if sc in (403,404,410,451) or sc>=500 or sc==0: return "OFF"
    return "OFF"

async def verificar_async(url, conc=20, timeout=10):
    t0=time.time()
    async with httpx.AsyncClient(timeout=timeout, headers=HEADERS, follow_redirects=True) as c:
        r = await c.get(url); r.raise_for_status()
        entries = parse_m3u8(r.text)

    limits = httpx.Limits(max_keepalive_connections=conc, max_connections=conc)
    async with httpx.AsyncClient(timeout=timeout, headers=HEADERS, limits=limits, follow_redirects=True) as c:
        sem = asyncio.Semaphore(conc)
        async def uno(name,u):
            async with sem:
                sc,ct = await head_or_range(c,u,timeout)
                return {"name":name,"url":u,"http":sc,"ctype":ct,"status":etiqueta(sc,ct)}
        items = await asyncio.gather(*[uno(n,u) for n,u in entries])

    return {"count": len(items), "took": round(time.time()-t0,1), "items": items}

@app.get("/verify")
def verify():
    url = request.args.get("playlist","").strip()
    if not url: return jsonify({"error":"missing playlist"}), 400
    conc = int(request.args.get("conc","20") or 20)
    tout = int(request.args.get("timeout","10") or 10)
    try:
        data = asyncio.run(verificar_async(url, conc, tout))
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/")
def root():
    return {"ok": True, "use": "/verify?playlist=URL&conc=20&timeout=10"}

if __name__ == "__main__":
    # Railway asigna PORT por variable; usa 8000 localmente
    import os
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
