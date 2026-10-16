"""Pruebas offline: herramientas reales + respuestas de modelo SIMULADAS.

No es una ejecución real de LLaMA y no reemplaza la demostración del agente.
Ejecutar desde el entorno del curso: uv run python verificar_beta.py
"""
import importlib.util
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from langchain_core.language_models.fake import FakeListLLM
from callbacks import AgentCallbackHandler
from steward_tools import load_rules, profile_dataset, validate_rules

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("steward_agent", BASE / "agente_data_steward.py")
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)


class CounterHandler(AgentCallbackHandler):
    def __init__(self):
        super().__init__(verbose=False)
        self.starts = []

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.starts.append(serialized["name"])

    def on_tool_end(self, output, **kwargs):
        pass


class BetaChecks(unittest.TestCase):
    def setUp(self):
        self.path = BASE / "clientes_demo.csv"
        self.rules = load_rules(BASE / "reglas_calidad.json")

    def action(self, name):
        return f"Thought: ejecutar herramienta\nAction: {name}\nAction Input: {self.path.as_posix()}"

    def report(self):
        return json.dumps({"acciones": {f"H{i}": "Revisar este caso con el responsable de datos." for i in range(1, 10)}})

    def test_profile(self):
        data = profile_dataset(self.path)
        self.assertEqual((data["filas"], data["columnas"], data["duplicados_completos_excedentes"]), (12, 6, 1))
        self.assertEqual(data["perfil_columnas"]["nombre"]["nulos"], 1)
        self.assertEqual(data["perfil_columnas"]["email"]["nulos"], 1)

    def test_rule_counts_and_no_changes(self):
        before = self.path.read_bytes()
        data = validate_rules(self.path, self.rules)
        counts = {(x["regla"], x["columna"]): x["cantidad"] for x in data["hallazgos"]}
        self.assertEqual(counts, {
            ("valor_obligatorio", "nombre"): 1, ("valor_obligatorio", "email"): 1,
            ("valor_no_unico", "id_cliente"): 4, ("numero_invalido", "edad"): 1,
            ("fuera_de_rango", "edad"): 2, ("fuera_de_catalogo", "pais"): 1,
            ("fecha_invalida", "fecha_alta"): 1, ("formato_email_invalido", "email"): 1,
            ("duplicado_completo_excedente", "*"): 1,
        })
        self.assertEqual(data["filas_con_algun_hallazgo"], 12)
        self.assertEqual(before, self.path.read_bytes())

    def test_missing_column_and_bad_csv(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "prueba.csv"
            path.write_text("id_cliente;nombre\nC1;Demo\n", encoding="utf-8-sig")
            data = validate_rules(path, self.rules)
            self.assertEqual(data["estado"], "incompleto")
            self.assertIn("edad", data["columnas_ausentes"])
            path.write_text("id,id\n1,2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                profile_dataset(path)
            path.write_text("id,nombre\n1,Demo,extra\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                profile_dataset(path)

    def test_model_selects_two_real_tools_and_callbacks(self):
        handler = CounterHandler()
        llm = FakeListLLM(responses=[self.action("perfilar_dataset"), self.action("validar_reglas"),
                                     self.report()])
        result = agent.run_audit(llm, self.path, self.rules, handler)
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(handler.starts, ["perfilar_dataset", "validar_reglas"])
        self.assertEqual(result["evidencia"]["validar_reglas"]["filas_con_algun_hallazgo"], 12)

    def test_clean_data_has_no_findings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "limpio.csv"
            path.write_text("id_cliente,nombre,email,edad,pais,fecha_alta\nC1,Demo,demo@example.com,30,MX,2026-01-10\n", encoding="utf-8")
            result = validate_rules(path, self.rules)
            self.assertEqual(result["estado"], "sin_hallazgos")
            self.assertEqual(result["hallazgos"], [])
            self.assertEqual(result["filas_con_algun_hallazgo"], 0)

    def test_premature_final_parser_recovery_and_repeat(self):
        handler = CounterHandler()
        llm = FakeListLLM(responses=["Final Answer: Prematura", "formato incorrecto",
            self.action("perfilar_dataset"), self.action("perfilar_dataset"),
            self.action("validar_reglas"), self.report()])
        result = agent.run_audit(llm, self.path, self.rules, handler)
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(result["iteraciones"], 6)
        self.assertEqual(handler.starts, ["perfilar_dataset", "validar_reglas"])

    def test_iteration_limit_is_not_success(self):
        result = agent.run_audit(FakeListLLM(responses=["Final Answer: Sin herramientas"]),
                                 self.path, self.rules, CounterHandler(), 3)
        self.assertEqual(result["estado"], "limite_alcanzado")
        self.assertIsNone(result["reporte_modelo"])
        self.assertEqual(result["herramientas_ejecutadas"], [])

    def test_wrong_path_and_unknown_tool(self):
        handler = CounterHandler()
        llm = FakeListLLM(responses=["Action: desconocida\nAction Input: archivo.csv",
            "Action: perfilar_dataset\nAction Input: archivo_inventado.csv",
            self.action("perfilar_dataset"), self.action("validar_reglas"), self.report()])
        result = agent.run_audit(llm, self.path, self.rules, handler)
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(len(result["evidencia"]), 2)

    def test_regression_path_followed_by_model_comment(self):
        handler = CounterHandler()
        # Reproduce el fallo observado: el parser captura el comentario como ruta.
        llm = FakeListLLM(responses=[
            self.action("perfilar_dataset") + "\n\nEspero el resultado...",
            f'Action: validar_reglas\nAction Input: "{self.path.as_posix()}"\n\nEspero el resultado...\nFinal Answer:',
            self.report()])
        result = agent.run_audit(llm, self.path, self.rules, handler)
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(result["iteraciones"], 3)
        self.assertEqual(handler.starts, ["perfilar_dataset", "validar_reglas"])

    def test_dataset_identifier_and_trailing_comment(self):
        handler = CounterHandler()
        llm = FakeListLLM(responses=[
            "Action: perfilar_dataset\nAction Input: dataset_actual\n\nEspero el resultado...",
            'Action: validar_reglas\nAction Input: "dataset_actual"\n\nEspero el resultado...',
            self.report()])
        result = agent.run_audit(llm, self.path, self.rules, handler)
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(result["evidencia"]["perfilar_dataset"]["filas"], 12)

    def test_windows_path_cleanup_preserves_spaces(self):
        path = r"C:\Users\eduar\OneDrive\Documentos\Datos de prueba\clientes_demo.csv"
        self.assertEqual(agent.clean_tool_input(f'"{path}"\n\nEspero el resultado...'), path)
        self.assertEqual(agent.clean_tool_input('```text\ndataset_actual\n```'), "dataset_actual")

    def test_empty_or_mixed_final_is_not_success(self):
        for text in ("Final Answer:", self.action("perfilar_dataset") + "\nFinal Answer: Inventada"):
            with self.assertRaises(agent.OutputParserException):
                agent.parse_response(text)

    def test_regression_final_answer_used_as_action(self):
        handler = CounterHandler()
        llm = FakeListLLM(responses=[self.action("perfilar_dataset"), self.action("validar_reglas"),
            "Thought: Resumen de la auditoría\nAction: Final Answer\nAction Input: dataset_actual",
            self.report()])
        result = agent.run_audit(llm, self.path, self.rules, handler)
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(result["iteraciones"], 4)
        self.assertEqual(handler.starts, ["perfilar_dataset", "validar_reglas"])
        # La última consulta ya no contiene el historial ni el prompt de acciones.
        self.assertEqual(result["reporte_final"].splitlines()[0], "Reporte de calidad de datos")

    def test_report_receives_evidence_without_react_history(self):
        from langchain_core.runnables import RunnableLambda
        calls = []

        def respond(value, **kwargs):
            calls.append(value)
            if len(calls) == 1:
                return self.action("perfilar_dataset")
            if len(calls) == 2:
                return self.action("validar_reglas")
            return self.report()

        result = agent.run_audit(RunnableLambda(respond), self.path, self.rules, CounterHandler())
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(calls[-1][0].type, "system")
        self.assertEqual(calls[-1][1].type, "human")
        self.assertIn('"filas_con_algun_hallazgo": 12', calls[-1][1].content)
        self.assertNotIn("Historial de herramientas:", calls[-1][0].content)

    def test_report_failure_keeps_real_evidence(self):
        handler = CounterHandler()
        llm = FakeListLLM(responses=[self.action("perfilar_dataset"), self.action("validar_reglas"),
            "Action: Final Answer\nAction Input: dataset_actual"])
        result = agent.run_audit(llm, self.path, self.rules, handler, 3)
        self.assertEqual(result["estado"], "limite_alcanzado")
        self.assertIsNone(result["reporte_modelo"])
        self.assertEqual(len(result["evidencia"]), 2)
        self.assertEqual(handler.starts, ["perfilar_dataset", "validar_reglas"])

    def test_report_regression_counts_priorities_and_omitted_age(self):
        llm = FakeListLLM(responses=[self.action("perfilar_dataset"), self.action("validar_reglas"), self.report()])
        result = agent.run_audit(llm, self.path, self.rules, CounterHandler())
        text = result["reporte_final"]
        self.assertIn("Hallazgos verificados: 9 | Alta: 3 | Media: 6", text)
        self.assertIn("H3 | valor_no_unico | id_cliente | 4 | alta", text)
        self.assertIn("H4 | numero_invalido | edad | 1 | media", text)
        self.assertIn("H9 | duplicado_completo_excedente | * | 1 | media", text)
        self.assertEqual(len(result["recomendaciones_modelo"]), 9)

    def test_missing_recommendation_retries_without_repeating_tools(self):
        incomplete = json.loads(self.report())
        del incomplete["acciones"]["H4"]
        handler = CounterHandler()
        llm = FakeListLLM(responses=[self.action("perfilar_dataset"), self.action("validar_reglas"),
                                     json.dumps(incomplete), self.report()])
        result = agent.run_audit(llm, self.path, self.rules, handler)
        self.assertEqual(result["estado"], "completado")
        self.assertEqual(result["iteraciones"], 4)
        self.assertEqual(handler.starts, ["perfilar_dataset", "validar_reglas"])

    def test_model_cannot_override_fact_fields(self):
        invalid = json.loads(self.report())
        invalid["numero_hallazgos"] = 7
        evidence = {"perfilar_dataset": profile_dataset(self.path),
                    "validar_reglas": validate_rules(self.path, self.rules)}
        with self.assertRaises(agent.OutputParserException):
            agent.generate_report(FakeListLLM(responses=[json.dumps(invalid)]), evidence, CounterHandler())

    def test_clean_dataset_report(self):
        evidence = {"perfilar_dataset": {"archivo": "limpio.csv", "filas": 1, "columnas": 1},
                    "validar_reglas": {"hallazgos": [], "estado": "sin_hallazgos",
                                       "filas_con_algun_hallazgo": 0, "columnas_ausentes": []}}
        actions, raw = agent.generate_report(FakeListLLM(responses=['{"acciones": {}}']), evidence, CounterHandler())
        text = agent.render_report(evidence, actions)
        self.assertIn("Hallazgos verificados: 0", text)
        self.assertIn("Sin hallazgos para las reglas comprobadas.", text)


if __name__ == "__main__":
    print("VERIFICACIÓN OFFLINE: respuestas del modelo simuladas, herramientas reales.")
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main(verbosity=2)
