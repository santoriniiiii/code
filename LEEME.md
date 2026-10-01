# FarIQ: Quiz

Juego tipo Kahoot en vivo: 30 segundos por pregunta, puntos extra por rapidez y podio al final.

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `index.html` | Pantalla del jugador (celular): unirse con nombre y responder |
| `host.html` | Panel del presentador (proyector): QR, iniciar, avanzar, resultados y podio |
| `style.css` | Diseño compartido |
| `common.js` | Funciones compartidas (temporizador, confeti, mostrar preguntas) |
| `api/game.js` | Servidor: guarda jugadores, respuestas y puntajes en Redis |
| `api/_questions.js` | Las 58 preguntas de la Unidad 1 con sus respuestas correctas |
| `vercel.json` | Configuración de Vercel |

Los HTML **no funcionan solos** (abriéndolos con doble clic): necesitan el servidor (`api/game.js`)
y la base de datos para que todos los jugadores compartan la misma partida.

## Publicar en Vercel

1. Sube esta carpeta completa a un proyecto de Vercel (o a un repositorio de GitHub conectado a Vercel).
2. En el proyecto: **Storage → Create Database → Upstash for Redis** y conéctala al proyecto.
   Esto crea solas las variables `KV_REST_API_URL` y `KV_REST_API_TOKEN`.
3. En **Settings → Environment Variables** agrega `HOST_PIN` con el PIN que quieras para el presentador.
4. Vuelve a desplegar.

## Cambiar las preguntas

Edita `api/_questions.js`. Cada pregunta tiene esta forma:

```js
{
  "text": "¿Pregunta?",
  "options": ["Opción A", "Opción B", "Opción C", "Opción D"],
  "correct": [1],          // 0 = A, 1 = B, 2 = C, 3 = D (puede haber más de una)
  "level": "FÁCIL",        // opcional
  "context": "Escenario…"  // opcional
}
```

## Ajustes rápidos (en `api/game.js`)

- `DURATION = 30000` → tiempo por pregunta en milisegundos.
- `MAX_POINTS = 1000` → puntos por responder bien al instante (responder al final del tiempo da la mitad).
