#!/usr/bin/env python3
"""
capturar_resultados.py
=======================

Captura automática de resultados de chance y loterías departamentales para
Laboratorio de Chance, leyendo las páginas de TEXTO de GanaGana (no las
imágenes de tableros). No usa OCR: estas páginas publican los números como
texto plano en una tabla HTML, así que se leen directamente.

Fuentes (todas de texto, verificadas contra el sitio real el 2026-08-11):
  - https://www.ganagana.com.co/index.php/resultados/sorteos-diarios
      Último resultado de cada chance diario (La Antioqueñita, Dorado,
      Cafeterito, Chontico, Paisita, Pijao, Sinuano, La Fantástica,
      La Caribeña, El Motilón, La Culona, Pick 3, Pick 4...).
  - https://www.ganagana.com.co/index.php/resultados/astro-sol-y-luna
      Astro Sol / Astro Luna (se descarta la columna Signo).
  - https://www.ganagana.com.co/index.php/resultados/loterias
      Loterías departamentales (Cundinamarca, Tolima, Cruz Roja, Huila,
      Meta, Valle, Manizales, Bogotá, Quindío, Risaralda, Medellín,
      Santander, Boyacá, Cauca, Extra de Colombia...).

FUERA DE ALCANCE A PROPÓSITO: Baloto y MiLoto. En este sitio esos
resultados están publicados como una FOTO (no hay texto), igual que los
tableros históricos por día — así que siguen su flujo actual (imagen ->
Claude transcribe). Ver la nota al final de este archivo.

Cómo funciona:
  1. Descarga las 3 páginas de arriba.
  2. Extrae nombre / fecha / resultado de cada fila de sus tablas.
     El nombre puede venir como texto visible o, si la celda no tiene
     texto (pasa en un par de filas), del atributo alt/title de su imagen.
  3. Normaliza el número: los sorteos que traen 5 cifras usan una "cifra
     adicional" que se descarta (se toman las primeras 4); los de 3 cifras
     (Pick 3) se rellenan con cero a la izquierda; los de 4 se dejan igual.
  4. Aplica el mapa de nombres -> nombre canónico (ver MAPA_NOMBRES abajo;
     los que no están confirmados se dejan tal cual y se listan aparte).
  5. Como "sorteos diarios" es una FOTO del último resultado de cada juego
     (no una serie temporal), guarda un estado local (captura_estado.json)
     con la última fecha ya capturada por juego, para no repetir la misma
     fila en cada corrida. Solo se guarda lo nuevo.
  6. Escribe un CSV en formato fecha,loteria,numero listo para pegar en
     "Importación masiva", y lo imprime en pantalla.

Uso:
    pip install requests beautifulsoup4        (una sola vez)
    python capturar_resultados.py

    python capturar_resultados.py --dias-loterias 20   (ventana de
        antigüedad para loterías departamentales; por defecto 14 días,
        pensado para cubrir un ciclo semanal con margen)

    python capturar_resultados.py --ignorar-estado     (ignora el estado
        guardado y vuelve a traer todo lo que haya en las páginas ahora
        mismo; útil en la primera corrida o para revisar algo puntual)

Honestidad técnica: mi entorno no tiene acceso a ganagana.com.co (solo a
dominios técnicos), así que no pude ejecutar este script contra el sitio
en vivo. Sí verifiqué el contenido y la estructura de las 3 páginas reales
ahora mismo (vía una herramienta de búsqueda con acceso al sitio) y probé
esta lógica de extracción contra un HTML construido con esa estructura y
esos valores reales. La primera corrida de verdad la haces tú: si algo no
calza, copia lo que imprime en pantalla y lo ajusto.
"""

import argparse
import csv
import json
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
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

URL_SORTEOS_DIARIOS = "https://www.ganagana.com.co/index.php/resultados/sorteos-diarios"
URL_ASTRO = "https://www.ganagana.com.co/index.php/resultados/astro-sol-y-luna"
URL_LOTERIAS = "https://www.ganagana.com.co/index.php/resultados/loterias"

CARPETA_SCRIPT = Path(__file__).resolve().parent
ARCHIVO_ESTADO = CARPETA_SCRIPT / "captura_estado.json"
CARPETA_SALIDA = CARPETA_SCRIPT / "capturas"

# Para la autocarga en index.html: este script debe vivir en LA MISMA
# carpeta que index.html, porque el archivo de abajo se referencia con una
# ruta relativa (<script src="captura_automatica.js">) y el navegador lo
# busca junto al HTML, no junto a este .py.
ARCHIVO_ACUMULADO = CARPETA_SCRIPT / "captura_acumulada.json"
ARCHIVO_JS_AUTOCARGA = CARPETA_SCRIPT / "captura_automatica.js"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
TIMEOUT_SEGUNDOS = 20
ESPERA_ENTRE_PETICIONES = 1.5  # mismo criterio de cortesía que descargar_tableros.py

# Juegos que nunca se guardan, sin importar dónde aparezcan.
EXCLUIDOS = {"suertudo"}

# --------------------------------------------------------------------------
# Mapa de nombres: sitio -> canónico
#
# Solo contiene renombres RESPALDADOS por reglas ya confirmadas del
# proyecto. Todo lo demás se deja EXACTAMENTE como aparece en el sitio y
# se lista aparte al final ("NOMBRES SIN CONFIRMAR") para que se revise
# una sola vez contra MAPA_CANONICO / DATOS en el HTML. No adivino nombres:
# es más seguro capturar con el nombre del sitio y corregir después, que
# inventar un renombre y contaminar la base.
# --------------------------------------------------------------------------

MAPA_NOMBRES = {
    # === Confirmado por reglas explícitas del proyecto ===
    # -- Antioqueñita: la fila del sitio no siempre trae texto visible,
    #    así que estas claves llegan por el alt/title de la imagen --
    "Antioqueñita": "La Antioqueñita 1",
    "Antioqueñita 2": "La Antioqueñita 2",
    # -- Motilón: regla confirmada "Motilón -> El Motilon" (sin tilde) --
    "El Motilón 1": "El Motilon 1",
    "El Motilón 2": "El Motilon 2",
    "Motilón 1": "El Motilon 1",
    "Motilón 2": "El Motilon 2",
    # -- Samán: regla confirmada --
    "El Samán de la Suerte": "El saman de la suerte",
    # -- Astro: en transcripciones confirmadas se usa "Astro Sol" / "Astro
    #    Luna", sin "SUPER" y sin mayúsculas sostenidas --
    "SUPER ASTRO SOL": "Astro Sol",
    "SUPER ASTRO LUNA": "Astro Luna",

    # === Confirmado directamente contra tu DATOS embebido (sesión 2026-08-11) ===
    # -- El sitio a veces solo trae el alt "El Saman" (sin el resto del
    #    nombre); DATOS usa "El saman de la suerte" --
    "El Saman": "El saman de la suerte",
    # -- El sitio muestra "Cafeterito Dia" (sin tilde); DATOS ya tiene
    #    "Cafeterito Día" con tilde para este mismo sorteo --
    "Cafeterito Dia": "Cafeterito Día",
    # -- El sitio muestra "La Fantástica 1/2" con tilde; DATOS usa
    #    "La Fantastica 1/2" sin tilde (a diferencia de La Caribeña, que
    #    sí conserva la tilde) --
    "La Fantástica 1": "La Fantastica 1",
    "La Fantástica 2": "La Fantastica 2",
    # -- Capitalización/orden, sin cambiar el nombre en sí --
    "Super chontico Millonario Noche": "Super Chontico Noche Millonario",

    # === Loterías departamentales: nombres tal como los muestra GanaGana
    #     -> forma canónica usada en una limpieza de datos anterior de
    #     este proyecto (mapeo de un CSV oficial). Vale la pena una
    #     revisión visual rápida, pero no son adivinanzas mías. ===
    "Lotería del Cundinamarca": "Cundinamarca",
    "Lotería del Tolima": "Tolima",
    "Lotería Cruz Roja": "Cruz Roja",
    "Lotería del Huila": "Huila",
    "Lotería del Meta": "Meta",
    "Lotería del Valle": "Valle",
    "Lotería Manizales": "Manizales",
    "Lotería De Bogota": "Bogotá",
    "Lotería del Quindio": "Quindío",
    "Lotería del Risaralda": "Risaralda",
    "Lotería de Medellin": "Lotería de Medellín",
    "Lotería de Santander": "Santander",
    "Lotería de Boyaca": "Boyacá",
    "Lotería del Cauca": "Cauca",
    "Lotería extra de colombia": "Extra de Colombia",
}

# Nombres pendientes de confirmar contra tu DATOS. Se vació el 2026-08-11
# tras revisar el HTML real: Dorado Mañana/Tarde/Noche y La Caribeña 1/2
# ya coinciden tal cual con el sitio (sin necesidad de mapeo), y
# La Fantástica 1/2 y Cafeterito Día quedaron resueltos arriba en
# MAPA_NOMBRES. Queda vacío para que, si el sitio agrega un juego nuevo
# que no reconoce el mapa, aparezca aquí en vez de adivinarse.
NOMBRES_A_VERIFICAR = set()


def normalizar_clave(nombre):
    """minúsculas y sin tildes, para comparar contra EXCLUIDOS sin fallar
    por acentos."""
    sin_tildes = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return sin_tildes.strip().lower()


def nombre_final(nombre_sitio):
    """Aplica MAPA_NOMBRES si existe una entrada; si no, deja el nombre
    del sitio tal cual."""
    return MAPA_NOMBRES.get(nombre_sitio, nombre_sitio)


# --------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------

def obtener_html(url):
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT_SEGUNDOS)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


# --------------------------------------------------------------------------
# Parseo
# --------------------------------------------------------------------------

def extraer_nombre(celda):
    """Texto visible de la celda; si está vacía, usa alt/title de su
    imagen. Se descarta cualquier <a> anidado antes de leer el texto:
    la última fila de "sorteos diarios" trae un enlace suelto
    ("Historico Resultados") pegado al nombre del sorteo, y sin este
    paso quedaría concatenado al nombre."""
    for a in celda.find_all("a"):
        a.decompose()
    texto = celda.get_text(strip=True)
    if texto:
        return texto
    img = celda.find("img")
    if img:
        return (img.get("alt") or img.get("title") or "").strip()
    return ""


def parsear_tabla_simple(html, min_celdas=3):
    """Sirve para sorteos-diarios (3 columnas) y astro-sol-y-luna (4
    columnas, se ignora la 4ta = Signo). Devuelve (filas, error)."""
    soup = BeautifulSoup(html, "html.parser")
    tabla = soup.find("table")
    if not tabla:
        return [], "No se encontró ninguna tabla en la página."

    cuerpo = tabla.find("tbody") or tabla
    filas = []
    for tr in cuerpo.find_all("tr"):
        celdas = tr.find_all("td")
        if len(celdas) < min_celdas:
            continue
        nombre = extraer_nombre(celdas[0])
        fecha = celdas[1].get_text(strip=True)
        crudo = celdas[2].get_text(strip=True)
        if not nombre or not fecha or not crudo:
            continue
        filas.append({"nombre_sitio": nombre, "fecha": fecha, "crudo": crudo})
    return filas, None


def parsear_loterias(html):
    """5 columnas: Loteria, Fecha (DD/MM/AAAA), Número, Serie, Plan de
    Premios. Se ignoran Serie y Plan de Premios."""
    soup = BeautifulSoup(html, "html.parser")
    tabla = soup.find("table")
    if not tabla:
        return [], "No se encontró ninguna tabla en la página."

    cuerpo = tabla.find("tbody") or tabla
    filas = []
    errores_fecha = []
    for tr in cuerpo.find_all("tr"):
        celdas = tr.find_all("td")
        if len(celdas) < 3:
            continue
        nombre = extraer_nombre(celdas[0])
        fecha_ddmmaaaa = celdas[1].get_text(strip=True)
        crudo = celdas[2].get_text(strip=True)
        if not nombre or not fecha_ddmmaaaa or not crudo:
            continue
        try:
            d, m, a = fecha_ddmmaaaa.split("/")
            fecha_iso = f"{a}-{m.zfill(2)}-{d.zfill(2)}"
            datetime.strptime(fecha_iso, "%Y-%m-%d")  # valida que exista
        except (ValueError, AttributeError):
            errores_fecha.append(f"{nombre}: {fecha_ddmmaaaa!r}")
            continue
        filas.append({"nombre_sitio": nombre, "fecha": fecha_iso, "crudo": crudo})

    error = None
    if errores_fecha:
        error = "Fechas con formato inesperado (se omitieron): " + "; ".join(errores_fecha)
    return filas, error


def filtrar_recientes(filas, dias):
    """Para loterías departamentales: la tabla mezcla el sorteo semanal
    vigente con sorteos "Extra" especiales de hace meses/años. Se
    descarta todo lo más viejo que `dias`, así nunca se cuela un Extra
    viejo como si fuera nuevo."""
    limite = date.today() - timedelta(days=dias)
    resultado = []
    for f in filas:
        y, m, d = map(int, f["fecha"].split("-"))
        if date(y, m, d) >= limite:
            resultado.append(f)
    return resultado


# --------------------------------------------------------------------------
# Normalización del número
# --------------------------------------------------------------------------

def normalizar_numero(crudo):
    """'3 1 9 8 7' (5 cifras con espacios) -> '3198'
       '31987'     (5 cifras pegadas, sin espacios)     -> '3198'
       '5581' / '5 5 8 1'  (4 cifras)                    -> '5581'
       '764'  / '7 6 4'    (3 cifras, Pick 3)             -> '0764'
    El sitio no siempre separa las cifras con espacios (depende de cómo
    esté armada esa fila en particular) -- se colapsa cualquier espacio
    antes de contar, así que ambos formatos quedan cubiertos por igual.
    Devuelve (numero_normalizado o None, mensaje_de_error o None)."""
    cifras_texto = crudo.replace(" ", "")
    if not cifras_texto.isdigit():
        return None, f"contiene algo que no es un dígito: {crudo!r}"
    n = len(cifras_texto)
    if n == 5:
        return cifras_texto[:4], None
    if n == 4:
        return cifras_texto, None
    if n == 3:
        return cifras_texto.zfill(4), None
    return None, f"cantidad de cifras inesperada ({n}): {crudo!r}"


# --------------------------------------------------------------------------
# Estado (para no repetir capturas de un "último resultado" que no cambió)
# --------------------------------------------------------------------------

def cargar_estado():
    if ARCHIVO_ESTADO.exists():
        try:
            return json.loads(ARCHIVO_ESTADO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"Aviso: {ARCHIVO_ESTADO.name} está corrupto, se empieza de cero.")
    return {}


def guardar_estado(estado):
    ARCHIVO_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------
# Acumulado para autocarga (captura_automatica.js)
#
# index.html ya sabe leer captura_automatica.js al abrirse (si existe) y
# fusionar lo que traiga con el mismo parser y las mismas reglas de
# "Importación masiva" (duplicado exacto -> se ignora solo; mismo día y
# lotería con número distinto -> conflicto, nunca se sobreescribe solo).
# Por eso es seguro que este archivo acumule TODO lo capturado alguna vez,
# no solo lo de la corrida de hoy: si Juan no abre la app por varios días,
# la próxima vez que la abra igual se pone al día de una sola vez. Volver a
# mandar una fila que la app ya absorbió no hace nada (queda como
# "duplicado" del lado de la app), así que acumular sin límite es inofensivo.
# --------------------------------------------------------------------------

def cargar_acumulado():
    if ARCHIVO_ACUMULADO.exists():
        try:
            return json.loads(ARCHIVO_ACUMULADO.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"Aviso: {ARCHIVO_ACUMULADO.name} está corrupto, se empieza de cero.")
    return []


def guardar_acumulado(filas):
    ARCHIVO_ACUMULADO.write_text(json.dumps(filas, ensure_ascii=False, indent=2), encoding="utf-8")


def escapar_para_plantilla_js(s):
    """Para meter texto dentro de un template literal `...` de JS sin romperlo."""
    return s.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")


def escribir_js_autocarga(filas_acumuladas):
    """Escribe captura_automatica.js con el mismo formato fecha,loteria,numero
    que ya entiende parsearImportacion() en index.html."""
    lineas = ["fecha,loteria,numero"]
    for f in filas_acumuladas:
        lineas.append(f"{f['fecha']},{f['loteria']},{f['numero']}")
    cuerpo = escapar_para_plantilla_js("\n".join(lineas))
    generado = datetime.now().isoformat(timespec="seconds")
    contenido = (
        "// Generado automáticamente por capturar_resultados.py — no editar a mano.\n"
        f"// Última corrida: {generado}\n"
        f"window.CAPTURA_AUTOMATICA_CHANCE = `{cuerpo}`;\n"
    )
    ARCHIVO_JS_AUTOCARGA.write_text(contenido, encoding="utf-8")


# --------------------------------------------------------------------------
# Programa principal
# --------------------------------------------------------------------------

def procesar_fuente(nombre_fuente, filas_crudas, estado, ignorar_estado, filtro_recencia_dias=None):
    """Aplica exclusiones, normaliza número, filtra por estado (o por
    antigüedad si se pide) y arma las filas finales + diagnósticos."""
    finales = []
    omitidos_excluidos = []
    omitidos_numero = []
    omitidos_repetidos = []
    sin_confirmar_vistos = set()

    if filtro_recencia_dias is not None:
        filas_crudas = filtrar_recientes(filas_crudas, filtro_recencia_dias)

    for fila in filas_crudas:
        clave_exclusion = normalizar_clave(fila["nombre_sitio"])
        if clave_exclusion in EXCLUIDOS:
            omitidos_excluidos.append(fila["nombre_sitio"])
            continue

        numero, err = normalizar_numero(fila["crudo"])
        if err:
            omitidos_numero.append(f"{fila['nombre_sitio']} ({fila['fecha']}): {err}")
            continue

        clave_estado = f"{nombre_fuente}:{fila['nombre_sitio']}"
        ultima_fecha = estado.get(clave_estado)
        if not ignorar_estado and ultima_fecha and fila["fecha"] <= ultima_fecha:
            omitidos_repetidos.append(f"{fila['nombre_sitio']} ({fila['fecha']})")
            continue

        if fila["nombre_sitio"] in NOMBRES_A_VERIFICAR:
            sin_confirmar_vistos.add(fila["nombre_sitio"])

        finales.append({
            "fecha": fila["fecha"],
            "loteria": nombre_final(fila["nombre_sitio"]),
            "numero": numero,
            "clave_estado": clave_estado,
        })

    return finales, {
        "excluidos": omitidos_excluidos,
        "numero_invalido": omitidos_numero,
        "ya_capturados": omitidos_repetidos,
        "sin_confirmar": sin_confirmar_vistos,
    }


def main():
    ap = argparse.ArgumentParser(description="Captura automática de resultados GanaGana (texto, sin OCR).")
    ap.add_argument("--dias-loterias", type=int, default=14,
                     help="Ventana de antigüedad en días para loterías departamentales (default: 14).")
    ap.add_argument("--ignorar-estado", action="store_true",
                     help="Ignora captura_estado.json y vuelve a traer todo lo que haya ahora en las páginas.")
    args = ap.parse_args()

    CARPETA_SALIDA.mkdir(exist_ok=True)
    estado = cargar_estado()

    fuentes = [
        ("sorteos_diarios", URL_SORTEOS_DIARIOS, "simple", None),
        ("astro", URL_ASTRO, "simple", None),
        ("loterias", URL_LOTERIAS, "loterias", args.dias_loterias),
    ]

    todas_finales = []
    resumen_diagnostico = {"excluidos": [], "numero_invalido": [], "ya_capturados": [], "sin_confirmar": set()}
    fuentes_con_error = []

    for i, (nombre_fuente, url, tipo, filtro_dias) in enumerate(fuentes):
        print(f"Descargando {url} ...")
        try:
            html = obtener_html(url)
        except requests.RequestException as e:
            print(f"  ERROR al descargar: {e}")
            fuentes_con_error.append((nombre_fuente, str(e)))
            continue

        if tipo == "simple":
            filas, error_parseo = parsear_tabla_simple(html)
        else:
            filas, error_parseo = parsear_loterias(html)

        if error_parseo:
            print(f"  Aviso de parseo: {error_parseo}")
        print(f"  {len(filas)} filas encontradas en la tabla.")

        finales, diag = procesar_fuente(nombre_fuente, filas, estado, args.ignorar_estado, filtro_dias)
        todas_finales.extend(finales)
        for k in ("excluidos", "numero_invalido", "ya_capturados"):
            resumen_diagnostico[k].extend(diag[k])
        resumen_diagnostico["sin_confirmar"] |= diag["sin_confirmar"]

        if i < len(fuentes) - 1:
            time.sleep(ESPERA_ENTRE_PETICIONES)

    if not todas_finales:
        print("\nNo hay resultados nuevos para capturar (todo lo visible en las páginas ya estaba en el estado guardado).")
        if fuentes_con_error:
            print("Fuentes con error en esta corrida:", ", ".join(f[0] for f in fuentes_con_error))
        # Diagnóstico completo aunque no haya nada nuevo -- antes esto solo
        # se imprimía en la rama de éxito, así que un caso como "todo se
        # descartó por numero_invalido" quedaba mudo justo cuando más hacía
        # falta verlo.
        if resumen_diagnostico["numero_invalido"]:
            print(f"\n{len(resumen_diagnostico['numero_invalido'])} fila(s) con número no reconocido:")
            for msg in resumen_diagnostico["numero_invalido"][:20]:
                print(f"  - {msg}")
        if resumen_diagnostico["excluidos"]:
            print(f"\n{len(resumen_diagnostico['excluidos'])} fila(s) excluidas por regla (Suertudo, etc.).")
        if resumen_diagnostico["ya_capturados"]:
            print(f"\n{len(resumen_diagnostico['ya_capturados'])} fila(s) ya estaban en el estado guardado (normal en corridas posteriores a la primera).")
        return

    todas_finales.sort(key=lambda f: (f["fecha"], f["loteria"]))

    # Actualizar estado: para cada clave, la fecha más reciente vista en esta corrida
    for f in todas_finales:
        actual = estado.get(f["clave_estado"])
        if not actual or f["fecha"] > actual:
            estado[f["clave_estado"]] = f["fecha"]
    guardar_estado(estado)

    # Escribir CSV
    fecha_archivo = date.today().isoformat()
    ruta_csv = CARPETA_SALIDA / f"{fecha_archivo}_captura.csv"
    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["fecha", "loteria", "numero"])
        for fila in todas_finales:
            w.writerow([fila["fecha"], fila["loteria"], fila["numero"]])

    # Sumar al acumulado para autocarga y regenerar captura_automatica.js
    # (index.html lo lee solo, al abrirse, si vive en la misma carpeta)
    acumulado = cargar_acumulado()
    ya_en_acumulado = {(f["fecha"], f["loteria"], f["numero"]) for f in acumulado}
    agregados_al_acumulado = 0
    for fila in todas_finales:
        clave = (fila["fecha"], fila["loteria"], fila["numero"])
        if clave not in ya_en_acumulado:
            acumulado.append({"fecha": fila["fecha"], "loteria": fila["loteria"], "numero": fila["numero"]})
            ya_en_acumulado.add(clave)
            agregados_al_acumulado += 1
    acumulado.sort(key=lambda f: (f["fecha"], f["loteria"]))
    guardar_acumulado(acumulado)
    escribir_js_autocarga(acumulado)

    # Resumen en pantalla, listo para copiar
    print(f"\n{len(todas_finales)} registros nuevos. Guardado en: {ruta_csv}")
    print(f"{ARCHIVO_JS_AUTOCARGA.name} actualizado: {len(acumulado)} registros acumulados listos para autocarga en index.html.")
    print("\n--- BLOQUE LISTO PARA PEGAR EN IMPORTACIÓN MASIVA ---")
    print("fecha,loteria,numero")
    for fila in todas_finales:
        print(f"{fila['fecha']},{fila['loteria']},{fila['numero']}")
    print("--- FIN DEL BLOQUE ---")

    if resumen_diagnostico["sin_confirmar"]:
        print("\nNOMBRES SIN CONFIRMAR (se capturaron tal cual los muestra el sitio; revisa una vez contra tu MAPA_CANONICO):")
        for n in sorted(resumen_diagnostico["sin_confirmar"]):
            print(f"  - {n!r}")

    if resumen_diagnostico["numero_invalido"]:
        print("\nFilas con número inesperado (NO se capturaron):")
        for msg in resumen_diagnostico["numero_invalido"]:
            print(f"  - {msg}")

    if resumen_diagnostico["excluidos"]:
        print(f"\nExcluidos por regla (Suertudo, etc.): {len(resumen_diagnostico['excluidos'])} fila(s).")

    if fuentes_con_error:
        print("\nFuentes que fallaron en esta corrida (revisa tu conexión o si el sitio cambió de dirección):")
        for nombre_fuente, err in fuentes_con_error:
            print(f"  - {nombre_fuente}: {err}")


if __name__ == "__main__":
    main()
