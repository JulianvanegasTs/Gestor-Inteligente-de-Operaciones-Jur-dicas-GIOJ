# Arquitectura del Sistema

## Alcance operativo del MVP

La persona analista selecciona desde la interfaz los archivos que desea
analizar, sin importar la carpeta del computador donde se encuentren. El
sistema recibe esos archivos temporalmente en memoria y no crea copias, no los
mueve y no modifica los originales.

El límite total de la selección se define en `config.json` mediante
`mvp.tamano_maximo_seleccion_mb`; la interfaz debe consultarlo y mostrar un
mensaje de tamaño explícito antes de transmitir una selección que lo exceda.

Los resultados derivados y la trazabilidad sí se guardan bajo `Salida/` con el
identificador temporal de la selección. La barra de estado debe acompañar las
fases de OCR, clasificación, extracción, normalización, validación y concepto.

Los casos ubicados fuera del proyecto, incluidos los de `GIOJ_PRUEBAS`, son
material de consulta. No son una ruta configurada ni una entrada del motor de
análisis.

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

---

# Requisito permanente de interfaz

La interfaz oficial debe mantener una barra de estado sencilla, ubicada debajo
del botón **Iniciar análisis** y visible mientras se ejecuta el flujo. Debe
mostrar la etapa actual, el porcentaje y el progreso accesible mediante
`role="progressbar"` y `aria-valuenow`.

Este control visual no modifica el motor jurídico ni las reglas de
`Arquitectura.xlsx`, pero es obligatorio para todos los ciclos de integración
de la interfaz. No debe eliminarse ni trasladarse a un área que pueda quedar
oculta durante el análisis.
