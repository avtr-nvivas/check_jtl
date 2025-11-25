#!/usr/bin/env python3
import argparse
import csv
import sys
import os
import json
from datetime import datetime

# =========================================================
# === Definición de Umbrales (SLAs) ===
# =========================================================
# Umbrales Generales
MAX_ERROR_RATE_TOTAL = 1.0   # Máximo 1.0% de errores globales
MAX_AVG_LATENCY      = 3000  # Máximo 3000 ms (3 segundos) de tiempo de respuesta promedio

# Umbrales Específicos
MIN_TPS              = 5     # Mínimo 5 Transacciones por Segundo

# =========================================================
# === Función principal de chequeo de SLAs ===
# =========================================================

def check_slas(jtl_file: str) -> None:
    """Procesa el archivo JTL, verifica los SLAs y genera summary.json."""

    total_samples   = 0
    total_errors    = 0
    total_latency   = 0

    # Para TPS
    min_start_time  = float('inf')
    max_end_time    = float('-inf')

    # Para métricas adicionales
    http_500        = 0
    latencies_ms    = []  # para percentiles

    try:
        with open(jtl_file, 'r', newline='', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)

            for row in reader:
                success       = row.get('success', 'false')
                elapsed       = int(row.get('elapsed', 0))
                timestamp     = int(row.get('timeStamp', 0))
                response_code = row.get('responseCode', '')

                total_samples += 1
                total_latency += elapsed
                latencies_ms.append(elapsed)

                # Tiempos para TPS
                current_start_time = timestamp
                current_end_time   = timestamp + elapsed

                if current_start_time < min_start_time:
                    min_start_time = current_start_time
                if current_end_time > max_end_time:
                    max_end_time = current_end_time

                # Errores (success != true)
                if success.lower() != 'true':
                    total_errors += 1

                # Errores HTTP 5xx
                if response_code.startswith('5'):
                    http_500 += 1

    except FileNotFoundError:
        print(f"ERROR: Archivo de resultados {jtl_file} no encontrado.")
        sys.exit(1)

    if total_samples == 0:
        print("ERROR: No se encontraron muestras en el archivo JTL.")
        sys.exit(1)

    # =========================================================
    # CÁLCULO DE MÉTRICAS FINALES
    # =========================================================

    error_rate = (total_errors / total_samples) * 100.0
    avg_latency = total_latency / total_samples

    # TPS: duración total en ms → s
    total_duration_ms = max_end_time - min_start_time
    total_duration_s  = total_duration_ms / 1000.0 if total_duration_ms > 0 else 0.0
    tps = total_samples / total_duration_s if total_duration_s > 0 else 0.0

    # Percentiles (p90 / p95)
    latencies_ms_sorted = sorted(latencies_ms)
    n = len(latencies_ms_sorted)

    def percentile(p: float) -> float:
        """Calcula el percentil p (0.0–1.0) de la lista de latencias."""
        if n == 0:
            return 0.0
        idx = int(round(p * (n - 1)))
        return float(latencies_ms_sorted[idx])

    p90 = percentile(0.90)
    p95 = percentile(0.95)

    samples_ok = total_samples - total_errors
    samples_ko = total_errors

    # =========================================================
    # EVALUACIÓN DE SLAs
    # =========================================================

    slas_passed = True
    sla_reasons = []

    # 1. Errores 5xx
    if http_500 > 0:
        slas_passed = False
        sla_reasons.append(
            f"Se detectaron {http_500} respuestas HTTP 5xx (no se permiten)."
        )
    else:
        sla_reasons.append("Sin respuestas HTTP 5xx (OK).")

    # 2. Tasa de error global
    if error_rate > MAX_ERROR_RATE_TOTAL:
        slas_passed = False
        sla_reasons.append(
            f"Tasa de error global {error_rate:.2f}% > límite {MAX_ERROR_RATE_TOTAL:.2f}%."
        )
    else:
        sla_reasons.append(
            f"Tasa de error global {error_rate:.2f}% ≤ límite {MAX_ERROR_RATE_TOTAL:.2f}% (OK)."
        )

    # 3. Latencia promedio
    if avg_latency > MAX_AVG_LATENCY:
        slas_passed = False
        sla_reasons.append(
            f"Latencia promedio {avg_latency:.2f} ms > límite {MAX_AVG_LATENCY} ms."
        )
    else:
        sla_reasons.append(
            f"Latencia promedio {avg_latency:.2f} ms ≤ límite {MAX_AVG_LATENCY} ms (OK)."
        )

    # 4. TPS mínimo
    if tps < MIN_TPS:
        slas_passed = False
        sla_reasons.append(
            f"TPS {tps:.2f} < mínimo requerido {MIN_TPS}."
        )
    else:
        sla_reasons.append(
            f"TPS {tps:.2f} ≥ mínimo requerido {MIN_TPS} (OK)."
        )

    # =========================================================
    # RESUMEN EN CONSOLA
    # =========================================================
    print("\n--- Resultados de Rendimiento ---")
    print(f"Muestras Totales       : {total_samples}")
    print(f"Muestras OK / KO       : {samples_ok} / {samples_ko}")
    print(f"Duración Total Prueba  : {total_duration_s:.2f} s")
    print(f"Tasa de Error Global   : {error_rate:.2f}% (Máx SLA: {MAX_ERROR_RATE_TOTAL}%)")
    print(f"Latencia Promedio      : {avg_latency:.2f} ms (Máx SLA: {MAX_AVG_LATENCY} ms)")
    print(f"Transacciones por Seg. : {tps:.2f} tps (Mín SLA: {MIN_TPS} tps)")
    print(f"Percentiles Latencia   : p90={p90:.2f} ms, p95={p95:.2f} ms")
    print(f"HTTP 5xx               : {http_500}")
    print("---------------------------------\n")

    if slas_passed:
        print("✅ VALIDACIÓN DE SLA EXITOSA. Todas las métricas cumplen los umbrales.")
    else:
        print("🚨 FALLO EN LA VALIDACIÓN DE SLA. Uno o más umbrales no se cumplieron.")

    print("\n--- Detalle Evaluación SLA ---")
    for r in sla_reasons:
        print(f"- {r}")
    print("---------------------------------\n")

    # =========================================================
    # GENERACIÓN DE summary.json
    # =========================================================

    # Datos de contexto (pueden venir desde Jenkins por variables de entorno)
    test_name = os.environ.get("TEST_NAME") or os.path.basename(jtl_file)
    threads   = int(os.environ.get("THREADS", "0") or 0)
    rampup    = int(os.environ.get("RAMP_UP", "0") or 0)
    duration  = int(os.environ.get("DURATION", "0") or 0)

    summary = {
        "test_name": test_name,
        "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",

        "threads": threads,
        "rampup": rampup,
        "duration": duration,

        "samples_total": total_samples,
        "samples_ok": samples_ok,
        "samples_ko": samples_ko,
        "http_500": http_500,
        "error_pct": round(error_rate, 2),

        "tps": round(tps, 2),
        "avg_rt_ms": round(avg_latency, 2),
        "p90_rt_ms": round(p90, 2),
        "p95_rt_ms": round(p95, 2),

        "sla_min_tps": MIN_TPS,
        "sla_max_error_pct": MAX_ERROR_RATE_TOTAL,
        "sla_max_avg_latency_ms": MAX_AVG_LATENCY,

        "sla_passed": slas_passed,
        "sla_reasons": sla_reasons,
    }

    try:
        with open("summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print("summary.json generado correctamente.")
    except Exception as e:
        print(f"ERROR al escribir summary.json: {e}")

    # =========================================================
    # CÓDIGO DE SALIDA (para Jenkins)
    # =========================================================
    sys.exit(0 if slas_passed else 1)


# =========================================================
# === Punto de entrada ===
# =========================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("jtl_file")
    parser.add_argument("--threads",  type=str, default=os.getenv("THREADS", "0"))
    parser.add_argument("--rampup",   type=str, default=os.getenv("RAMP_UP", "0"))
    parser.add_argument("--duration", type=str, default=os.getenv("DURATION", "0"))
    args = parser.parse_args()

    # Si tu script ya genera summary.json, usa args.threads/args.rampup/args.duration
    # cuando armes el JSON. Ej:
    # summary["threads"] = float(args.threads) si viene numérico o déjalo string.
    # summary["rampup"] = float(args.rampup)
    # summary["duration"] = float(args.duration)

    check_slas(args.jtl_file)

