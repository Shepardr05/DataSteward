"""Beta Data Steward: adaptación del ciclo ReAct manual del curso."""
import argparse
import csv
import json
import os
import re
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents.format_scratchpad import format_log_to_str
from langchain.agents.output_parsers import ReActSingleInputOutputParser
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import Tool, render_text_description
from langchain_ollama import ChatOllama

from callbacks import AgentCallbackHandler
from steward_tools import load_rules, profile_dataset, validate_rules

BASE = Path(__file__).resolve().parent


def clean_tool_input(value):
    """El parser original captura todo lo que sigue a Action Input.

    Una herramienta de esta beta solo recibe un identificador o ruta en una
    línea. El comentario posterior del modelo no forma parte de la entrada.
    """
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    while lines and lines[0].startswith("```"):
        lines.pop(0)
    return lines[0].strip('`"\'').strip() if lines else ""


def parse_response(message):
    """Conserva el parser ReAct del curso y normaliza su entrada monolínea."""
    text = message.content if hasattr(message, "content") else str(message)
    if not isinstance(text, str):
        raise OutputParserException("Se esperaba una respuesta de texto.")
    # LLaMA a veces añade un marcador final vacío tras una acción válida.
    # No se acepta una respuesta que mezcle acción y respuesta final con texto.
    if re.search(r"(?m)^\s*Action(?:\s*\d+)?\s*:", text):
        text = re.sub(r"\n\s*Final Answer:\s*$", "", text)
    parsed = ReActSingleInputOutputParser().parse(text)
    if isinstance(parsed, AgentAction):
        value = clean_tool_input(parsed.tool_input)
        if not value:
            raise OutputParserException("Action Input está vacío.")
        # El historial conserva la acción ejecutada, sin el comentario añadido.
        return AgentAction(tool=parsed.tool, tool_input=value,
                           log=f"Action: {parsed.tool}\nAction Input: {value}")
    if not parsed.return_values.get("output", "").strip():
        raise OutputParserException("Final Answer está vacío.")
    return parsed


def build_tools(dataset_path, rules):
    """Cada tool acepta un solo string, compatible con el parser original."""
    target = Path(dataset_path).resolve()

    def checked_path(value):
        cleaned = clean_tool_input(value)
        if cleaned == "dataset_actual":
            return target
        if not cleaned or Path(cleaned).resolve() != target:
            raise ValueError("Usa Action Input: dataset_actual para el CSV seleccionado.")
        return target

    def profile(value):
        return json.dumps(profile_dataset(checked_path(value)), ensure_ascii=False)

    def validate(value):
        return json.dumps(validate_rules(checked_path(value), rules), ensure_ascii=False)

    return [
        Tool(name="perfilar_dataset", func=profile,
             description="Perfila el CSV seleccionado: filas, columnas, nulos, tipos aparentes y duplicados. Entrada única: dataset_actual."),
        Tool(name="validar_reglas", func=validate,
             description="Valida el CSV seleccionado con reglas JSON: obligatorios, unicidad, rangos, catálogo, fechas y emails. Entrada única: dataset_actual."),
    ]


def generate_report(llm, evidence, handler, feedback=""):
    """El modelo propone una acción por hallazgo; no reescribe las métricas."""
    instructions = (BASE / "prompt_reporte.txt").read_text(encoding="utf-8")
    findings = {f"H{i}": item for i, item in enumerate(evidence["validar_reglas"]["hallazgos"], 1)}
    response = llm.bind(format="json", options={"temperature": 0, "num_predict": 1200}).invoke([
        SystemMessage(content=instructions + feedback),
        HumanMessage(content="Evidencia calculada por Python:\n" + json.dumps(
            {"evidencia": evidence, "hallazgos_identificados": findings}, ensure_ascii=False)),
    ], config={"callbacks": [handler]})
    text = response.content if hasattr(response, "content") else str(response)
    if not isinstance(text, str):
        raise OutputParserException("Se esperaba JSON con recomendaciones.")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OutputParserException("La propuesta no contiene JSON válido.") from exc
    if not isinstance(data, dict) or set(data) != {"acciones"} or not isinstance(data["acciones"], dict):
        raise OutputParserException('Usa exclusivamente el objeto JSON {"acciones": {...}}.')
    actions = data["acciones"]
    if set(actions) != set(findings) or any(not isinstance(v, str) or not v.strip() for v in actions.values()):
        raise OutputParserException("Incluye una acción no vacía por cada identificador H, sin omitir ni inventar hallazgos.")
    return actions, text


def render_report(evidence, actions):
    """Hechos y prioridades provienen exclusivamente de las herramientas."""
    profile = evidence["perfilar_dataset"]
    validation = evidence["validar_reglas"]
    findings = validation["hallazgos"]
    counts = Counter(item["prioridad"] for item in findings)
    lines = ["Reporte de calidad de datos", "", "RESUMEN VERIFICADO",
             f"Archivo: {profile['archivo']}", f"Filas: {profile['filas']} | Columnas: {profile['columnas']}",
             f"Estado de la validación: {validation['estado']}",
             f"Hallazgos verificados: {len(findings)} | Alta: {counts['alta']} | Media: {counts['media']}",
             f"Filas con algún hallazgo: {validation['filas_con_algun_hallazgo']}",
             "", "HALLAZGOS VERIFICADOS (cifras y prioridades calculadas por Python)",
             "ID | Regla | Columna | Cantidad | Prioridad"]
    for i, item in enumerate(findings, 1):
        count = item["cantidad"] if item["cantidad"] is not None else "no aplica"
        lines.append(f"H{i} | {item['regla']} | {item['columna']} | {count} | {item['prioridad']}")
    if not findings:
        lines.append("Sin hallazgos para las reglas comprobadas.")
    lines.extend(["", "RECOMENDACIONES DEL MODELO (sugerencias sujetas a revisión)"])
    order = sorted(enumerate(findings, 1), key=lambda pair: {"alta": 0, "media": 1}.get(pair[1]["prioridad"], 2))
    for i, item in order:
        lines.append(f"H{i} [{item['prioridad']}]: {actions[f'H{i}'].strip()}")
    if not findings:
        lines.append("No hay hallazgos específicos que requieran una recomendación.")
    lines.extend(["", "LÍMITES",
                  "Los hallazgos pueden solaparse: sus cantidades no se suman para contar filas afectadas.",
                  "Unicidad cuenta todas las apariciones repetidas; duplicados completos solo las copias excedentes.",
                  "Los índices de ejemplo incluyen el encabezado como registro 1.",
                  "Reglas preliminares a confirmar con el negocio; email comprueba formato, no existencia.",
                  "El CSV no se modificó. No se garantiza la calidad fuera de las reglas comprobadas.",
                  "Se valida la estructura y cobertura de las recomendaciones, no la corrección semántica de cada sugerencia."])
    if validation["columnas_ausentes"]:
        lines.append("Validación incompleta; columnas ausentes: " + ", ".join(validation["columnas_ausentes"]))
    return "\n".join(lines)


def run_audit(llm, dataset_path, rules, handler, max_iters=10):
    """El LLM elige las acciones; no se simulan llamadas a herramientas."""
    tools = build_tools(dataset_path, rules)
    by_name = {t.name: t for t in tools}
    prompt = PromptTemplate.from_template(
        (BASE / "prompt_data_steward.txt").read_text(encoding="utf-8")
    ).partial(tools=render_text_description(tools), tool_names=", ".join(by_name))
    # Mismo pipeline manual del curso; el historial precede a Thought.
    agent = (
        {"input": lambda x: x["input"],
         "agent_scratchpad": lambda x: format_log_to_str(x["agent_scratchpad"], llm_prefix="")}
        | prompt | llm | parse_response
    )
    request = (
        f"Audita este CSV: {Path(dataset_path).resolve().as_posix()}\n"
        "Este archivo está asociado al identificador dataset_actual. Usa ese identificador como Action Input.\n"
        "Llama a las dos herramientas y recomienda acciones de calidad.\n"
        f"Reglas disponibles: {json.dumps(rules, ensure_ascii=False)}"
    )
    steps, evidence = [], {}
    feedback = ""
    for iteration in range(1, max_iters + 1):
        print(f"\n=== ITERACIÓN {iteration}/{max_iters} ===")
        pending = [name for name in by_name if name not in evidence]
        if not pending:
            print("[FASE REPORTE] Ambas herramientas terminaron; redactando el diagnóstico.")
            try:
                recommendations, raw_report = generate_report(llm, evidence, handler, feedback)
            except OutputParserException as exc:
                feedback = "\nCorrección: " + str(exc) + " Devuelve solo JSON con acciones por cada identificador H."
                print("[FORMATO] Se solicitarán nuevamente las recomendaciones; no se repiten herramientas.")
                continue
            return {"estado": "completado", "modelo": getattr(llm, "model", "modelo_prueba"),
                    "iteraciones": iteration, "herramientas_ejecutadas": list(evidence),
                    "evidencia": evidence, "reporte_modelo": raw_report,
                    "recomendaciones_modelo": recommendations,
                    "reporte_final": render_report(evidence, recommendations)}
        try:
            state = "\nEstado de ejecución: faltan resultados correctos de " + ", ".join(pending) + ". Llama a la siguiente herramienta pendiente."
            result = agent.invoke({"input": request + state + feedback, "agent_scratchpad": steps},
                                  config={"callbacks": [handler]})
        except OutputParserException:
            feedback = "\nCorrección: usa exactamente Action + Action Input, o Final Answer. No mezcles ambos formatos."
            print("[FORMATO] Respuesta no interpretable; se solicitará corrección.")
            continue
        if isinstance(result, AgentFinish):
            feedback = "\nAún faltan herramientas con resultado correcto: " + ", ".join(pending)
            print("[CONTROL] Respuesta final prematura; falta evidencia.")
            continue
        if not isinstance(result, AgentAction):
            raise TypeError("El parser no devolvió AgentAction ni AgentFinish.")
        name = result.tool.strip().strip('`"\'')
        if name not in by_name:
            observation = json.dumps({"error": "Herramienta desconocida", "permitidas": list(by_name)})
        elif name in evidence:
            observation = json.dumps({"aviso": "Esta herramienta ya se ejecutó; usa su evidencia y continúa.",
                                      "resultado": evidence[name]}, ensure_ascii=False)
            print(f"[CONTROL] {name}: resultado reutilizado, sin ejecutar de nuevo.")
        else:
            try:
                # invoke, en lugar de .func, dispara los callbacks de herramienta.
                observation = by_name[name].invoke(str(result.tool_input), config={"callbacks": [handler]})
                evidence[name] = json.loads(observation)
                feedback = ""
            except (ValueError, OSError, UnicodeError, csv.Error) as exc:
                observation = json.dumps({"error": str(exc)}, ensure_ascii=False)
        steps.append((result, str(observation)))
    return {"estado": "limite_alcanzado", "iteraciones": max_iters,
            "herramientas_ejecutadas": list(evidence), "evidencia": evidence,
            "reporte_modelo": None, "reporte_final": None,
            "mensaje": "El modelo no completó la auditoría en el límite. La evidencia disponible se conserva; no es una respuesta final exitosa."}


def main():
    load_dotenv(BASE / ".env")
    parser = argparse.ArgumentParser(description="Agente ReAct Data Steward con Ollama")
    parser.add_argument("--csv", type=Path, default=BASE / "clientes_demo.csv")
    parser.add_argument("--rules", type=Path, default=BASE / "reglas_calidad.json")
    parser.add_argument("--model", default=os.getenv("STEWARD_MODEL", "llama3:instruct"))
    parser.add_argument("--max-iters", type=int, default=10)
    parser.add_argument("--output", type=Path, default=BASE / "auditoria_resultado.json")
    parser.add_argument("--verbose", action="store_true", help="Mostrar el prompt completo en cada llamada")
    args = parser.parse_args()
    if args.max_iters < 3:
        parser.error("Usa al menos 3 iteraciones: dos herramientas y una respuesta final.")
    if args.output.resolve() in {args.csv.resolve(), args.rules.resolve(), Path(__file__).resolve(),
                                  BASE / "prompt_data_steward.txt", BASE / "prompt_reporte.txt",
                                  BASE / "callbacks.py", BASE / "steward_tools.py"}:
        parser.error("La salida no puede sobrescribir las entradas ni el código.")
    try:
        rules = load_rules(args.rules)
        print(f"DATA STEWARD BETA | Ollama | {args.model}")
        llm = ChatOllama(model=args.model, temperature=0, num_predict=700,
                         base_url=os.getenv("OLLAMA_HOST", "http://localhost:11434")).bind(stop=["\nObservation:"])
        result = run_audit(llm, args.csv, rules, AgentCallbackHandler(verbose=args.verbose), args.max_iters)
        # RunnableBinding conserva el modelo en .bound; declarar el seleccionado explícitamente.
        result["modelo"] = args.model
        result["proveedor"] = "Ollama local"
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\n=== RESULTADO ===")
        print(result["reporte_final"] or result["mensaje"])
        print("Herramientas ejecutadas:", ", ".join(result["herramientas_ejecutadas"]))
        print("Evidencia y reporte guardados en:", args.output.resolve())
        return 0 if result["estado"] == "completado" else 2
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"No se pudo completar: {exc}")
        return 1
    except Exception as exc:
        print(f"Error de ejecución ({type(exc).__name__}): {exc}")
        print("Comprueba que Ollama esté activo y que el modelo esté descargado.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
