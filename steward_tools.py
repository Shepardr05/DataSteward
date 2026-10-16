"""Herramientas deterministas de calidad de datos; solo biblioteca estándar."""
import csv
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

NULLS = {"", "null", "none", "nan", "n/a"}


def missing(value):
    return value.strip().lower() in NULLS


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def read_csv(path):
    path = Path(path)
    if path.suffix.lower() != ".csv":
        raise ValueError("La entrada debe ser un archivo CSV.")
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Esta beta acepta archivos de hasta 10 MiB.")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(8192)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(handle, dialect, strict=True)
        columns = next(reader, [])
        columns = [c.strip() for c in columns]
        if not columns or any(not c for c in columns):
            raise ValueError("El CSV debe tener encabezados no vacíos.")
        if len(columns) != len(set(columns)):
            raise ValueError("Hay encabezados duplicados.")
        rows = []
        for record_index, values in enumerate(reader, 2):
            if len(values) != len(columns):
                raise ValueError(f"Registro {record_index}: número de campos incorrecto.")
            if len(rows) >= 100_000:
                raise ValueError("Esta beta acepta hasta 100000 registros.")
            rows.append(dict(zip(columns, values)))
    return columns, rows


def profile_dataset(path):
    columns, rows = read_csv(path)
    counts = Counter(tuple(row[c] for c in columns) for row in rows)
    details = {}
    for column in columns:
        present = [row[column].strip() for row in rows if not missing(row[column])]
        nums = [number(value) for value in present]
        kind = "sin_datos"
        if present:
            kind = "texto"
            if all(value is not None for value in nums):
                kind = "entero_aparente" if all(v.is_integer() for v in nums) else "numerico_aparente"
        details[column] = {
            "nulos": len(rows) - len(present),
            "valores_distintos_no_nulos": len(set(present)),
            "tipo_aparente": kind,
        }
    return {
        "archivo": Path(path).name,
        "filas": len(rows),
        "columnas": len(columns),
        "duplicados_completos_excedentes": sum(n - 1 for n in counts.values()),
        "perfil_columnas": details,
        "nota": "Tipos inferidos, no esquema de negocio. Nulos: vacío, null, none, nan y n/a. No se altera el CSV.",
    }


def load_rules(path):
    rules = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    allowed = {"required_columns", "unique_columns", "numeric_ranges", "allowed_values", "date_formats", "email_columns"}
    if not isinstance(rules, dict) or set(rules) - allowed:
        raise ValueError("Reglas inválidas: se esperaba un objeto con claves soportadas.")
    for key in ("required_columns", "unique_columns", "email_columns"):
        values = rules.get(key, [])
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError(f"{key} debe ser una lista de columnas.")
    for key in ("numeric_ranges", "allowed_values", "date_formats"):
        if not isinstance(rules.get(key, {}), dict):
            raise ValueError(f"{key} debe ser un objeto.")
    for column, bounds in rules.get("numeric_ranges", {}).items():
        if not isinstance(bounds, dict) or set(bounds) - {"min", "max"}:
            raise ValueError(f"Rango inválido para {column}.")
        for value in bounds.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Límite no numérico en {column}.")
        if bounds.get("min", -math.inf) > bounds.get("max", math.inf):
            raise ValueError(f"Rango invertido en {column}.")
    for column, values in rules.get("allowed_values", {}).items():
        if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
            raise ValueError(f"Dominio inválido para {column}.")
    if any(not isinstance(v, str) or not v for v in rules.get("date_formats", {}).values()):
        raise ValueError("Los formatos de fecha deben ser cadenas no vacías.")
    return rules


def validate_rules(path, rules):
    columns, rows = read_csv(path)
    issues = []
    affected = set()

    def add(rule, column, indices, priority="media"):
        if indices:
            affected.update(indices)
            issues.append({"regla": rule, "columna": column, "prioridad": priority,
                           "cantidad": len(indices), "registros_ejemplo": indices[:10]})

    referenced = set()
    for key in ("required_columns", "unique_columns", "email_columns"):
        referenced.update(rules.get(key, []))
    for key in ("numeric_ranges", "allowed_values", "date_formats"):
        referenced.update(rules.get(key, {}))
    absent = sorted(referenced - set(columns))
    for column in absent:
        issues.append({"regla": "columna_ausente", "columna": column, "prioridad": "alta",
                       "cantidad": None, "registros_ejemplo": []})
    for column in rules.get("required_columns", []):
        if column in columns:
            add("valor_obligatorio", column, [i for i, r in enumerate(rows, 2) if missing(r[column])], "alta")
    for column in rules.get("unique_columns", []):
        if column not in columns:
            continue
        counts = Counter(r[column].strip() for r in rows if not missing(r[column]))
        add("valor_no_unico", column,
            [i for i, r in enumerate(rows, 2) if not missing(r[column]) and counts[r[column].strip()] > 1], "alta")
    for column, bounds in rules.get("numeric_ranges", {}).items():
        if column not in columns:
            continue
        nonnumeric, outside = [], []
        for i, row in enumerate(rows, 2):
            if missing(row[column]):
                continue
            value = number(row[column])
            if value is None:
                nonnumeric.append(i)
            elif not bounds.get("min", -math.inf) <= value <= bounds.get("max", math.inf):
                outside.append(i)
        add("numero_invalido", column, nonnumeric)
        add("fuera_de_rango", column, outside)
    for column, allowed in rules.get("allowed_values", {}).items():
        if column in columns:
            add("fuera_de_catalogo", column, [i for i, r in enumerate(rows, 2)
                if not missing(r[column]) and r[column].strip() not in allowed])
    for column, fmt in rules.get("date_formats", {}).items():
        if column not in columns:
            continue
        invalid = []
        for i, row in enumerate(rows, 2):
            if missing(row[column]):
                continue
            try:
                datetime.strptime(row[column].strip(), fmt)
            except ValueError:
                invalid.append(i)
        add("fecha_invalida", column, invalid)
    for column in rules.get("email_columns", []):
        if column in columns:
            add("formato_email_invalido", column, [i for i, r in enumerate(rows, 2)
                if not missing(r[column]) and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", r[column].strip())])
    seen = set()
    duplicates = []
    for i, row in enumerate(rows, 2):
        key = tuple(row[c] for c in columns)
        if key in seen:
            duplicates.append(i)
        seen.add(key)
    add("duplicado_completo_excedente", "*", duplicates)
    return {
        "archivo": Path(path).name, "filas": len(rows),
        "estado": "incompleto" if absent else ("con_hallazgos" if issues else "sin_hallazgos"),
        "reglas_aplicadas": rules, "hallazgos": issues,
        "filas_con_algun_hallazgo": len(affected),
        "columnas_ausentes": absent,
        "nota": "Índices de registros lógicos: encabezado=1. No sumar conteos de reglas: pueden solaparse. Unicidad marca todas las apariciones; duplicado completo solo las excedentes. Email: formato básico, no existencia. Sin hallazgos no garantiza calidad total.",
    }
