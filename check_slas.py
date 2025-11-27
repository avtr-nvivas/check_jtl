#!/usr/bin/env python3
import argparse
import csv
import sys
import os
import json
from datetime import datetime
from typing import Optional

# =========================================================
# === Definición de Umbrales (SLAs) ===
# =========================================================
MAX_ERROR_RATE_TOTAL = 1.0   # %
MAX_AVG_LATENCY      = 3000  # ms
MIN_TPS              = 5     # tps

def safe_int(v, default=0) -> int:
    try:
        if v is None:
            return default
        s = str(v).strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default

def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def check_slas(
    jtl_file: str,
    threads: int,
    rampup: int,
    duration: int,
    test_name: str,
    repo: str,
    jmx: str,
    out_path: str,
) -> int:
    """Procesa el archivo JTL, verifica los SLAs y genera summary.json."""
    total_samples   = 0
    total_errors    = 0
    total_latency   = 0

    min_start_time  = float('inf')
    max_end_time    = float('-inf')

    http_500        = 0
    latencies_ms    = []

    try:
        with open(jtl_file, 'r', newline='', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)

            for row in reader:
                success       = row.get('success', 'false')
                elapsed       = safe_int(row.get('elapsed', 0), 0)
                timestamp     = safe_int(row.get('timeStamp', 0), 0)
                response_code = (row.get('responseCode', '') or '').strip()

                total_samples += 1
                total_latency += elapsed
                latencies_ms.append(elapsed)

                current_start_time = timestamp
                current_end_time   = timestamp + elapsed

                if current_start_time < min_start_time:
                    min_start_time = current_start_time
                if current_end_time > max_end_time:
                    max_end_time = current_end_time

                if str(success).lower() != 'true':
                    total_errors += 1

                if response_code.startswith('5'):
                    http_500 += 1

    except FileNotFoundError:
        print(f"ERROR: Archivo de resultados {jtl_file} no encontrado.")
        return 1

    if total_samples == 0:
        print("ERROR: No se encontraron muestras en el archivo JTL.")
        return 1

    # =========================
    # Métricas
    # =========================
    error_rate = (total_errors / total_samples) * 100.0
    avg_latency = total_latency / total_samples

    total_duration_ms = max_end_time - min_start_time
    total_duration_s  = total_duration_ms / 1000.0 if total_duration_ms > 0 else 0.0
    tps = total_samples / total_duration_s if total_duration_s > 0 else 0.0

    latencies_ms_sorted = sorted(latencies_ms)
    n = len(latencies_ms_sorted)

    def percentile(p: float) -> float:
        if n == 0:
            return 0.0
        idx = int(round(p * (n - 1)))
        return float(latencies_ms_sorted[idx])

    p90 = percentile(0.90)
    p95 = percentile(0.95)

    samples_ok = total_samples - total_errors
    samples_ko = total_errors

    # =========================
    # Evaluación de SLAs
    # =========================
    slas_passed = True
    sla_reasons = []

    if http_500 > 0:
        slas_passed = False
        sla_reasons.append(f"Se detectaron {http_500} respuestas HTTP 5xx (no se permiten).")
    else:
        sla_reasons.append("Sin respuestas HTTP 5xx (OK).")

    if error_rate > MAX_ERROR_RATE_TOTAL:
        slas_passed = False
        sla_reasons.append(f"Tasa de error global {error_rate:.2f}% > límite {MAX_ERROR_RATE_TOTAL:.2f}%.")
    else:
        sla_reasons.append(f"Tasa de error global {error_rate:.2f}% ≤ límite {MAX_ERROR_RATE_TOTAL:.2f}% (OK).")

    if avg_latency > MAX_AVG_LATENCY:
        slas_passed = False
        sla_reasons.append(f"Latencia promedio {avg_latency:.2f} ms > límite {MAX_AVG_LATENCY} ms.")
    else:
        sla_reasons.append(f"Latencia promedio {avg_latency:.2f} ms ≤ límite {MAX_AVG_LATENCY} ms (OK).")

    if tps < MIN_TPS:
        slas_passed = False
        sla_reasons.append(f"TPS {tps:.2f} < mínimo requerido {MIN_TPS}.")
    else:
        sla_reasons.append(f"TPS {tps:.2f} ≥ mínimo requerido {MIN_TPS} (OK).")

    # =========================
    # summary.json
    # =========================
    summary = {
        "test_name": test_name,
        "timestamp": utc_now_iso(),

        "threads": int(threads),
        "rampup": int(rampup),
        "duration": int(duration),

        "repo": (repo or "").strip(),
        "jmx": (jmx or "").strip(),

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
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"OK: {out_path} generado. threads={threads}, rampup={rampup}, duration={duration}")
    except Exception as e:
        print(f"ERROR al escribir {out_path}: {e}")
        return 1

    return 0 if slas_passed else 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("jtl_file")

    parser.add_argument("--threads",  type=str, default=os.getenv("THREADS", "0"))
    parser.add_argument("--rampup",   type=str, default=os.getenv("RAMP_UP", "0"))
    parser.add_argument("--duration", type=str, default=os.getenv("DURATION", "0"))

    parser.add_argument("--repo", type=str, default=os.getenv("JMX_URL", ""))
    parser.add_argument("--jmx",  type=str, default=os.getenv("JMX_FILE", ""))
    parser.add_argument("--out",  type=str, default="summary.json")
    parser.add_argument("--test-name", type=str, default=os.getenv("TEST_NAME", ""))

    args = parser.parse_args()

    test_name = (args.test_name or os.path.basename(args.jtl_file)).strip()
    exit_code = check_slas(
        jtl_file=args.jtl_file,
        threads=safe_int(args.threads, 0),
        rampup=safe_int(args.rampup, 0),
        duration=safe_int(args.duration, 0),
        test_name=test_name,
        repo=args.repo,
        jmx=args.jmx,
        out_path=args.out,
    )
    sys.exit(exit_code)
