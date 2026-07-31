# Laboratorio de Chance

App de backtesting de métodos (caliente, rezagado, frío) por lotería, con **8.705 sorteos reales embebidos** (chance + loterías departamentales + Lotería de Medellín, 2007-01-05 → 2026-07-30, 61 loterías). Cifra verificada directamente del array `DATOS` en `index.html`, no estimada.

**Pestaña "3 Cifras" (v24):** análisis de la modalidad reducida de apuesta — últimas 3 cifras de cualquier lotería (en Pick 3 esas 3 cifras ya son el resultado completo). Mismo motor estadístico y mismo dato de siempre, solo ignorando la cifra de mil; incluye Pronóstico, Backtest con tendencia de dígitos y persistencia, Analizar un número (3 cifras), Panorama por lotería y Alertas (escaneo de todas las loterías × 5 métodos × 10 dígitos).

**Fase 1 — integridad de datos y seguridad (v25):** primera fase de una auditoría más amplia. Ver `AUDITORIA.md` para el diagnóstico completo. Resumen de lo corregido:
- **Duplicados vs. conflictos:** la depuración ya no usa una ventana de "±5 días" (podía borrar sorteos legítimos). Ahora la llave es *lotería normalizada + fecha exacta*: mismo número → duplicado exacto (se puede quitar); número distinto → conflicto real, se reporta y nunca se borra o sobreescribe solo.
- **Importación con vista previa:** antes de aplicar una lista pegada, se muestra cuántos son nuevos, duplicados, conflictos y errores; hay que confirmar explícitamente.
- **Deshacer última importación** (masiva, individual o de archivo de respaldo).
- **Validación real de fechas:** ya no basta con el formato `AAAA-MM-DD`; se rechazan fechas de calendario imposibles (ej. 31 de febrero) y se avisa si la fecha es futura.
- **Saneamiento de nombres de lotería:** se elimina cualquier carácter fuera de letras/números/espacios/puntuación básica — cierra la puerta a HTML/JS guardado como "nombre de lotería" (XSS), aplicado en el punto de lectura central así que también limpia datos ya guardados.
- **Protección contra CSV injection:** campos que empiecen por `= + - @` se exportan con un apóstrofo de escape (se revierte automáticamente si ese mismo respaldo se vuelve a importar).
- **Parser de importación:** ahora sí ignora líneas que empiezan con `#` (antes el propio encabezado del respaldo exportado contaba como "línea con error" al reimportarlo).

**Fase 1b — integridad del backtesting (v26):**
- **Fuga temporal del mismo día — corregida.** El backtest entrenaba por índice, así que en el agregado "TODO EL CHANCE" (27,4 sorteos por fecha en promedio) el resultado de una lotería se usaba para "pronosticar" otra del mismo día. Ahora el entrenamiento se corta en la fecha: solo sorteos de fechas *estrictamente anteriores*. Sobre datos de prueba diseñados para exponerla, la fuga inflaba el acierto de 0,40 a 0,96 cifras por sorteo (z=+27,5 → z=+1,4 tras la corrección). Sobre la base real el efecto fue moderado pero consistente: los cinco métodos se movieron hacia el azar. Con una lotería individual (un sorteo por fecha) los resultados son idénticos bit a bit — no se altera ningún historial retroactivamente.
- **Empates — corregidos.** Ante dígitos con la misma frecuencia el código elegía siempre el menor, sesgando los pronósticos hacia el 0 (muy notorio en el método Frío). Ahora se desempata entre todos los empatados con un sorteo sembrado de forma determinista: imparcial, pero reproducible corrida a corrida.
- **El agregado ya no se presenta como jugada:** mezcla decenas de loterías, sirve para auditar uniformidad, no para apostar. Lleva advertencia explícita.
- **Balotas al día con Fase 1:** clasificación duplicado/conflicto, validación de fechas y chequeo de conflicto en el formulario individual.
- **Validación con simulaciones:** 5 semillas × 3.000 sorteos uniformes × 5 métodos → |z| máximo 2,26 (ningún método aparenta ventaja). Con un sesgo artificial conocido (unidades = 7 el 40% de las veces) → se detecta con z=+33,2.

**Fase 1c — base central integrada (v27):** el respaldo de 7.109 registros quedó fusionado con los 1.603 embebidos → **8.705 sorteos**, 61 loterías, 42 con ≥100 sorteos. Verificado: 0 duplicados, 0 conflictos, 0 fechas inválidas, ceros a la izquierda intactos, 77 nombres crudos normalizados a 61. Se excluyeron 6 registros con motivo documentado (2 de Suertudo por regla del proyecto, 4 duplicados de Medellín por fecha de pago). **Resultado del análisis: 210 combinaciones lotería×método → 8 con |z|≥2 (se esperaban 9,6 por azar), 0 con |z|≥3.** El escaneo de dígitos da 29 alertas frente a 28,7 esperadas. Ninguna señal sobrevive el umbral corregido más el chequeo de persistencia — incluida la del dígito 1 en Chontico Noche, que resulta no sostenida (mitad 1: z=−0,70; mitad 2: z=+4,47). También se añadieron **umbrales de muestra por tipo de análisis**: con n máximo de 211, ninguna lotería alcanza muestra suficiente para Pares (necesita 1.000) ni Ternas (3.000), y las tarjetas ahora lo advierten.

**Pendiente:** Corrección de sesgo en "Mejor jugada empírica" y fuga temporal en el agregado "Todo el chance" quedan para la fase de backtesting/modelos, no se tocaron aquí a propósito.

## Publicar en GitHub Pages
1. Crear un repositorio nuevo (por ejemplo `lab-chance`).
2. Subir estos 6 archivos a la raíz del repositorio.
3. En **Settings → Pages**, en *Source* elegir `Deploy from a branch`, rama `main`, carpeta `/ (root)` y guardar.
4. En 1–2 minutos la app queda en `https://TU_USUARIO.github.io/lab-chance/`.

## Instalar en el celular
1. Abrir el link en Chrome (Android) o Safari (iPhone).
2. Menú → **Agregar a pantalla de inicio** (Chrome puede ofrecer "Instalar aplicación").
3. Queda como app independiente, con ícono propio y funcionamiento sin internet (los datos van embebidos).

## Dónde se guardan los datos
- **Base histórica (8.705 sorteos):** dentro de `index.html`, en la constante `DATOS`; viaja con la app y funciona offline. Rango: 2007-01-05 a 2026-07-30. Ya no hace falta importar el respaldo en cada dispositivo.
- **Sorteos que agregues:** en el almacenamiento local del navegador del dispositivo (`localStorage`) o, dentro de Claude, en almacenamiento persistente de la conversación. Persisten entre sesiones, pero son locales a cada equipo/contexto y se pierden si se borran los datos del navegador.
- Para sincronizar entre varios dispositivos, el siguiente paso natural es un backend en Supabase (planeado para una fase posterior).

## Actualizar la base histórica
Los datos están en `index.html` en la constante `DATOS` (formato `["AAAA-MM-DD","Lotería","0000"]`). Se pueden agregar registros ahí directamente, o usar el formulario de la app (con vista previa y deshacer para importaciones masivas).
