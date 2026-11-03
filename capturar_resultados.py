#!/usr/bin/env python3
"""
capturar_resultados.py — versión 2 (3-nov-2026)
================================================

Captura automática de resultados de chance y loterías para Laboratorio de
Chance, leyendo el sitio NUEVO de GanaGana (el que estrenó hacia el
22-oct-2026, hecho en WordPress). Las direcciones viejas
/index.php/resultados/... ya no existen (dan "Page Not Found").

Fuentes (verificadas contra el sitio real el 3-nov-2026):
  - /resultados-sorteos-diarios/   último resultado de cada chance diario (29)
  - /resultados-loterias/          último sorteo de cada lotería semanal (14)
  - /sorteos-especiales/           sorteos extraordinarios (21)
  - /resultados-super-astro/       Astro Sol y Astro Luna, con ~1 año de
                                   histórico en la misma página
  - /detalles-loterias/?lottery_id=N
        histórico de un año de cada juego (atributo data-items, un JSON).
        Los números vienen enmascarados: "*****566" (Pick 3),
        "****5614" (4 cifras) y "***42422" (4 cifras + cifra adicional,
        que el sitio muestra como 4242-2).

Cómo funciona:
  1. Lee las 4 páginas de resultados.
  2. Para cada juego compara la fecha que muestra el sitio con la última
     que ya se capturó (captura_estado.json).
       - Si solo falta ese sorteo, lo toma de la tabla.
       - Si faltan más días que la cadencia del juego (1 día para los
         diarios, 7 para las loterías), recupera los sorteos intermedios
         desde el histórico del juego. Así, si la captura estuvo caída
         varios días, se pone al día sola en la siguiente corrida.
       - Si el histórico no carga, guarda lo que muestra la tabla pero
         no da el juego por completo: la próxima corrida lo vuelve a
         intentar.
  3. Convierte cada nombre al nombre que usa la app (MAPA_NOMBRES). Si
     aparece un juego que no está en el mapa, se guarda con el nombre del
     sitio (la app lo manda a la bandeja de cuarentena) y se avisa.
  4. Normaliza el número: 3 cifras (Pick 3) -> se rellena con un cero;
     4 cifras + cifra adicional -> se toman las 4 primeras.
  5. Escribe:
       captura_acumulada.json   todo lo capturado alguna vez
       captura_automatica.js    lo mismo, en el formato que lee index.html
       capturas/AAAA-MM-DD_captura.csv   lo nuevo de cada día
       captura_estado.json      última fecha capturada por juego
  6. Si una fuente falla (sitio caído, página que ya no existe, cambio de
     diseño), lo reporta EL MISMO DÍA: anotación de error en GitHub,
     salida "errores" para el workflow y resumen en la página de la
     corrida. Lo que sí se pudo leer se guarda igual.

Fuera de alcance: Baloto y MiLoto (siguen a mano) y Suertudo (excluido
siempre, regla del proyecto).

Uso:
    pip install requests beautifulsoup4        (una sola vez)
    python capturar_resultados.py
    python capturar_resultados.py --historial  (además guarda el histórico
        de un año de cada juego en historial_ganagana.json; la app no lo
        lee, es solo para revisar o completar la base)
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Faltan librerías. Instala con:\n    pip install requests beautifulsoup4")
    sys.exit(1)


# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

BASE = "https://www.ganagana.com.co"
URL_DIARIOS = BASE + "/resultados-sorteos-diarios/"
URL_LOTERIAS = BASE + "/resultados-loterias/"
URL_ESPECIALES = BASE + "/sorteos-especiales/"
URL_ASTRO = BASE + "/resultados-super-astro/"
URL_HISTORICO = BASE + "/detalles-loterias/?lottery_id={id}"

# (clave, título, url, tipo de página, cadencia en días)
# cadencia = cada cuántos días hay sorteo como mínimo. Si entre lo último
# capturado y lo que muestra el sitio hay más días que esto, se recuperan
# los intermedios desde el histórico. None = no se recupera (especiales:
# no tienen calendario fijo; Astro: su página ya trae el histórico).
FUENTES = [
    ("diarios", "Sorteos diarios", URL_DIARIOS, "tabla", 1),
    ("loterias", "Loterías", URL_LOTERIAS, "tabla", 7),
    ("especiales", "Sorteos especiales", URL_ESPECIALES, "tabla", None),
    ("astro", "Astro Sol y Luna", URL_ASTRO, "astro", None),
]

CARPETA = Path(__file__).resolve().parent
ARCHIVO_ESTADO = CARPETA / "captura_estado.json"
ARCHIVO_ACUMULADO = CARPETA / "captura_acumulada.json"
ARCHIVO_JS = CARPETA / "captura_automatica.js"
ARCHIVO_HISTORIAL = CARPETA / "historial_ganagana.json"
CARPETA_CAPTURAS = CARPETA / "capturas"

# Colombia no tiene horario de verano: UTC-5 todo el año.
ZONA_COLOMBIA = timezone(timedelta(hours=-5), "COT")

# Juego que aparece por primera vez (o repositorio sin estado): se
# recuperan estos días hacia atrás. Lo más viejo no se toca, para no
# meter sorteos especiales de hace meses como si fueran nuevos.
DIAS_INICIALES = 14

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "es-CO,es;q=0.9",
}
TIMEOUT_SEGUNDOS = 30
ESPERA_ENTRE_PETICIONES = 1.0
REINTENTOS = 3

# Nunca se guardan (regla del proyecto).
EXCLUIDOS = {"suertudo"}

MESES = {
    "ene": 1, "jan": 1, "feb": 2, "mar": 3, "abr": 4, "apr": 4, "may": 5,
    "jun": 6, "jul": 7, "ago": 8, "aug": 8, "sep": 9, "sept": 9, "set": 9,
    "oct": 10, "nov": 11, "dic": 12, "dec": 12,
}


# --------------------------------------------------------------------------
# Nombres: sitio -> app
#
# Las claves van sin tildes y en minúsculas (ver clave_nombre), así que
# "La Fantástica 1" y "La Fantastica 1" caen en la misma entrada. Los
# valores son los nombres exactos que ya usaba la captura y que la app
# reconoce. Incluye los nombres del sitio viejo para poder convertir el
# captura_estado.json anterior.
# --------------------------------------------------------------------------

MAPA_NOMBRES = {
    # --- Sorteos diarios ---
    "pick 3 dia": "Pick 3 Día",
    "pick 3 noche": "Pick 3 Noche",
    "pick 4 dia": "Pick 4 Día",
    "pick 4 noche": "Pick 4 Noche",
    "la antioquenita 1": "La Antioqueñita 1",
    "antioquenita 1": "La Antioqueñita 1",
    "antioquenita": "La Antioqueñita 1",
    "la antioquenita 2": "La Antioqueñita 2",
    "antioquenita 2": "La Antioqueñita 2",
    "cafeterito dia": "Cafeterito Día",
    "cafeterito noche": "Cafeterito Noche",
    "el motilon 1": "El Motilon 1",
    "motilon 1": "El Motilon 1",
    "el motilon 2": "El Motilon 2",
    "motilon 2": "El Motilon 2",
    "la fantastica 1": "La Fantastica 1",
    "la fantastica 2": "La Fantastica 2",
    "la culona dia": "La Culona Día",
    "la culona noche": "La Culona Noche",
    "chontico millonario": "Chontico Millonario",
    "chontico noche": "Chontico Noche",
    "super chontico millonario noche": "Super Chontico Noche Millonario",
    "super chontico noche millonario": "Super Chontico Noche Millonario",
    "paisita 1": "Paisita 1",
    "paisita 2": "Paisita 2",
    "paisita 3": "Paisita 3",
    "la caribena 1": "La Caribeña 1",
    "la caribena 2": "La Caribeña 2",
    "sinuano dia": "Sinuano Día",
    "sinuano noche": "Sinuano Noche",
    "el pijao de oro": "El Pijao de Oro",
    "el saman de la suerte": "El saman de la suerte",
    "el saman": "El saman de la suerte",
    "dorado manana": "Dorado Mañana",
    "dorado tarde": "Dorado Tarde",
    "dorado noche": "Dorado Noche",
    # --- Astro ---
    "astro sol": "Astro Sol",
    "super astro sol": "Astro Sol",
    "astro luna": "Astro Luna",
    "super astro luna": "Astro Luna",
    # --- Loterías semanales ---
    "loteria del cauca": "Cauca",
    "loteria de boyaca": "Boyacá",
    "loteria de santander": "Santander",
    "loteria de risaralda": "Risaralda",
    "loteria del risaralda": "Risaralda",
    "loteria de medellin": "Lotería de Medellín",
    "loteria del quindio": "Quindío",
    "loteria de bogota": "Bogotá",
    "loteria de manizales": "Manizales",
    "loteria manizales": "Manizales",
    "loteria del valle": "Valle",
    "loteria del meta": "Meta",
    "loteria de la cruz roja": "Cruz Roja",
    "loteria cruz roja": "Cruz Roja",
    "loteria del huila": "Huila",
    "loteria del tolima": "Tolima",
    "loteria de cundinamarca": "Cundinamarca",
    "loteria del cundinamarca": "Cundinamarca",
    # --- Sorteos especiales (mismo sorteo, nombre que ya usaba la captura) ---
    "sorteo extra de colombia": "Extra de Colombia",
    "loteria extra de colombia": "Extra de Colombia",
    "sorteo extra de colombia quindio": "Extra de Colombia - Quindio",
    "extra de colombia - quindio": "Extra de Colombia - Quindio",
    "sorteo extra de colombia atlantico": "Extra de Colombia Atlántico",
    "sorteo extra de colombia cucuta": "Extra de Colombia Cúcuta",
    "sorteo extra loteria del cauca": "Extra Super Millonario",
    "extra super millonario": "Extra Super Millonario",
    "sorteo extraordinario tolima": "Extra Pijao de la Lotería del Tolima",
    "extra pijao de la loteria del tolima": "Extra Pijao de la Lotería del Tolima",
    "sorteo extraordinario de navidad": "Sorteo Extraordinario de Navidad",
    "super extra navideno de medellin": "Extra Medellin",
    "extra medellin": "Extra Medellin",
    "extra banderita navideno": "Extra Banderita Navideño",
}


NOMBRES_CONOCIDOS = set(MAPA_NOMBRES.values())


def quitar_tildes(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()


def limpiar_nombre(texto):
    return re.sub(r"\s+", " ", (texto or "")).strip()


def clave_nombre(texto):
    return quitar_tildes(limpiar_nombre(texto)).lower()


def nombre_app(nombre_sitio):
    """Devuelve (nombre para la app, True si estaba en el mapa)."""
    clave = clave_nombre(nombre_sitio)
    if clave in MAPA_NOMBRES:
        return MAPA_NOMBRES[clave], True
    return limpiar_nombre(nombre_sitio), False


def es_excluido(nombre):
    clave = clave_nombre(nombre)
    return any(x in clave for x in EXCLUIDOS)


def es_pick3(nombre):
    return clave_nombre(nombre).startswith("pick 3")


# --------------------------------------------------------------------------
# Fechas y números
# --------------------------------------------------------------------------

def leer_fecha(texto):
    """'02 Nov 2026', '2 ago. 2026', '2026-11-02' o '02/11/2026' -> '2026-11-02'.
    Devuelve None si no es una fecha válida."""
    t = limpiar_nombre(texto).lower().replace(".", "")
    try:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", t)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        m = re.fullmatch(r"(\d{1,2})(?: de)? ([a-záéíóú]+)(?: de)? (\d{4})", t)
        if m:
            mes = MESES.get(quitar_tildes(m[2])[:4]) or MESES.get(quitar_tildes(m[2])[:3])
            if mes:
                return date(int(m[3]), mes, int(m[1])).isoformat()
    except ValueError:
        return None
    return None


def leer_numero(crudo, nombre):
    """Número del sitio -> 4 cifras para la app.
       '566' / '*****566'  (Pick 3)                  -> '0566'
       '5614' / '****5614'                           -> '5614'
       '4242-2' / '***42422' (4 cifras + adicional)   -> '4242'
    Devuelve (número, None) o (None, motivo)."""
    s = re.sub(r"\s+", "", crudo or "").lstrip("*")
    m = re.fullmatch(r"(\d{3,5})(?:-(\d))?", s)
    if not m:
        return None, f"número con formato no reconocido: {crudo!r}"
    cifras = m[1]
    if es_pick3(nombre):
        if len(cifras) == 3:
            return cifras.zfill(4), None
        if len(cifras) == 4 and cifras[0] == "0" and not m[2]:
            return cifras, None
        return None, f"Pick 3 con {len(cifras)} cifras: {crudo!r}"
    if len(cifras) == 3:
        return None, f"solo 3 cifras en un juego de 4: {crudo!r}"
    if len(cifras) == 5:
        if m[2]:
            return None, f"número con formato no reconocido: {crudo!r}"
        return cifras[:4], None
    return cifras, None


def dias_entre(desde, hasta):
    return (date.fromisoformat(hasta) - date.fromisoformat(desde)).days


# --------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------

class ErrorFuente(Exception):
    pass


_sesion = None


def obtener_html(url):
    """Descarga una página. Reintenta caídas pasajeras; una página que ya no
    existe (404) falla de una vez."""
    global _sesion
    if _sesion is None:
        _sesion = requests.Session()
        _sesion.headers.update(HEADERS)
    ultimo = None
    for intento in range(1, REINTENTOS + 1):
        try:
            resp = _sesion.get(url, timeout=TIMEOUT_SEGUNDOS)
            if resp.status_code in (404, 410):
                raise ErrorFuente(f"la página ya no existe ({resp.status_code}): {url}")
            resp.raise_for_status()
            resp.encoding = resp.encoding or "utf-8"
            if resp.encoding.lower() in ("iso-8859-1", "latin-1"):
                resp.encoding = "utf-8"
            return resp.text
        except ErrorFuente:
            raise
        except requests.RequestException as e:
            ultimo = e
            if intento < REINTENTOS:
                time.sleep(3 * intento)
    raise ErrorFuente(f"no se pudo descargar {url}: {ultimo}")


def pausa():
    if ESPERA_ENTRE_PETICIONES:
        time.sleep(ESPERA_ENTRE_PETICIONES)


# --------------------------------------------------------------------------
# Lectura de las páginas
# --------------------------------------------------------------------------

def leer_tabla(html_texto):
    """Tablas de sorteos diarios, loterías y especiales.
    Devuelve (filas, malas). Cada fila: nombre_sitio, lottery_id, crudo, fecha."""
    soup = BeautifulSoup(html_texto, "html.parser")
    trs = soup.select("tr.gg-loteria-tabla__fila")
    filas, malas = [], []
    for tr in trs:
        img = tr.find("img")
        span = tr.select_one(".gg-loteria-tabla__nombre-sorteo")
        nombre = limpiar_nombre(
            (img.get("alt") if img else "") or (span.get_text() if span else "") or tr.get("data-nombre", "")
        )
        ref = tr.get("data-href", "")
        if "lottery_id" not in ref:
            a = tr.find("a", href=re.compile(r"lottery_id="))
            ref = a.get("href", "") if a else ""
        m = re.search(r"lottery_id=(\d+)", ref)
        lottery_id = m[1] if m else None
        chip = tr.select_one(".gg-loteria-tabla__chip--numero")
        crudo = chip.get_text(strip=True) if chip else ""
        fecha = None
        for td in tr.find_all("td", recursive=False):
            if td.select_one(".gg-loteria-tabla__chip"):
                continue
            fecha = leer_fecha(td.get_text(" ", strip=True))
            if fecha:
                break
        if not nombre or not crudo or not fecha:
            malas.append(f"{nombre or '(sin nombre)'}: número {crudo!r}, fecha {fecha!r}")
            continue
        filas.append({"nombre_sitio": nombre, "lottery_id": lottery_id, "crudo": crudo, "fecha": fecha})
    return filas, malas


def leer_astro(html_texto):
    """Página de Astro: un panel por juego (Sol y Luna) con la tarjeta del
    último sorteo y el histórico de un año. Devuelve
    ({nombre_sitio: {fecha: crudo}}, malas)."""
    soup = BeautifulSoup(html_texto, "html.parser")
    nombres = {}
    for btn in soup.select(".gg-loteria-astros__btn"):
        destino = btn.get("data-target") or btn.get("aria-controls")
        img = btn.find("img")
        nombre = limpiar_nombre((img.get("alt") if img else "") or btn.get("aria-label", "") or btn.get_text())
        if destino and nombre:
            nombres[destino] = nombre
    juegos, malas = {}, []
    for panel in soup.select(".gg-loteria-astros__panel"):
        nombre = nombres.get(panel.get("id"))
        if not nombre:
            malas.append(f"panel {panel.get('id')!r} sin nombre de juego")
            continue
        por_fecha = juegos.setdefault(nombre, {})
        for card in panel.select(".gg-loteria-astros__resultado-card"):
            p = card.select_one(".gg-loteria-astros__fecha")
            fecha = leer_fecha(p.get_text()) if p else None
            crudo = "".join(d.get_text(strip=True) for d in card.select(".gg-loteria-astros__esfera-digito"))
            if not fecha or not crudo:
                malas.append(f"{nombre}: tarjeta sin fecha o sin número")
                continue
            if fecha in por_fecha and por_fecha[fecha] != crudo:
                malas.append(f"{nombre} {fecha}: dos números distintos en la página ({por_fecha[fecha]} y {crudo})")
                continue
            por_fecha[fecha] = crudo
    return juegos, malas


def leer_historico(html_texto):
    """Página /detalles-loterias/: lista de {fecha, crudo} del premio mayor."""
    soup = BeautifulSoup(html_texto, "html.parser")
    el = soup.find(attrs={"data-items": True})
    if el is None:
        raise ErrorFuente("la página del histórico no trae datos (data-items)")
    try:
        items = json.loads(el["data-items"])
    except (json.JSONDecodeError, TypeError) as e:
        raise ErrorFuente(f"el histórico no se pudo leer: {e}")
    salida = []
    for it in items:
        if not isinstance(it, dict) or it.get("is_major_prize") is False:
            continue
        fecha = leer_fecha(str(it.get("result_date", "")))
        crudo = str(it.get("number", ""))
        if fecha and crudo:
            salida.append({"fecha": fecha, "crudo": crudo, "nombre_sitio": it.get("lottery_name", "")})
    return salida


# --------------------------------------------------------------------------
# Archivos
# --------------------------------------------------------------------------

def leer_json(ruta, defecto):
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"Aviso: {ruta.name} está dañado; se empieza de cero.")
    return defecto


def cargar_estado():
    """Formato 2: {"formato": 2, "ultima": {nombre_app: fecha}}.
    Convierte el formato viejo ({"fuente:nombre_sitio": fecha})."""
    crudo = leer_json(ARCHIVO_ESTADO, {})
    if isinstance(crudo, dict) and crudo.get("formato") == 2:
        return dict(crudo.get("ultima", {})), False
    ultima = {}
    for k, v in (crudo or {}).items():
        if not isinstance(v, str) or not leer_fecha(v):
            continue
        nombre = k.split(":", 1)[1] if ":" in k else k
        app, _ = nombre_app(nombre)
        if v > ultima.get(app, ""):
            ultima[app] = v
    return ultima, bool(crudo)


def guardar_estado(ultima):
    datos = {
        "formato": 2,
        "nota": "Última fecha capturada por juego (nombres de la app). Lo escribe capturar_resultados.py.",
        "ultima": dict(sorted(ultima.items())),
    }
    ARCHIVO_ESTADO.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def escribir_js(acumulado, generado):
    lineas = ["fecha,loteria,numero"] + [f"{f['fecha']},{f['loteria']},{f['numero']}" for f in acumulado]
    cuerpo = "\n".join(lineas).replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    ARCHIVO_JS.write_text(
        "// Generado automáticamente por capturar_resultados.py — no editar a mano.\n"
        f"// Última corrida: {generado}\n"
        f"window.CAPTURA_AUTOMATICA_CHANCE = `{cuerpo}`;\n",
        encoding="utf-8",
    )


def escribir_csv_del_dia(nuevos, hoy):
    CARPETA_CAPTURAS.mkdir(exist_ok=True)
    ruta = CARPETA_CAPTURAS / f"{hoy}_captura.csv"
    previas = []
    if ruta.exists():
        with open(ruta, encoding="utf-8-sig", newline="") as f:
            previas = [r for r in csv.DictReader(f)]
    vistas = {(r["fecha"], r["loteria"], r["numero"]) for r in previas}
    filas = previas + [r for r in nuevos if (r["fecha"], r["loteria"], r["numero"]) not in vistas]
    filas.sort(key=lambda r: (r["fecha"], r["loteria"]))
    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "loteria", "numero"])
        for r in filas:
            w.writerow([r["fecha"], r["loteria"], r["numero"]])
    return ruta


# --------------------------------------------------------------------------
# Captura
# --------------------------------------------------------------------------

class Captura:
    def __init__(self, hoy, ultima, acumulado):
        self.hoy = hoy
        self.ultima = ultima
        self.acumulado = acumulado
        self.por_clave = {(f["fecha"], f["loteria"]): f["numero"] for f in acumulado}
        self.nuevos = []
        self.errores = []       # (dónde, mensaje): fallas de fuente -> corrida en rojo
        self.avisos = []        # cosas para revisar que no detienen la captura
        self.resumen = []       # (fuente, filas leídas, nuevos, estado)
        self.recuperados = {}   # juego -> cuántos salieron del histórico
        self.nombres_nuevos = set()
        self.excluidas = 0

    # -- utilidades --
    def piso(self, lot):
        return self.ultima.get(lot) or (date.fromisoformat(self.hoy) - timedelta(days=DIAS_INICIALES)).isoformat()

    def avanzar(self, lot, fecha):
        if fecha > self.ultima.get(lot, ""):
            self.ultima[lot] = fecha

    def agregar(self, fecha, lot, numero):
        """True si la fila queda en la captura (nueva o idéntica a una ya
        guardada); False si es de una fecha futura o choca con otra."""
        if fecha > self.hoy:
            self.avisos.append(f"{lot} {fecha}: fecha posterior a hoy ({self.hoy}); se ignoró.")
            return False
        previo = self.por_clave.get((fecha, lot))
        if previo is not None:
            if previo != numero:
                self.avisos.append(
                    f"{lot} {fecha}: el sitio muestra {numero} pero ya estaba capturado {previo}; se dejó el guardado. Revísalo."
                )
                return False
            return True
        fila = {"fecha": fecha, "loteria": lot, "numero": numero}
        if lot not in NOMBRES_CONOCIDOS:
            self.nombres_nuevos.add(lot)
        self.acumulado.append(fila)
        self.nuevos.append(fila)
        self.por_clave[(fecha, lot)] = numero
        return True

    # -- fuentes --
    def procesar_tabla(self, clave, titulo, html_texto, cadencia):
        filas, malas = leer_tabla(html_texto)
        if not filas:
            raise ErrorFuente("no se encontró ningún resultado en la página; puede que el sitio haya cambiado de diseño")
        for m in malas:
            self.avisos.append(f"{titulo}: fila sin leer ({m})")
        if len(malas) > len(filas):
            raise ErrorFuente(f"{len(malas)} de {len(filas) + len(malas)} filas no se pudieron leer; puede que el sitio haya cambiado de diseño")
        antes = len(self.nuevos)
        for fila in filas:
            if es_excluido(fila["nombre_sitio"]):
                self.excluidas += 1
                continue
            lot, _ = nombre_app(fila["nombre_sitio"])
            numero, motivo = leer_numero(fila["crudo"], lot)
            if motivo:
                self.avisos.append(f"{lot} {fila['fecha']}: {motivo}; no se capturó.")
                continue
            piso = self.piso(lot)
            if fila["fecha"] <= piso:
                continue
            if cadencia is not None and dias_entre(piso, fila["fecha"]) > cadencia:
                if fila["lottery_id"]:
                    self.recuperar(lot, fila, numero, piso)
                    continue
                self.avisos.append(f"{lot}: faltan días desde {piso} pero la fila no trae enlace al histórico; solo se tomó el {fila['fecha']}.")
            if self.agregar(fila["fecha"], lot, numero):
                self.avanzar(lot, fila["fecha"])
        self.resumen.append((titulo, len(filas), len(self.nuevos) - antes, "bien"))

    def recuperar(self, lot, fila, numero_tabla, piso):
        """Faltan sorteos entre lo último capturado y lo que muestra el sitio:
        se completan desde el histórico del juego."""
        pausa()
        try:
            historico = leer_historico(obtener_html(URL_HISTORICO.format(id=fila["lottery_id"])))
        except ErrorFuente as e:
            self.errores.append((f"Histórico de {lot}", str(e)))
            # Se guarda lo que muestra la tabla, pero el juego no se da por
            # completo: la próxima corrida vuelve a buscar los días que faltan.
            self.agregar(fila["fecha"], lot, numero_tabla)
            return
        por_fecha = {}
        for h in historico:
            if piso < h["fecha"] <= self.hoy:
                numero, motivo = leer_numero(h["crudo"], lot)
                if motivo:
                    self.avisos.append(f"{lot} {h['fecha']} (histórico): {motivo}; no se capturó.")
                    continue
                por_fecha[h["fecha"]] = numero
        if fila["fecha"] in por_fecha and por_fecha[fila["fecha"]] != numero_tabla:
            self.avisos.append(
                f"{lot} {fila['fecha']}: la tabla dice {numero_tabla} y el histórico {por_fecha[fila['fecha']]}; se tomó el de la tabla."
            )
        por_fecha[fila["fecha"]] = numero_tabla
        agregados = 0
        for fecha in sorted(por_fecha):
            antes = len(self.nuevos)
            if self.agregar(fecha, lot, por_fecha[fecha]):
                self.avanzar(lot, fecha)
            agregados += len(self.nuevos) - antes
        if agregados > 1:
            self.recuperados[lot] = agregados - 1

    def procesar_astro(self, titulo, html_texto):
        juegos, malas = leer_astro(html_texto)
        if not any(juegos.values()):
            raise ErrorFuente("no se encontró ningún resultado de Astro en la página; puede que el sitio haya cambiado de diseño")
        for m in malas:
            self.avisos.append(f"{titulo}: {m}")
        antes = len(self.nuevos)
        leidas = 0
        for nombre_sitio, por_fecha in juegos.items():
            lot, _ = nombre_app(nombre_sitio)
            piso = self.piso(lot)
            for fecha in sorted(por_fecha):
                leidas += 1
                if not (piso < fecha):
                    continue
                numero, motivo = leer_numero(por_fecha[fecha], lot)
                if motivo:
                    self.avisos.append(f"{lot} {fecha}: {motivo}; no se capturó.")
                    continue
                if self.agregar(fecha, lot, numero):
                    self.avanzar(lot, fecha)
        self.resumen.append((titulo, leidas, len(self.nuevos) - antes, "bien"))

    def correr(self):
        for i, (clave, titulo, url, tipo, cadencia) in enumerate(FUENTES):
            if i:
                pausa()
            print(f"Leyendo {titulo}: {url}")
            try:
                html_texto = obtener_html(url)
                if tipo == "astro":
                    self.procesar_astro(titulo, html_texto)
                else:
                    self.procesar_tabla(clave, titulo, html_texto, cadencia)
            except ErrorFuente as e:
                self.errores.append((titulo, str(e)))
                self.resumen.append((titulo, 0, 0, "FALLÓ"))


def capturar_historial(hoy, generado):
    """--historial: un año de resultados de cada juego, en historial_ganagana.json."""
    juegos, avisos = {}, []
    ids = {}
    for clave, titulo, url, tipo, _ in FUENTES:
        pausa()
        try:
            html_texto = obtener_html(url)
        except ErrorFuente as e:
            avisos.append(f"Histórico: {titulo}: {e}")
            continue
        if tipo == "astro":
            por_juego, _ = leer_astro(html_texto)
            for nombre_sitio, por_fecha in por_juego.items():
                lot, _ = nombre_app(nombre_sitio)
                res = []
                for f, c in sorted(por_fecha.items()):
                    n, _ = leer_numero(c, lot)
                    if n and f <= hoy:
                        res.append([f, n])
                juegos[lot] = {"nombre_sitio": nombre_sitio, "lottery_id": None, "resultados": res}
        else:
            filas, _ = leer_tabla(html_texto)
            for fila in filas:
                if fila["lottery_id"] and not es_excluido(fila["nombre_sitio"]):
                    ids[fila["lottery_id"]] = fila["nombre_sitio"]
    for lottery_id, nombre_sitio in sorted(ids.items(), key=lambda x: int(x[0])):
        pausa()
        lot, _ = nombre_app(nombre_sitio)
        try:
            items = leer_historico(obtener_html(URL_HISTORICO.format(id=lottery_id)))
        except ErrorFuente as e:
            avisos.append(f"Histórico de {lot}: {e}")
            continue
        res = {}
        for it in items:
            n, _ = leer_numero(it["crudo"], lot)
            if n and it["fecha"] <= hoy:
                res[it["fecha"]] = n
        juegos[lot] = {"nombre_sitio": nombre_sitio, "lottery_id": lottery_id, "resultados": sorted(map(list, res.items()))}
    datos = {"generado": generado, "fuente": BASE, "juegos": dict(sorted(juegos.items()))}
    ARCHIVO_HISTORIAL.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    total = sum(len(j["resultados"]) for j in juegos.values())
    return len(juegos), total, avisos


# --------------------------------------------------------------------------
# Reporte (pantalla, anotaciones y resumen de GitHub Actions)
# --------------------------------------------------------------------------

EN_ACTIONS = os.environ.get("GITHUB_ACTIONS") == "true"


def anotar(nivel, titulo, mensaje):
    mensaje = mensaje.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    if EN_ACTIONS:
        print(f"::{nivel} title={titulo}::{mensaje}")
    else:
        print(f"{'ERROR' if nivel == 'error' else 'AVISO'} · {titulo}: {mensaje}")


def escribir_salidas(**valores):
    ruta = os.environ.get("GITHUB_OUTPUT")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            for k, v in valores.items():
                f.write(f"{k}={v}\n")


def escribir_resumen(texto):
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def reportar(cap, ultima_captura, migrado, extra=None):
    print()
    print("Fuente                 Leídos  Nuevos  Estado")
    for titulo, leidas, nuevos, estado in cap.resumen:
        print(f"{titulo:22} {leidas:6}  {nuevos:6}  {estado}")
    print(f"\n{len(cap.nuevos)} resultado(s) nuevo(s). Último día capturado: {ultima_captura or '(ninguno)'}.")
    if migrado:
        print("captura_estado.json estaba en el formato viejo: se convirtió al formato 2.")
    if cap.recuperados:
        print("Recuperados desde el histórico (días que faltaban): " +
              ", ".join(f"{k} {v}" for k, v in sorted(cap.recuperados.items())))
    if cap.excluidas:
        print(f"Excluidas por regla (Suertudo): {cap.excluidas}")
    if cap.nuevos:
        print("\n--- BLOQUE LISTO PARA PEGAR EN IMPORTACIÓN MASIVA ---")
        print("fecha,loteria,numero")
        for f in sorted(cap.nuevos, key=lambda r: (r["fecha"], r["loteria"])):
            print(f"{f['fecha']},{f['loteria']},{f['numero']}")
        print("--- FIN DEL BLOQUE ---")
    print()
    for donde, msg in cap.errores:
        anotar("error", donde, msg)
    if cap.nombres_nuevos:
        anotar("warning", "Nombres nuevos",
               "El sitio trae juegos que no están en MAPA_NOMBRES; se guardaron con el nombre del sitio "
               "y la app los mandará a la cuarentena: " + "; ".join(sorted(cap.nombres_nuevos)))
    for a in cap.avisos:
        anotar("warning", "Revisar", a)
    for a in (extra or []):
        anotar("warning", "Historial", a)

    md = ["## Captura de resultados", ""]
    md.append(f"**{len(cap.nuevos)} resultado(s) nuevo(s)** · último día capturado: **{ultima_captura or '—'}**")
    md.append("")
    md.append("| Fuente | Leídos | Nuevos | Estado |")
    md.append("|---|---:|---:|---|")
    for titulo, leidas, nuevos, estado in cap.resumen:
        md.append(f"| {titulo} | {leidas} | {nuevos} | {'✅' if estado == 'bien' else '❌ falló'} |")
    if cap.recuperados:
        md += ["", "**Recuperados desde el histórico:** " + ", ".join(f"{k} ({v})" for k, v in sorted(cap.recuperados.items()))]
    if cap.errores:
        md += ["", "### ❌ Errores"] + [f"- **{d}:** {m}" for d, m in cap.errores]
    if cap.nombres_nuevos:
        md += ["", "### Nombres nuevos (van a la cuarentena de la app)"] + [f"- {n}" for n in sorted(cap.nombres_nuevos)]
    if cap.avisos:
        md += ["", "### Para revisar"] + [f"- {a}" for a in cap.avisos]
    escribir_resumen("\n".join(md))


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Captura automática de resultados de GanaGana (sitio nuevo).")
    ap.add_argument("--historial", action="store_true",
                    help="Además guarda el histórico de un año de cada juego en historial_ganagana.json.")
    args = ap.parse_args(argv)

    ahora = datetime.now(ZONA_COLOMBIA)
    hoy = os.environ.get("CAPTURA_HOY") or ahora.date().isoformat()  # CAPTURA_HOY: solo para pruebas
    generado = ahora.isoformat(timespec="seconds")

    ultima, migrado = cargar_estado()
    acumulado = leer_json(ARCHIVO_ACUMULADO, [])
    cap = Captura(hoy, ultima, acumulado)
    cap.correr()

    if cap.nuevos:
        cap.acumulado.sort(key=lambda f: (f["fecha"], f["loteria"]))
        ARCHIVO_ACUMULADO.write_text(json.dumps(cap.acumulado, ensure_ascii=False, indent=2), encoding="utf-8")
        escribir_js(cap.acumulado, generado)
        ruta_csv = escribir_csv_del_dia(cap.nuevos, hoy)
        print(f"Guardado: {ARCHIVO_ACUMULADO.name}, {ARCHIVO_JS.name} y {ruta_csv.relative_to(CARPETA)}")
    if cap.nuevos or migrado or not ARCHIVO_ESTADO.exists():
        guardar_estado(cap.ultima)

    extra = []
    if args.historial:
        print("\nGuardando el histórico de un año de cada juego...")
        n_juegos, n_res, extra = capturar_historial(hoy, generado)
        print(f"{ARCHIVO_HISTORIAL.name}: {n_juegos} juegos, {n_res} resultados.")

    fechas = [f["fecha"] for f in cap.acumulado]
    ultima_captura = max(fechas) if fechas else ""
    reportar(cap, ultima_captura, migrado, extra)
    escribir_salidas(errores=len(cap.errores), nuevos=len(cap.nuevos), ultima=ultima_captura)
    return 0


if __name__ == "__main__":
    sys.exit(main())
