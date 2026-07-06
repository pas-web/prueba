#!/usr/bin/env python3
"""
generar.py — valida recorrido.json, genera iconos de la PWA, placas QR
imprimibles y actualiza la versión del caché. Ejecutar desde la carpeta
de la app (donde están index.html y recorrido.json).

Uso: python3 generar.py [--version N]
Requiere: pillow, qrcode  (pip install pillow qrcode --break-system-packages)
"""
import json, sys, os, math, re, argparse

def err(msg): print(f"  ✗ {msg}"); return 1

def validar(R):
    fallos = 0
    ids = set()
    for t in R.get("tramos", []):
        if "id" not in t: fallos += err("Tramo sin id"); continue
        if t["id"] in ids: fallos += err(f"id duplicado: {t['id']}")
        ids.add(t["id"])
    for t in R["tramos"]:
        destinos = []
        if t.get("ir"): destinos.append(t["ir"])
        for op in t.get("opciones", []): destinos.append(op.get("ir"))
        if t.get("qr", {}).get("revelacion", {}).get("ir"):
            destinos.append(t["qr"]["revelacion"]["ir"])
        for d in destinos:
            if d and d != "FIN" and d not in ids:
                fallos += err(f"Tramo {t['id']} apunta a '{d}' que no existe")
        if t.get("qr") and not t["qr"].get("codigo"):
            fallos += err(f"Tramo {t['id']} tiene qr sin 'codigo'")
        e = t.get("enigma")
        if e:
            if e.get("tipo") not in ("respuesta", "multiple", "secuencia"):
                fallos += err(f"Tramo {t['id']}: enigma.tipo inválido: {e.get('tipo')}")
            if e.get("tipo") == "respuesta" and not e.get("respuesta"):
                fallos += err(f"Tramo {t['id']}: enigma respuesta sin 'respuesta'")
            if e.get("tipo") == "multiple":
                ops = set(map(str, e.get("opciones", [])))
                corr = set(map(str, e.get("correctas", [])))
                if not corr: fallos += err(f"Tramo {t['id']}: enigma multiple sin 'correctas'")
                if not corr.issubset(ops): fallos += err(f"Tramo {t['id']}: 'correctas' no está contenida en 'opciones'")
            if e.get("tipo") == "secuencia" and len(e.get("secuencia", [])) < 2:
                fallos += err(f"Tramo {t['id']}: enigma secuencia necesita 2+ elementos")
            if not e.get("pistas"):
                print(f"  ⚠ Tramo {t['id']}: enigma sin 'pistas' (recomendadas 3 graduales)")
            rec = e.get("recompensa", {})
            if rec.get("ir") and rec["ir"] != "FIN":
                destinos.append(rec["ir"])
    # segunda pasada: destinos de recompensas de enigma
    for t in R["tramos"]:
        rec = t.get("enigma", {}).get("recompensa", {})
        d = rec.get("ir")
        if d and d != "FIN" and d not in ids:
            fallos += err(f"Recompensa del enigma en {t['id']} apunta a '{d}' que no existe")
    inicio = R.get("inicio", R["tramos"][0]["id"])
    if inicio not in ids: fallos += err(f"'inicio' apunta a '{inicio}' que no existe")
    # archivos declarados vs existentes
    for t in R["tramos"]:
        for campo in ("audio", "imagen"):
            for obj in (t, t.get("qr", {}).get("revelacion", {}),
                        t.get("enigma", {}).get("recompensa", {}),
                        t.get("objeto", {}) or {},
                        (t.get("enigma", {}).get("recompensa", {}) or {}).get("objeto", {}) or {}):
                f = obj.get(campo)
                if f and not os.path.exists(f):
                    fallos += err(f"Archivo declarado pero no encontrado: {f}")
    for nombre, val in R.get("ambientes", {}).items():
        if not val.startswith("sintetizado:") and not os.path.exists(val):
            fallos += err(f"Ambiente '{nombre}' apunta a archivo inexistente: {val}")
    return fallos

def lista_archivos(R):
    """Todos los assets que el service worker debe precachear."""
    archivos = set()
    def agrega(obj):
        for campo in ("audio", "imagen"):
            if obj.get(campo): archivos.add("./" + obj[campo])
    for t in R["tramos"]:
        agrega(t)
        if t.get("qr", {}).get("revelacion"): agrega(t["qr"]["revelacion"])
        rec = t.get("enigma", {}).get("recompensa")
        if rec:
            agrega(rec)
            if rec.get("objeto"): agrega(rec["objeto"])
        if t.get("objeto"): agrega(t["objeto"])
    for val in R.get("ambientes", {}).values():
        if not val.startswith("sintetizado:"): archivos.add("./" + val)
    return sorted(archivos)

def iconos(R):
    from PIL import Image, ImageDraw
    p = R.get("paleta", {})
    fondo, acento, texto = p.get("fondo", "#12332B"), p.get("acento", "#D9A441"), p.get("texto", "#F5EFE2")
    for size in (192, 512):
        img = Image.new("RGB", (size, size), fondo)
        d = ImageDraw.Draw(img)
        w = max(6, size // 28)
        pts = [(i, size*0.55 + math.sin(i/size*3.5*math.pi)*size*0.16) for i in range(0, size+1, 4)]
        d.line(pts, fill=acento, width=w, joint="curve")
        cx, cy = pts[int(len(pts)*0.7)]
        d.ellipse([cx-w*1.4, cy-w*1.4, cx+w*1.4, cy+w*1.4], fill=texto)
        img.save(f"icono-{size}.png")
    print("  ✓ iconos generados")

def placas_qr(R):
    import qrcode
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs("qr", exist_ok=True)
    p = R.get("paleta", {})
    n = 0
    for t in R["tramos"]:
        q = t.get("qr")
        if not q: continue
        img = qrcode.make(q["codigo"], box_size=14, border=3).convert("RGB")
        W, H = img.width + 80, img.height + 170
        lienzo = Image.new("RGB", (W, H), p.get("texto", "#F5EFE2"))
        d = ImageDraw.Draw(lienzo)
        lienzo.paste(img, (40, 40))
        try:
            f1 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
            f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
        except Exception:
            f1 = f2 = None
        d.text((W//2, img.height+70), (t.get("titulo") or t["id"]).upper()[:34],
               fill=p.get("fondo", "#12332B"), font=f1, anchor="mm")
        palabra = q.get("palabra") or q["codigo"].split(":")[-1]
        d.text((W//2, img.height+115), f"Palabra de respaldo: {palabra}",
               fill="#8A5A33", font=f2, anchor="mm")
        lienzo.save(f"qr/qr-{t['id']}.png")
        n += 1
    print(f"  ✓ {n} placa(s) QR generadas en qr/")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", type=int, default=None, help="número de versión de caché")
    args = ap.parse_args()

    R = json.load(open("recorrido.json", encoding="utf-8"))
    print("Validando recorrido.json…")
    if validar(R):
        print("Corrige los errores antes de empaquetar."); sys.exit(1)
    print("  ✓ estructura correcta")

    R["archivos"] = lista_archivos(R)
    json.dump(R, open("recorrido.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  ✓ {len(R['archivos'])} archivo(s) declarados para descarga offline")

    iconos(R)
    placas_qr(R)

    if args.version:
        sw = open("sw.js", encoding="utf-8").read()
        sw = re.sub(r'sendero-v\d+', f'sendero-v{args.version}', sw)
        open("sw.js", "w", encoding="utf-8").write(sw)
        print(f"  ✓ caché actualizado a sendero-v{args.version}")
    print("Listo. Sube toda la carpeta a GitHub Pages.")

if __name__ == "__main__":
    main()
