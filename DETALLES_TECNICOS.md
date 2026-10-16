# Data Steward — beta ReAct del equipo

Adaptación de `agente_data_steward.py` y `callbacks.py` del curso.
Modelo elegido: **llama3:instruct**, mediante **Ollama local**. Temperatura 0.
No requiere API key ni pago a OpenAI. Conserva LangChain y el ciclo ReAct
manual, sin AgentExecutor. El modelo decide las herramientas; Python calcula
las métricas y ejecuta las validaciones.

## Ejecución independiente

Esta carpeta incluye su propio `pyproject.toml`, `uv.lock` y `.python-version`.
Sigue las instrucciones de `README.md`. No requiere copiar archivos al tutorial
original ni utilizar su entorno. El código principal proviene del ejemplo
`6_ReAct_agent_with_callbacks.py` del curso, adaptado y renombrado.

## Consigna y evidencia que deben mostrar

| Requisito | Dónde mostrarlo |
|---|---|
| Agente autónomo tipo ReAct beta | `run_audit` en el script principal: modelo → parser → herramienta → observación → siguiente decisión |
| Prompt preliminar Data Steward | `prompt_data_steward.txt`; se carga realmente en el agente |
| Prompt y modelo elegidos | Prompt anterior + `ChatOllama(model="llama3:instruct", temperature=0)` |
| Dos herramientas utilizadas | Trazas `[TOOL START] perfilar_dataset` y `[TOOL START] validar_reglas`, ambas con `[TOOL END]` |
| Código en repo del equipo | Subir los archivos a su repositorio y mostrar el enlace |

**No se ha subido este paquete a su repositorio.** Esa parte de la entrega
debe hacerse desde su cuenta/equipo. Las trazas reales se obtienen al ejecutar
el modelo en su PC; las pruebas offline no sustituyen esa evidencia.

## Herramientas

- `perfilar_dataset(ruta_csv)`: filas, columnas, nulos por columna, cantidad
  de valores distintos, tipo aparente y duplicados completos excedentes.
- `validar_reglas(ruta_csv)`: aplica `reglas_calidad.json`, que se carga al
  iniciar, y devuelve problemas, cantidades, prioridades e índices de ejemplo.
  Revisa campos obligatorios, identificadores únicos, rangos numéricos,
  catálogos, fechas y formato básico de correo. También detecta duplicados
  completos y columnas ausentes.

Ambas herramientas aceptan el string `dataset_actual` porque el parser original
ReActSingleInputOutputParser admite una sola entrada. El programa lo resuelve
al CSV elegido por la CLI. También se acepta la ruta exacta, recortando
comentarios posteriores a su primera línea. No se incluyen valores personales en los resultados: solo
métricas e índices. El CSV no se modifica.

## Datos y reglas de demostración

`clientes_demo.csv` es **sintético**, con 12 filas y 6 columnas. Las reglas
son ejemplos definidos para la práctica; deben acordarse con el responsable
del negocio antes de aplicar el agente a datos reales.

| Problema esperado | Cantidad |
|---|---:|
| Nombre obligatorio vacío | 1 |
| Email obligatorio vacío | 1 |
| Filas involucradas en IDs repetidos | 4 |
| Edad no numérica | 1 |
| Edad fuera de 0–120 | 2 |
| País fuera de MX, CO, ES | 1 |
| Fecha imposible | 1 |
| Formato de email inválido | 1 |
| Duplicado completo excedente | 1 |

**12 filas distintas** presentan al menos un hallazgo. Los conteos se solapan:
no deben sumarse para obtener filas afectadas. Unicidad incluye todas las
apariciones de un ID repetido; duplicado completo cuenta solo las copias
posteriores a la primera. Los índices son registros lógicos con encabezado=1,
no necesariamente líneas físicas si hay campos CSV multilínea.

Se consideran nulos vacío, `null`, `none`, `nan` y `n/a`, sin distinguir
mayúsculas. Los campos opcionales nulos no se validan por formato o rango.
Los catálogos sí distinguen mayúsculas; las comparaciones de reglas recortan
espacios exteriores. Duplicados completos comparan los campos originales.
Los tipos del perfil son inferencias, no tipos de negocio garantizados.

## Otra entrada

```powershell
uv run python agente_data_steward.py --csv "datos/clientes.csv" --rules "reglas_calidad.json" --output "mi_auditoria.json"
```

Modifica las reglas para usar los nombres de columna del nuevo archivo.
Si faltan columnas, la validación se marca `incompleto`. Formatos aceptados:
CSV UTF-8 / UTF-8 con BOM, separador coma, punto y coma o tabulador, hasta
10 MiB y 100000 registros. No hay soporte de Excel, base de datos o streaming
en esta beta.

## Callbacks y límites del ciclo

El script llama `Tool.invoke(..., config={"callbacks": [...]})`, en lugar de
`.func`, para disparar los eventos reales de herramientas. Cada consulta al
modelo también usa callbacks. Para mostrar el prompt completo:

```powershell
uv run python agente_data_steward.py --verbose
```

El historial se ubica antes de `Thought:`. Hay máximo 10 iteraciones,
reintentos acotados ante formato incorrecto, bloqueo de respuesta final sin
dos herramientas exitosas y reutilización de resultados ante solicitudes
repetidas. No se ejecutan herramientas artificialmente si el modelo no las
elige. `llama3:instruct` puede seguir fallando el formato o alcanzar el límite:
en ese caso se debe mostrar el fallo y ajustar el prompt/modelo, no ocultarlo.

Las cifras confiables están en `evidencia`. Python ensambla `reporte_final`
con esas cifras y sus prioridades. LLaMA genera únicamente las recomendaciones,
una por identificador de hallazgo, mediante el prompt `prompt_reporte.txt`.
Se verifica su estructura y cobertura, pero no la corrección semántica de
cada sugerencia. No se garantiza cumplimiento regulatorio, corrección de
datos o calidad total.

## Verificación offline

```powershell
uv run python verificar_beta.py
```

Comprueba métricas conocidas, reglas, CSV inválido, columnas ausentes,
callbacks reales de herramientas, recuperación del parser, respuestas finales
prematuras, acciones repetidas, rutas erróneas y límite de iteraciones.
Las respuestas del modelo en estas pruebas son SIMULADAS. No se ha ejecutado
LLaMA en el entorno donde se preparó el paquete: deben ejecutar y capturar la
demostración real en su equipo.

## Archivos a subir al repositorio

Los tres módulos `.py`, `verificar_beta.py`, `prompt_data_steward.txt`, `prompt_reporte.txt`,
`clientes_demo.csv`, `reglas_calidad.json` y este README. Conserva los archivos
de dependencias del curso. No subas `.venv`, `.env` ni datasets personales.

Guion breve: presentar objetivo y modelo → enseñar prompt → ejecutar auditoría
→ señalar ambas llamadas de herramienta → comparar hallazgos con las reglas
→ mostrar limitaciones y el repositorio del equipo.
