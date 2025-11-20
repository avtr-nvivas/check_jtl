#!/usr/bin/env python3
import csv
import sys

# =========================================================
# === Definición de Umbrales (SLAs) ===
# =========================================================
# Umbrales Generales
MAX_ERROR_RATE_TOTAL = 1.0  # Máximo 1.0% de errores globales (original)
MAX_AVG_LATENCY = 3000      # Máximo 3000 ms (3 segundos) de tiempo de respuesta promedio (Nuevo Requisito)

# Umbrales Específicos
MIN_TPS = 5                 # Mínimo 5 Transacciones por Segundo (Nuevo Requisito)
# No se permite NINGÚN error 5xx (Manejado con una bandera booleana)
# =========================================================


def check_slas(jtl_file):
    """Procesa el archivo JTL y verifica los SLAs."""
    
    total_samples = 0
    total_errors = 0
    total_latency = 0
    
    # Para el cálculo de TPS
    min_start_time = float('inf')
    max_end_time = float('-inf')
    
    # Para la detección de errores 5xx
    found_5xx_error = False
    
    try:
        with open(jtl_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                # Extracción de campos
                success = row.get('success', 'false')
                elapsed = int(row.get('elapsed', 0))
                timestamp = int(row.get('timeStamp', 0))
                response_code = row.get('responseCode', '')

                total_samples += 1
                total_latency += elapsed
                
                # Rastreo de Tiempos para TPS
                current_start_time = timestamp
                current_end_time = timestamp + elapsed
                
                if current_start_time < min_start_time:
                    min_start_time = current_start_time
                if current_end_time > max_end_time:
                    max_end_time = current_end_time
                
                # Detección de Errores
                if success.lower() != 'true':
                    total_errors += 1
                
                # Detección específica de error 5xx
                if response_code.startswith('5'):
                    found_5xx_error = True
                    
    except FileNotFoundError:
        print(f"ERROR: Archivo de resultados {jtl_file} no encontrado.")
        sys.exit(1)

    if total_samples == 0:
        print("ERROR: No se encontraron muestras en el archivo JTL.")
        sys.exit(1)
        
    # =========================================================
    # CÁLCULO DE MÉTRICAS FINALES
    # =========================================================
    error_rate = (total_errors / total_samples) * 100
    avg_latency = total_latency / total_samples
    
    # Cálculo de TPS: (duración total en ms / 1000)
    total_duration_ms = max_end_time - min_start_time
    total_duration_s = total_duration_ms / 1000.0 if total_duration_ms > 0 else 0
    
    tps = total_samples / total_duration_s if total_duration_s > 0 else 0

    print("\n--- Resultados de Rendimiento ---")
    print(f"Muestras Totales: {total_samples}")
    print(f"Duración Total de la Prueba: {total_duration_s:.2f} s")
    print(f"Tasa de Error Global: {error_rate:.2f}% (Máx SLA: {MAX_ERROR_RATE_TOTAL}%)")
    print(f"Latencia Promedio: {avg_latency:.2f} ms (Máx SLA: {MAX_AVG_LATENCY} ms)")
    print(f"Transacciones por Segundo (TPS): {tps:.2f} tps (Mín SLA: {MIN_TPS} tps)")
    print("---------------------------------\n")

    # =========================================================
    # EVALUACIÓN DE SLAs
    # =========================================================
    slas_passed = True
    
    # 1. Error 5xx (Requisito Crítico)
    if found_5xx_error:
        print("❌ FALLO DE SLA CRÍTICO: Se detectaron errores con código de respuesta 5xx.")
        slas_passed = False
        
    # 2. Tasa de Error Global (Métrica de Calidad)
    if error_rate > MAX_ERROR_RATE_TOTAL:
        print(f"❌ FALLO DE SLA: La Tasa de Error Global ({error_rate:.2f}%) excede el límite de {MAX_ERROR_RATE_TOTAL}%.")
        slas_passed = False
        
    # 3. Latencia Promedio Máxima (Requisito: 3 segundos)
    if avg_latency > MAX_AVG_LATENCY:
        print(f"❌ FALLO DE SLA: La Latencia Promedio ({avg_latency:.2f} ms) excede el límite de {MAX_AVG_LATENCY} ms.")
        slas_passed = False
        
    # 4. TPS Mínimo (Requisito: 5 TPS)
    if tps < MIN_TPS:
        print(f"❌ FALLO DE SLA: El TPS ({tps:.2f}) es menor al mínimo requerido de {MIN_TPS}.")
        slas_passed = False
        
    
    if slas_passed:
        print("✅ VALIDACIÓN DE SLA EXITOSA. Todas las métricas cumplen los umbrales.")
        sys.exit(0) # Salida con éxito
    else:
        print("🚨 FALLO EN LA VALIDACIÓN DE SLA. Uno o más umbrales no se cumplieron.")
        sys.exit(1) # Salida con error para fallar el build de Jenkins

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python check_slas.py <archivo_jtl>")
        sys.exit(1)
        
    check_slas(sys.argv[1])