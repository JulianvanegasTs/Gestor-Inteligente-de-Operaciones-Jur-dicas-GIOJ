# Arquitectura del Sistema

Esta carpeta contiene toda la configuración funcional del proyecto.

El sistema obtiene desde estos archivos todas las reglas necesarias para ejecutar el análisis.

No deben programarse reglas jurídicas directamente en el código.

Toda modificación funcional debe realizarse desde Arquitectura.xlsx.

---

# Archivos

Arquitectura.xlsx

Contiene:

- Campos de extracción
- Catálogos
- Reglas jurídicas
- Flujo del analista
- Motor de extracción
- Salidas
- Trazabilidad
- Marcadores
- Formateadores

config.json

Contiene parámetros generales del sistema.

---

# Objetivo

Separar completamente la lógica jurídica del código fuente.

El programa únicamente interpreta esta arquitectura.

Nunca debe modificarla.