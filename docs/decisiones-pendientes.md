# Decisiones pendientes

Lista de lo que **no** está cerrado. No se debe implementar nada de aquí como
si fuera definitivo.

## Ranking

Confirmado:

- Mínimo de 20 preguntas para aparecer.
- Se ordena por precisión (propuesta: porcentaje de respuestas correctas, no
  solo cantidad de aciertos).
- El tiempo desempata.

Pendiente de confirmar:

- ¿Desempate por **tiempo total** o por **tiempo medio**? En la conversación se
  habló de menor tiempo total, pero no hubo confirmación expresa.
- Qué intentos cuentan.

El SQL recibido propone precisión, luego aciertos y luego tiempo medio, usando
las primeras respuestas por pregunta fuente en sesiones completadas. **No es la
fórmula final aprobada**: antes de implementarla hay que revisar la vista
`practice_ranking` para que no agregue desempates no acordados (p. ej. aciertos).

## Cronómetro configurable

El plazo elegido es de 90 segundos, pero el SQL lo usa fijo en varios lugares
(entre ellos el cálculo del `deadline` y un trigger). Cambiar solo
`time_limit_seconds` **no basta**. Hay que adaptar esos cálculos antes de
presentar el plazo como configurable de punta a punta. También falta
documentar la regla exacta al vencer el plazo.

## Supabase, Auth, datos y despliegues

Nada de esto está terminado:

- Migración real sin escribir/aplicar; sin historial verificado.
- Auth, las cinco identidades del equipo y sus perfiles.
- Importación privada del banco de preguntas (483 esperadas, no garantizadas
  como habilitadas el primer día).
- Endpoints de juego.
- Despliegues en Netlify y Render, y comprobar que el frontend alcanza la API.

## Otros

- **Versión de Python en Render**: el backend se probó localmente con 3.14.5.
  Al desplegar hay que fijar la versión (p. ej. con `PYTHON_VERSION`) y
  comprobar que Render la admite. No se creó `runtime.txt`.
- **Servidor de Render tras inactividad**: probar su comportamiento en el plan
  gratuito antes de depender de él.
- **Simulacro**: las fases (16, 12, 8 y 4 preguntas) se basan en el reglamento
  de 2025; faltan las reglas de 2026.
- **Dependencia de pruebas**: con `httpx` 0.28 el cliente de pruebas de
  Starlette emite una advertencia de deprecación que recomienda `httpx2`. Las
  pruebas pasan; está sin decidir si migrar.
