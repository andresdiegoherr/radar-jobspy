#!/usr/bin/env python3
"""
JobSpy × RADAR — Barrido complementario a las alertas de LinkedIn (Grupo A)
Alineado con: 2026-09-01_informe-preferencias-geograficas-y-alertas_v1-0.md

Cubre lo que las alertas NO alcanzan:
  · Grupos B/C/D (desdobles por ciudad, castellano/inglés, territorio ampliado)
  · Listado completo (sin el límite de 6 vacantes por email de alerta)
  · Portugal, UK, LATAM, Golfo — con la regla dura RELOCATE aplicada
  · Solo ofertas vivas (scraping en vivo, sin 404 ni zombis de 2024)

Filtro = sección 3.1 del informe (roles admitidos) + 3.2 (exclusiones duras).
Scoring geográfico = jerarquía 2.1: Barcelona > España > UE > UK > LATAM > Golfo > Global.
Salida con prioridades P1/P2/P3 (convención Inbox RADAR).

Uso:
    python3 jobspy_radar.py           # barrido completo (~3-4 min)
    python3 jobspy_radar.py --quick   # solo 2 búsquedas (test)
"""

import sys
import re
from datetime import date
from pathlib import Path

import pandas as pd
from jobspy import scrape_jobs

# ─────────────────────────────────────────────────────────────
# 1. BÚSQUEDAS — complementan (no duplican) las alertas del Grupo A
#    (término, ubicación, país_indeed, mercado, solo_remoto)
# ─────────────────────────────────────────────────────────────
BUSQUEDAS = [
    # ES core — desdoble por ciudad (Grupo B) y roles clave
    ("creative director",     "Barcelona, Spain",  "spain",     "barcelona", False),
    ("director creativo",     "Barcelona, Spain",  "spain",     "barcelona", False),
    ("creative director",     "Madrid, Spain",     "spain",     "espana",    False),
    ("art director",          "Barcelona, Spain",  "spain",     "barcelona", False),
    # ES — roles del Grupo C (castellano/inglés)
    ("head of brand",         "Spain",             "spain",     "espana",    False),
    ("design director",       "Spain",             "spain",     "espana",    False),
    ("creative strategist",   "Spain",             "spain",     "espana",    False),
    ("brand strategist",      "Spain",             "spain",     "espana",    False),
    ("content director",      "Spain",             "spain",     "espana",    False),
    ("creative producer",     "Spain",             "spain",     "espana",    False),
    # Especialidades IA / ops (A7, D7, D8) — remoto
    ("creative technologist", "Spain",             "spain",     "espana",    True),
    ("design operations",     "Spain",             "spain",     "espana",    True),
    # IA creativa (2-sep-2026). Verificado que la puntuación ya separa bien lo
    # tuyo de lo técnico: "AI Creative Director" da 68/P1 y "Head of AI" 10/P4,
    # porque el dominio lo carga "creative", no "AI". Faltaba solo buscarlas.
    ("ai creative director",  "Spain",             "spain",     "espana",    True),
    ("ai creative director",  "United States",     "usa",       "usa",       True),
    ("generative ai design",  "Spain",             "spain",     "espana",    True),
    # UX de dirección (2-sep-2026). La puntuación se arregló en el motor v6.13.0
    # (antes "Head of UX" daba 6 puntos e era invisible), pero sin estas búsquedas
    # no llegaría ninguna: ningún término anterior las cubría.
    ("head of ux",            "Spain",             "spain",     "espana",    False),
    ("ux director",           "Spain",             "spain",     "espana",    False),
    ("head of product design","Spain",             "spain",     "espana",    False),
    # Territorio ampliado (Grupo D)
    ("creative director",     "Lisbon, Portugal",  "portugal",  "ue",        False),
    ("creative director",     "London, United Kingdom", "uk",   "uk",        False),
    ("director creativo",     "Mexico City, Mexico", "mexico",  "latam",     False),
    ("director creativo",     "Buenos Aires, Argentina", "argentina", "latam", False),
    # Golfo (prioridad 4 del informe — hueco sin cobertura automatizada)
    ("creative director",     "Dubai",             "united arab emirates", "golfo", False),
    # EE.UU. — SOLO remoto (regla 2.2 actualizada 01/09/2026: remoto SÍ,
    # relocate SÍ, onsite sin relocate NO)
    ("creative director",     "United States",     "usa",       "usa",       True),
    ("brand director",        "United States",     "usa",       "usa",       True),
    ("design director",       "United States",     "usa",       "usa",       True),
]

SITES = ["indeed", "google", "linkedin"]
RESULTS_PER_SEARCH = 25
HOURS_OLD = 24 * 14   # 14 días

# ─────────────────────────────────────────────────────────────
# 2. FILTRO RADAR — sección 3.1 (roles admitidos, 33 títulos)
# ─────────────────────────────────────────────────────────────
ROLES_ADMITIDOS = [
    # Creatividad y dirección
    "creative director", "director creativo", "directora creativa",
    "dirección creativa", "direccion creativa", "executive creative director",
    "group creative director", "chief creative officer", "head of creative",
    "creative lead", "vp creative", "associate creative director",
    "director de arte", "art director",
    # Marca y estrategia
    "brand director", "head of brand", "brand lead", "brand strategist",
    "brand strategy", "estratega de marca", "director de marca",
    "brand consultant", "consultor de marca", "chief brand officer",
    "brand experience", "responsable de marca",
    # Diseño
    "design director", "director de diseño", "head of design", "design lead",
    "lead designer", "brand designer", "foresight",
    # Comunicación y contenido
    "communications director", "director de comunicación",
    "head of communications", "content director", "director de contenidos",
    "content lead", "editorial director", "responsable de comunicación",
    # Estudio y operaciones
    "studio director", "head of studio", "director de estudio",
    "creative producer", "productor creativo", "creative operations",
    "design operations", "head of motion", "motion director",
    # Tecnología e IA
    "creative technologist", "ai creative", "generative ai",
    "head of creative technology", "creative innovation",
    "ai creative director", "creative ai", "ai brand",
    # UX de dirección — añadido 2-sep-2026 junto al arreglo del motor v6.13.0
    "head of ux", "ux director", "director of ux", "head of product design",
    "product design director", "experiencia de usuario",
    "creative strategist", "creative strategy",
    # Agencia / negocio / marketing con alcance de marca
    "client partner", "brand marketing director", "head of marketing & brand",
    "interim creative director", "fractional creative director",
]

# Sección 3.2 — exclusiones duras (si aparecen en el TÍTULO → descarte)
EXCLUSIONES_TITULO = [
    # Nivel
    "junior", "intern", "becari", "práctica", "practica", "trainee",
    "graduate", "estudiante", "student",
    # Áreas no afines
    "sales", "ventas", "comercial", "business development",
    "finance", "financial", "accounting", "contab", "legal", "abogado",
    "tax ", "payroll", "software engineer", "developer", "devops",
    "backend", "frontend", "full stack", "data engineer", "qa engineer",
    # Marketing de conversión pura
    "performance marketing", "growth marketing", "demand generation",
    "seo specialist", "sem specialist", "product marketing",
]

# Regla de oro 2.3 — detección RELOCATE
KEYWORDS_RELOCATE = [
    "relocation", "relocation package", "relocation assistance",
    "visa sponsorship", "sponsor visa", "sponsorship available",
    "ayuda al traslado", "paquete de reubicación", "reubicación",
    "visado patrocinado", "housing allowance",
]

KEYWORDS_REMOTO = [
    "remote", "remoto", "teletrabajo", "work from anywhere",
    "fully remote", "100% remote", "en remoto",
]

# Jerarquía geográfica 2.1 → puntos
# "usa" añadido 01/09/2026: remoto/relocate admitido, al nivel de LATAM/Golfo
SCORE_MERCADO = {"barcelona": 6, "espana": 5, "ue": 4, "uk": 3,
                 "latam": 2, "golfo": 2, "usa": 2, "global": 1}

# ─────────────────────────────────────────────────────────────

def evaluar(row):
    """Aplica el filtro RADAR. Devuelve (prioridad, score, etiquetas) o None si descarte."""
    titulo = str(row.get("title", "")).lower()
    desc = str(row.get("description", "") or "").lower()
    loc = str(row.get("location", "") or "").lower()
    mercado = row["mercado"]
    etiquetas = []

    # 1. Exclusiones duras (3.2)
    if any(kw in titulo for kw in EXCLUSIONES_TITULO):
        return None

    # 2. Barcelona detectada en la ubicación → sube de tier
    if "barcelona" in loc:
        mercado = "barcelona"

    # 3. Señales de remoto y relocate
    es_remoto = bool(row.get("is_remote")) or any(k in titulo + " " + desc for k in KEYWORDS_REMOTO)
    relocate = any(k in desc for k in KEYWORDS_RELOCATE)
    if relocate:
        etiquetas.append("RELOCATE")

    # 4. EE.UU. (regla 2.2 ACTUALIZADA por Andrés el 01/09/2026):
    #    Ya NO es descarte total. EE.UU. se trata como el resto de mercados
    #    internacionales: remoto 100% SÍ (aunque implique viajar 1-2 veces/año),
    #    relocate/visado SÍ, onsite sin relocate NO.
    es_usa = "united states" in loc or bool(re.search(r",\s*us\b", loc))
    if es_usa:
        mercado = "usa"

    # 5. Regla dura 2.3: onsite fuera de España sin relocate → descarte
    #    (si no hay descripción no podemos verificar → se conserva como P3 VERIFICAR)
    if mercado in ("ue", "uk", "latam", "golfo", "usa") and not es_remoto and not relocate:
        if desc.strip() and desc != "nan":
            return None
        etiquetas.append("VERIFICAR-UBICACION")

    # 6. Match de rol (3.1)
    rol_ok = any(r in titulo for r in ROLES_ADMITIDOS)

    # 7. Score
    score = SCORE_MERCADO.get(mercado, 1)
    if rol_ok:
        score += 10
    if relocate:
        score += 2
    if es_remoto:
        score += 1

    # 8. Prioridad (convención Inbox RADAR)
    if rol_ok and mercado in ("barcelona", "espana"):
        prioridad = "P1"
    elif rol_ok and (mercado in ("ue", "uk") and (es_remoto or relocate) or relocate):
        prioridad = "P2"
    elif rol_ok:
        prioridad = "P3"
    else:
        prioridad = "REVISAR"   # no matchea los 33 títulos pero no está excluida

    return prioridad, score, "|".join(etiquetas), mercado


def main():
    quick = "--quick" in sys.argv
    busquedas = BUSQUEDAS[:2] if quick else BUSQUEDAS

    frames, brutas = [], 0
    for termino, ubicacion, pais, mercado, remoto in busquedas:
        # MEJORA v1.1: en mercados fuera de España descargamos la descripción
        # completa de LinkedIn (más lento) para poder aplicar la regla RELOCATE
        # 2.3 en el momento, en vez de dejar ofertas en VERIFICAR-UBICACION.
        fetch_desc = mercado in ("ue", "uk", "latam", "golfo", "usa")
        print(f"🔎 «{termino}» · {ubicacion} [{mercado}]"
              f"{' (remoto)' if remoto else ''}{' +desc' if fetch_desc else ''} …", flush=True)
        try:
            df = scrape_jobs(
                site_name=SITES,
                search_term=termino,
                google_search_term=f"{termino} jobs in {ubicacion}",
                location=ubicacion,
                results_wanted=RESULTS_PER_SEARCH,
                hours_old=HOURS_OLD,
                country_indeed=pais,
                is_remote=remoto,
                linkedin_fetch_description=fetch_desc,
                verbose=0,
            )
            if df is not None and len(df):
                df["busqueda"], df["mercado"] = termino, mercado
                frames.append(df)
                brutas += len(df)
                print(f"   → {len(df)} ofertas")
        except Exception as e:
            print(f"   ⚠️ {type(e).__name__}: {e}")

    if not frames:
        print("Sin resultados.")
        return

    # dropna(axis=1, how='all') por frame evita el FutureWarning de pandas
    # al concatenar frames con columnas totalmente vacías
    frames = [f.dropna(axis=1, how="all") for f in frames]
    jobs = pd.concat(frames, ignore_index=True)
    jobs = jobs.drop_duplicates(subset=["job_url"], keep="first")
    jobs["_k"] = (jobs["title"].str.lower().str.strip() + "|" +
                  jobs["company"].fillna("").str.lower().str.strip())
    jobs = jobs.drop_duplicates(subset=["_k"], keep="first").drop(columns=["_k"])

    # Aplicar filtro RADAR
    evaluadas, descartadas = [], 0
    for _, row in jobs.iterrows():
        r = evaluar(row)
        if r is None:
            descartadas += 1
            continue
        d = row.to_dict()
        d["prioridad"], d["score"], d["etiquetas"], d["mercado_final"] = r
        evaluadas.append(d)

    res = pd.DataFrame(evaluadas)
    orden_p = {"P1": 0, "P2": 1, "P3": 2, "REVISAR": 3}
    res["_o"] = res["prioridad"].map(orden_p)
    res = res.sort_values(["_o", "score"], ascending=[True, False]).drop(columns=["_o"])

    # Guardar
    outdir = Path("resultados"); outdir.mkdir(exist_ok=True)
    hoy = date.today().isoformat()
    cols = [c for c in ["prioridad", "score", "etiquetas", "title", "company",
                        "location", "mercado_final", "is_remote", "date_posted",
                        "site", "busqueda", "min_amount", "max_amount", "currency",
                        "job_url", "description"] if c in res.columns]
    csv_path = outdir / f"radar_{hoy}.csv"
    res[cols].to_csv(csv_path, index=False)

    # Resumen MD
    md = [f"# RADAR · Barrido JobSpy — {hoy}",
          f"\n**{brutas} brutas → {len(jobs)} únicas → {descartadas} descartadas por filtro "
          f"(exclusiones 3.2 / onsite sin RELOCATE / onsite USA) → {len(res)} en Inbox**\n"]
    for p, titulo_seccion in [("P1", "🔴 P1 — Rol admitido · Barcelona/España"),
                              ("P2", "🟠 P2 — Rol admitido · UE/UK remoto o RELOCATE"),
                              ("P3", "🟡 P3 — Rol admitido · resto de mercados")]:
        sub = res[res["prioridad"] == p]
        md.append(f"\n## {titulo_seccion} ({len(sub)})\n")
        if len(sub):
            md.append("| Score | Título | Empresa | Ubicación | Etiq. | Fuente | Link |")
            md.append("|---|---|---|---|---|---|---|")
            for _, r in sub.head(25).iterrows():
                t = re.sub(r"\|", "-", str(r["title"]))[:55]
                c = re.sub(r"\|", "-", str(r.get("company") or "—"))[:28]
                l = str(r.get("location") or "—")[:28]
                e = r.get("etiquetas") or ""
                md.append(f"| {r['score']} | {t} | {c} | {l} | {e} | {r['site']} | [ver]({r['job_url']}) |")
    n_rev = len(res[res["prioridad"] == "REVISAR"])
    md.append(f"\n---\n*{n_rev} ofertas adicionales en estado REVISAR (no matchean los 33 "
              f"títulos pero no están excluidas) — solo en el CSV.*")
    md_path = outdir / f"radar_{hoy}.md"
    md_path.write_text("\n".join(md))

    print(f"\n✅ Inbox: {len(res)} ofertas ({descartadas} descartadas por filtro RADAR)")
    for p in ["P1", "P2", "P3", "REVISAR"]:
        print(f"   {p}: {len(res[res['prioridad']==p])}")
    print(f"   📄 {csv_path}\n   📄 {md_path}")


if __name__ == "__main__":
    main()
