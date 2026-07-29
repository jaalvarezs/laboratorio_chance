# Laboratorio de Chance

App de backtesting de métodos (caliente, rezagado, frío) por lotería, con 1,603 sorteos reales embebidos (chance + Lotería de Medellín desde 2007).

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
- **Base histórica (591 sorteos):** dentro de `index.html`; viaja con la app y funciona offline.
- **Sorteos que agregues:** en el almacenamiento local del navegador del dispositivo (`localStorage`). Persisten entre sesiones, pero son locales a cada equipo y se pierden si se borran los datos del navegador.
- Para sincronizar entre varios dispositivos, el siguiente paso natural es un backend en Supabase.

## Actualizar la base histórica
Los datos están en `index.html` en la constante `DATOS` (formato `["AAAA-MM-DD","Lotería","0000"]`). Se pueden agregar registros ahí directamente, o usar el formulario de la app.
