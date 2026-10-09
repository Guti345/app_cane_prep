CANE PREP: RESUMEN DEL PROYECTO Y PLAN HASTA EL 15 DE OCTUBRE
Estado al viernes 9 de octubre de 2026

1. OBJETIVO

Construir una aplicación web de práctica para las cinco personas del equipo
CANE. Permitirá entrenar con el banco de preguntas, responder bajo presión
de tiempo, guardar los intentos y comparar el rendimiento individual.

La meta es tener un MVP funcional a más tardar el jueves 15 de octubre.
Después, el equipo podrá practicar y corregir problemas hasta el concurso
del martes 27 de octubre, según la fecha que indicaste. La prioridad es
poner a funcionar el entrenamiento, no terminar todas las mejoras posibles.

2. QUÉ DEBE ENTREGAR EL MVP

- Acceso individual para los cinco integrantes, sin registro abierto.
- Práctica por área, preguntas aleatorias y modo simulacro.
- Preguntas con opciones múltiples, respetando entre 3 y 5 opciones.
- Enunciados y opciones legibles, con ecuaciones, tablas y figuras cuando
  correspondan. Markdown y LaTeX servirán para presentar el contenido.
- Cronómetro de 90 segundos por pregunta.
- Al responder, indicar si estuvo bien o mal y mostrar la opción correcta.
  No incluir explicaciones en esta primera versión.
- Guardar usuario, pregunta, opción elegida, resultado, tiempo y vencimientos.
- Ranking individual dentro del equipo, con mínimo 20 preguntas para aparecer.

Las estadísticas detalladas por área y persona y el repaso de fallos quedan
para después del MVP. No deben retrasar la primera versión utilizable.

3. DECISIONES TOMADAS Y PRECISIONES PENDIENTES

Arquitectura: tres capas independientes.
- Frontend: JavaScript/TypeScript, desplegado como sitio estático en Netlify.
- Backend: API REST con Python y FastAPI, desplegada en Render.
- Datos y usuarios: PostgreSQL y Auth en Supabase.

Se buscará usar planes gratuitos. Esto es una estrategia de despliegue,
no una garantía de disponibilidad o capacidad ilimitada. Hay que probar
el comportamiento de Render después de un periodo de inactividad.
Vercel y Koyeb se mencionaron como alternativas, no como cambios decididos.

Repositorio: Guti345/app_cane_prep será el lugar para documentar el avance.
Tú incorporas los archivos y haces los commits. No se ha modificado el repo
como parte de esta entrega. El monorepo es la estructura recomendada;
todavía falta tu visto bueno para adoptarlo como decisión definitiva.

Ranking: confirmaste el mínimo de 20 preguntas, ordenar por precisión y
usar el tiempo para desempatar. Precisión se propone medir como porcentaje
de respuestas correctas, no solo como cantidad de aciertos.

En la conversación se resumió el desempate como menor tiempo total, pero
esa elección entre tiempo total y medio no tuvo una confirmación expresa.
La vista practice_ranking entregada usa precisión, luego aciertos y tiempo
medio. Antes de implementarla como regla definitiva, hay que confirmar el
tiempo total y ajustar la vista para que no agregue desempates no acordados.
También debe cerrarse qué intentos cuentan: el SQL propone el primer intento
por pregunta y persona en sesiones completas, con 20 preguntas distintas.

Cronómetro: elegiste 90 segundos y se planteó que fuera configurable.
Para el MVP se trabajará con un único plazo que incluya lectura y respuesta,
contado por el servidor desde que emite la pregunta. Recargar la página no
debe reiniciarlo. El SQL ya fue actualizado a 90 segundos, pero el deadline
y el trigger siguen fijos en 90. Cambiar solo la configuración a 60 no basta:
hay que adaptar esos cálculos antes de afirmar que es configurable de punta
a punta. La regla exacta al vencer el plazo también debe quedar documentada.

Simulacro: se propusieron fases de 16, 12, 8 y 4 preguntas, distribuidas por
igual entre las cuatro áreas. Son plantillas de entrenamiento basadas en el
reglamento de 2025 revisado. Falta confirmar las reglas de 2026 antes de
presentarlas como una reproducción oficial del concurso.

4. CÓMO FUNCIONARÁ

El frontend mostrará la interfaz y usará Supabase Auth para iniciar sesión.
Con el token del usuario, pedirá a FastAPI las sesiones, preguntas y resultados.
FastAPI verificará la identidad y el equipo, controlará el tiempo, evaluará
las respuestas y guardará los intentos en Supabase.

El navegador no tendrá acceso directo a las tablas del juego ni decidirá
si una respuesta es correcta. Antes de responder recibirá el enunciado,
las opciones y los recursos, pero no la clave. Después de evaluar, la API
podrá mostrar la respuesta correcta de esa pregunta.

Las respuestas estarán separadas en question_keys. Las credenciales privadas
quedarán en el backend, nunca en el frontend ni en GitHub. CORS limitará los
orígenes permitidos, pero la autorización de usuarios y sesiones seguirá
siendo responsabilidad de FastAPI.

5. BANCO DE PREGUNTAS Y CONVERSIÓN

El conteo corregido de la guía de conversión es de 483 preguntas en 94 páginas:
- Econometría: 97 preguntas.
- Microeconomía: 132 preguntas.
- Macroeconomía: 123 preguntas.
- Historia y Pensamiento Económico: 131 preguntas.

Este conteo reemplaza las 487 preguntas del README anterior. La numeración
reinicia por área. No se debe inventar la edición o fase de una pregunta.

La clave está resaltada en amarillo. Por eso la conversión necesita leer
el PDF a color; copiar solo el texto pierde esa información. Transcribir
el resaltado no equivale a certificar que la respuesta sea correcta.

Proceso de trabajo de la guía:
1. Abrir un chat de IA por área y adjuntar el PDF, el esquema y el prompt.
2. Hacer una prueba con Econometría 1 a 8 y compararla contra el PDF.
3. Procesar 44 lotes: 13 de Econometría, 11 de Microeconomía, 11 de
   Macroeconomía y 9 de Historia. La guía trae los rangos y páginas.
4. Guardar los JSON en private-data/lotes/, fuera del repo público.
5. Validar formato, IDs, opciones, claves, fórmulas y recursos de cada lote.
6. Revisar las preguntas marcadas sin inventar respuestas ni completar
   enunciados dudosos. Extraer las figuras sin mostrar el resaltado.
7. Fusionar y reconciliar el inventario: deben quedar 483 preguntas únicas
   entre las convertidas y las pendientes, sin contar dos veces la prueba.
8. Importar contenido y claves por separado, vinculados y en una transacción.
   Activar solo las preguntas revisadas, con clave y recursos disponibles.

Se presupuestaron 44 envíos de lotes más uno de prueba. Si se reutiliza la
prueba validada como primer lote, no se repiten sus ocho preguntas al fusionar.
Los conflictos entre versiones se revisan antes de importar, no se pisan.

Hay unas diez incidencias conocidas. Seis preguntas no tienen resaltado:
Econometría 17, 81 y 95; Microeconomía 114; Historia 61 y 96. Econometría 4,
10 y 11 requieren revisión de texto, y Microeconomía 112 tiene un enunciado
incompleto. Puede aparecer alguna incidencia adicional al convertir.

483 es el inventario esperado, no la cantidad garantizada de preguntas
habilitadas el primer día. Las pendientes deben quedar fuera de las sesiones.

6. ESTRUCTURA PROPUESTA DEL PROYECTO

app_cane_prep/
  README.md          Alcance, instalación, decisiones y avance.
  .gitignore         Exclusiones antes de copiar material privado.
  frontend/          Interfaz y configuración de Netlify.
  backend/           FastAPI, configuración y dependencias para Render.
  supabase/
    migrations/      Cambios de estructura de la base de datos.
  docs/              Guías, arquitectura, prompt y esquema JSON.
  scripts/           Validación, fusión e importación de preguntas.
  private-data/      Solo local: PDF, lotes, banco y recursos originales.

Esta es una propuesta de organización, no una afirmación de que todas las
carpetas o funciones ya existen. Los archivos públicos documentan y ejecutan
el proyecto; private-data/ y los secretos no se versionan. Los recursos
que sí verá el jugador deben estar limpios de respuestas resaltadas.

7. ESTADO ACTUAL

Ya se prepararon el esquema JSON, el ejemplo, el prompt de conversión,
el diseño SQL, el README y las guías de arquitectura, conversión y Supabase.
El SQL actualizado usa 90 segundos. Son entregables de preparación, no
pruebas de que la aplicación esté funcionando.

Creaste tu cuenta y proyecto de Supabase. La vinculación con GitHub está en
proceso. Confirmaste que todavía no ejecutaste el SQL ni configuraste lo demás.
La migración real, Auth, perfiles, importación y despliegues siguen pendientes
según el último estado compartido. No se ha verificado tu panel privado.

Para la carga inicial se recomendó mantener Automatic branching y Deploy
to production apagados, aplicar una sola vez la migración mediante la CLI
con db push y comprobar su historial. No pegar primero el SQL en SQL Editor
y luego repetirlo con GitHub: esta migración no es idempotente.

Vincular GitHub a Supabase no despliega el frontend ni FastAPI. Netlify y
Render se configuran por separado. Auth tampoco crea automáticamente los
perfiles del equipo; habrá que crear las cinco identidades y sus perfiles.

8. PLAN PROPUESTO, DÍA A DÍA

Es una secuencia de trabajo con resultados comprobables, no una promesa de
que todo cabe sin obstáculos. Si participan los demás integrantes, se puede
repartir la conversión por áreas y trabajar interfaz y API en paralelo;
no hay asignaciones personales confirmadas todavía.

VIERNES 9 - Cerrar reglas y preparar la base
- Confirmar monorepo, desempate del ranking y qué intentos cuentan.
- Revisar los ajustes del SQL: ranking y cronómetro realmente configurable.
- Preparar exclusiones de Git y organizar los documentos.
- Terminar el enlace GitHub sin automatizar la primera carga.
- Probar la migración en una base limpia; aplicarla una vez en el proyecto
  correcto y verificar tablas, permisos e historial.
- Hacer y revisar la prueba de Econometría 1 a 8.
Resultado: reglas claras, base revisada y método de conversión validado.

SÁBADO 10 - Datos e infraestructura mínima
- Avanzar los lotes por áreas y validar cada salida.
- Crear la base del backend y desplegar una prueba de salud en Render.
- Desplegar el frontend mínimo en Netlify y comprobar que alcanza la API.
- Configurar secretos del servidor y los orígenes permitidos.
Resultado: conexión Netlify-Render-Supabase comprobada y lotes en proceso.

DOMINGO 11 - Usuarios e importación
- Completar los lotes, reconciliar conteos y revisar incidencias y figuras.
- Preparar el importador y cargar primero un conjunto pequeño revisado.
- Configurar Auth, los cinco usuarios y sus perfiles del equipo.
- Preparar el flujo de correos si se usan invitaciones o recuperación.
Resultado: acceso del equipo y primeras preguntas utilizables, sin claves
expuestas. Las dudosas quedan pendientes, no bloquean todo el banco.

LUNES 12 - Motor de práctica
- Implementar sesiones, selección de preguntas y recepción de respuestas.
- Controlar los 90 segundos en el servidor y guardar los intentos.
- Verificar recargas, vencimientos, doble envío y acceso a sesiones ajenas.
- Continuar la importación de preguntas listas.
Resultado: ciclo completo de pregunta, respuesta, evaluación y registro.

MARTES 13 - Interfaz y ranking
- Integrar login, selección de modo, pregunta, cronómetro y resultado.
- Presentar ecuaciones, opciones variables, tablas e imágenes.
- Implementar el ranking con la regla cerrada y su mínimo de 20 preguntas.
- Probar por área, aleatorio y las plantillas de simulacro.
Resultado: flujo de práctica completo desde la interfaz.

MIÉRCOLES 14 - Prueba con el equipo
- Probar en celulares con los cinco usuarios.
- Revisar legibilidad, latencia, sesiones incompletas y áreas con pocos datos.
- Intentar acceder sin token, leer claves y modificar intentos desde el cliente:
  todo acceso indebido debe ser rechazado.
- Corregir problemas y comprobar que cada versión usada conserva su contenido.
Resultado: lista corta de fallos corregidos y prueba de punta a punta.

JUEVES 15 - Publicar el MVP
- Hacer una prueba final de login, práctica, timeout, resultados y ranking.
- Confirmar URLs, recuperación de acceso y configuración de producción.
- Revisar los archivos públicos antes de que hagas los commits.
- Documentar cómo entrar, practicar y reportar un problema.
- Entregar el enlace al equipo y conservar una copia privada de los datos.
Resultado: versión utilizable, con limitaciones conocidas documentadas.

Si el plazo se aprieta, se aplazan las mejoras posteriores al MVP y se dejan
fuera las preguntas dudosas. No se recortan la autorización, la protección
de las claves ni las pruebas del cronómetro para llegar a la fecha.

9. CUÁNDO LO CONSIDERAMOS LISTO

El MVP estará listo cuando los cinco integrantes puedan entrar, practicar
en los modos previstos, responder preguntas legibles, recibir el feedback,
guardar intentos y consultar un ranking consistente con la regla elegida.

También debe demostrar que nadie puede ver la clave antes de responder,
reiniciar el plazo recargando, guardar dos respuestas finales o consultar
sesiones ajenas. Las preguntas activas deben estar revisadas y completas.

Del 16 al 26 de octubre: práctica del equipo, correcciones y, si hay tiempo,
estadísticas y repaso de fallos. El 27 de octubre queda como fecha objetivo
del concurso según tu calendario, no como plazo para terminar la aplicación.

DOCUMENTOS DE APOYO

README, ARQUITECTURA, GUIA_CONVERSION y GUIA_SUPABASE_CANE entregados el 9 de
octubre. Este resumen recoge el estado de la conversación y distingue lo
confirmado, lo propuesto y lo pendiente. No incluye código ni ejecuta cambios.
Ante diferencias, usar el conteo corregido de 483 y el plazo elegido de 90 s;
actualizar los documentos anteriores para que no conserven 487 o 60 s.
