# Agente Data Steward — ReAct con Ollama

**Versión beta para la entrega** Audita la calidad de un CSV,
identifica problemas y recomienda acciones usando un agente ReAct con dos
herramientas.

**Modelo:** `llama3:instruct` · **Proveedor:** Ollama local · **Framework:**
LangChain · **Python:** 3.12 · **API key de OpenAI:** no requerida.

## Dónde revisar cada elemento

| Elemento | Archivo o evidencia |
|---|---|
| Código principal del agente ReAct | [agente_data_steward.py](agente_data_steward.py), función `run_audit` |
| Prompt preliminar de Data Steward | [prompt_data_steward.txt](prompt_data_steward.txt); síntesis en [prompt_reporte.txt](prompt_reporte.txt) |
| Modelo seleccionado | `ChatOllama` en `agente_data_steward.py` |
| Dos herramientas | `perfilar_dataset` y `validar_reglas`, registradas en `build_tools`; cálculos en [steward_tools.py](steward_tools.py) |
| Herramientas utilizadas durante la ejecución | Eventos `[TOOL START]` y `[TOOL END]` de ambas herramientas en la terminal |


## Instalar uv y Ollama en Windows

Realiza la instalación en **Windows PowerShell**. Si alguna herramienta ya
está instalada, comprueba su versión y continúa con el siguiente paso.

### 1. Instalar uv

`uv` instala las dependencias y administra el entorno de Python del proyecto.
Ejecuta el instalador oficial:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Cierra PowerShell y abre una ventana nueva. Si usas VS Code, cierra todas sus
ventanas y vuelve a abrirlo para que las terminales reconozcan el nuevo `PATH`.
Comprueba la instalación:

```powershell
uv --version
```

Si aparece `uv is not recognized`, prueba la ruta habitual del instalador:

```powershell
& "$env:USERPROFILE\.local\bin\uv.exe" --version
```

Si esta ruta muestra la versión, puedes utilizarla en los comandos posteriores.
La instalación de dependencias con `uv sync --locked` utilizará Python 3.12,
según los archivos del proyecto, y podrá descargarlo si hace falta.

Documentación oficial: [instalación de uv](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Instalar Ollama

Ollama ejecuta el modelo de lenguaje en tu computadora. En PowerShell ejecuta:

```powershell
irm https://ollama.com/install.ps1 | iex
```

Como alternativa, descarga y ejecuta el instalador desde
[Ollama para Windows](https://ollama.com/download/windows).
Elige solo uno de los dos métodos de instalación.

Al terminar, abre Ollama desde el menú Inicio. Cierra y vuelve a abrir
PowerShell o todas las ventanas de VS Code. Comprueba:

```powershell
ollama --version
```

Si el comando no se reconoce, prueba la ubicación habitual de instalación:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" --version
```

### 3. Descargar el modelo del proyecto

Con Ollama abierto, descarga `llama3:instruct` una sola vez. Esta descarga
requiere conexión a internet y puede tardar varios minutos:

```powershell
ollama pull llama3:instruct
ollama list
```

Comprueba que `llama3:instruct` aparezca en la lista. Si necesitas la ruta
completa, usa:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull llama3:instruct
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" list
```

Si aparece un error de conexión con el servidor, comprueba que Ollama esté
abierto. También puedes iniciarlo con `ollama serve` en otra terminal y
mantenerla abierta mientras ejecutas la demostración.

## Ejecutar la demostración

Con `uv` instalado y Ollama abierto con el modelo descargado, abre **esta
carpeta** en VS Code. La terminal debe estar en la carpeta que contiene
`pyproject.toml` y `agente_data_steward.py`. Ejecuta:

```powershell
uv sync --locked
uv run python agente_data_steward.py
```

`uv` utilizará Python 3.12 y creará una `.venv` propia en esta carpeta. El
script lee `clientes_demo.csv` y `reglas_calidad.json`, llama a las herramientas
y guarda evidencia y reporte en `auditoria_resultado.json`.

Si en tu terminal todavía no se reconocen `uv` u `ollama`, usa sus rutas:

```powershell
& "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" pull llama3:instruct
& "$env:USERPROFILE\.local\bin\uv.exe" sync --locked
& "$env:USERPROFILE\.local\bin\uv.exe" run python agente_data_steward.py
```

Si Ollama ya tiene descargado el modelo, omite el comando `pull`.

## Qué hace cada herramienta

1. **perfilar_dataset:** cuenta filas, columnas, nulos, valores distintos y
   duplicados completos; infiere tipos aparentes.
2. **validar_reglas:** comprueba campos obligatorios, IDs únicos, edades,
   catálogo de países, fechas, formato de correo y duplicados completos.

El modelo elige las llamadas. Python calcula las cifras y devuelve las
observaciones. También construye el resumen y la tabla final de hallazgos.
LLaMA propone una recomendación por hallazgo. El CSV no se modifica.

## Archivos de la entrega

| Archivo | Propósito |
|---|---|
| `agente_data_steward.py` | Punto de entrada y ciclo ReAct manual |
| `steward_tools.py` | Perfilado y validación de datos |
| `callbacks.py` | Trazas del modelo y las herramientas |
| `prompt_data_steward.txt` | Rol e instrucciones que recibe el modelo |
| `prompt_reporte.txt` | Instrucciones de síntesis una vez calculada la evidencia |
| `clientes_demo.csv` | 12 registros sintéticos con errores conocidos |
| `reglas_calidad.json` | Reglas de calidad de la demostración |
| `pyproject.toml`, `uv.lock`, `.python-version` | Dependencias y versión de Python |
| `verificar_beta.py` | Diecinueve pruebas offline |
| `DETALLES_TECNICOS.md` | Conteos esperados, límites y guía técnica |

## Verificación y estado de la beta

```powershell
uv run python verificar_beta.py
```

Las diecinueve pruebas verifican cálculos, llamadas de herramientas y controles del
ciclo con respuestas del modelo **simuladas**. No sustituyen una ejecución
real de LLaMA. El programa detiene el ciclo al alcanzar diez iteraciones y registra ese estado como `limite_alcanzado`, sin presentarlo como éxito.


## Corrección de la beta: entradas de herramientas

Las herramientas reciben `dataset_actual`, un identificador del CSV que se
seleccionó al iniciar. El modelo sigue eligiendo qué herramienta llamar;
Python resuelve ese identificador a la ruta real. Así no se necesita que el
modelo copie rutas largas de Windows. Por compatibilidad también se acepta
la ruta exacta, usando solo la primera línea de `Action Input` y quitando las
comillas. Frases posteriores como “Espero el resultado…” quedan fuera de la
entrada y del historial de acciones ejecutadas.

Se tolera un marcador `Final Answer:` vacío al final de una solicitud de
herramienta, pero no una respuesta que mezcle una acción y un reporte final.
Un `Final Answer:` vacío por sí solo tampoco se considera éxito.

## Cierre del agente y generación del reporte

El ciclo ReAct se usa para seleccionar y ejecutar las herramientas. Cuando
ambas devuelven resultados correctos, el controlador detecta que se alcanzó
ese objetivo e inicia una llamada de síntesis con un prompt independiente,
`prompt_reporte.txt`. Esa consulta recibe solo la evidencia y las instrucciones
del reporte, sin el historial de acciones. Esto evita que el modelo vuelva a
tratar `Final Answer` como nombre de herramienta.

La etapa se anuncia como `[FASE REPORTE]`. LLaMA entrega JSON en modo
`format="json"`, con una acción propuesta para cada identificador H1, H2, etc.
El programa comprueba que estén todos los identificadores, sin inventar otros,
y que cada propuesta sea texto no vacío. Si falla, se reintenta dentro del
límite global de diez llamadas conservando la evidencia y sin repetir tools.

Python construye el reporte final: conteos, prioridades y tabla de hallazgos
provienen exclusivamente de la evidencia. Así el modelo no puede cambiar el
recuento o excluir problemas de esa tabla. Las recomendaciones se muestran
como sugerencias del modelo y requieren revisión de su contenido.

El JSON guarda `evidencia`, `reporte_modelo` (respuesta JSON original del LLM),
`recomendaciones_modelo` (acciones validadas en estructura y cobertura) y
`reporte_final` (texto completo ensamblado por Python). La validación estructural
no garantiza que cada recomendación sea correcta para el negocio.

## Si el entorno virtual en OneDrive queda bloqueado

Desde esta carpeta usa un entorno fuera de OneDrive en la misma terminal:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\uv\envs\data-steward"
& "$env:USERPROFILE\.local\bin\uv.exe" sync --locked --link-mode=copy
& "$env:USERPROFILE\.local\bin\uv.exe" run --link-mode=copy python agente_data_steward.py
```

Repite la primera línea al abrir otra terminal. Para una actualización del
código sin cambios de dependencias basta la primera línea y el comando `run`.

## Procedencia

Adaptado del ejemplo `6_ReAct_agent_with_callbacks.py` y `callbacks.py` de
[TEC AI LangChain](https://github.com/ofc-tec/tec-ai-langchain). Se mantiene
el ciclo ReAct manual; se agregan el rol Data Steward, las herramientas de
calidad de datos, reglas, datos sintéticos y controles de ejecución.
