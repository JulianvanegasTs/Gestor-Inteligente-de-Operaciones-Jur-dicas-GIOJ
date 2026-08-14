# BACKLOG.md

# Backlog de Desarrollo
## Gestor Inteligente de Operaciones Jurídicas (GIOJ)

---

# Objetivo

Este documento convierte la hoja de ruta del proyecto definida en ROADMAP.md en tareas concretas de desarrollo.

Cada tarea representa una unidad funcional independiente que puede ser implementada, probada y validada antes de continuar con la siguiente.

El desarrollo deberá ejecutarse siguiendo estrictamente el orden establecido.

---

# Reglas de implementación

Antes de iniciar cualquier tarea:

1. Leer completamente:

- AGENTS.md
- PROJECT.md
- MVP.md
- ROADMAP.md
- Arquitectura.xlsx

2. No modificar:

- Arquitectura.xlsx
- Plantillas Word

3. No programar reglas jurídicas directamente en código.

4. No avanzar a la siguiente tarea hasta que la anterior cumpla sus criterios de aceptación.

---

# GIOJ-001
# Inicialización del proyecto

Relacionado con:

ROADMAP - FASE 0

## Objetivo

Crear la estructura base del programa y preparar el entorno de ejecución.

## Entrada

Archivos:

- Arquitectura/config.json
- Arquitectura/Arquitectura.xlsx

## Desarrollo requerido

Crear:

- Estructura interna del programa.
- Configuración inicial.
- Manejo básico de rutas.
- Sistema inicial de logs.
- Validación de archivos obligatorios.

## Salida esperada

El sistema inicia correctamente y reconoce la configuración del proyecto.

## Criterios de aceptación

□ El programa inicia sin errores.

□ Detecta archivos de configuración.

□ Valida existencia de Arquitectura.xlsx.

□ Genera estructura temporal necesaria.

---

# GIOJ-002
# Integración de la interfaz HTML

Relacionado con:

ROADMAP - FASE 1

## Objetivo

Conectar la interfaz HTML existente con el programa.

## Entrada

Archivo:

Interfaz HTML existente.

## Desarrollo requerido

Implementar:

- Botón Nuevo Proyecto.
- Selección de carpeta.
- Botón Analizar.
- Botón Generar Documento.

Mantener el diseño existente.

## Salida esperada

La interfaz permite iniciar un análisis.

## Criterios de aceptación

□ La interfaz abre correctamente.

□ Los botones ejecutan acciones.

□ No se modifica el diseño original.

---

# GIOJ-003
# Lectura del expediente

Relacionado con:

ROADMAP - FASE 2

## Objetivo

Permitir seleccionar y leer una carpeta de expediente.

## Entrada

Carpeta:

Expedientes/{id_expediente}/01_Documentos/

## Desarrollo requerido

Detectar:

- PDFs.
- Imágenes.
- Documentos relacionados.

Crear objeto interno Expediente.

## Salida esperada

Expediente cargado correctamente.

## Criterios de aceptación

□ Identifica todos los archivos.

□ Conserva nombre y ubicación original.

□ Genera estructura interna del expediente.

---

# GIOJ-004
# OCR documental

Relacionado con:

ROADMAP - FASE 3

## Objetivo

Extraer texto de los documentos.

## Entrada

Documentos del expediente.

## Desarrollo requerido

Procesar:

- PDF digital.
- PDF escaneado.
- Imágenes.

Mantener relación:

Documento → Texto → Página.

## Salida esperada

Texto extraído por documento.

## Criterios de aceptación

□ Todos los documentos generan texto.

□ Conserva referencia de páginas.

□ Los errores quedan registrados.

---

# GIOJ-005
# Clasificación documental

Relacionado con:

ROADMAP - FASE 4

## Objetivo

Identificar automáticamente el tipo documental.

## Entrada

Texto extraído.

## Documentos esperados

- Escritura objeto.
- Escritura antecedente.
- Certificado de tradición.
- Promesa de compraventa.
- Poder.
- Documento identidad.
- Reglamento PH.
- Minuta.
- Otro Sí.

## Desarrollo requerido

Asignar:

Documento → Tipo documental.

## Salida esperada

Expediente clasificado.

## Criterios de aceptación

□ Cada documento tiene clasificación.

□ Los documentos no identificados quedan marcados.

---

# GIOJ-006
# Motor de extracción documental

Relacionado con:

ROADMAP - FASE 5

## Objetivo

Extraer información jurídica utilizando la arquitectura definida.

## Entrada

Archivos:

- 01_Campos_Extraccion
- 05_Extraccion_Documental

## Desarrollo requerido

Extraer:

- Personas.
- Inmuebles.
- Créditos.
- Escrituras.
- Poderes.
- Datos jurídicos.

No crear campos manuales.

## Salida esperada

JSON estructurado del expediente.

## Criterios de aceptación

□ Los campos provienen de Arquitectura.xlsx.

□ Cada dato tiene origen documental.

□ Existe trazabilidad del dato extraído.

---

# GIOJ-007
# Normalización de datos

Relacionado con:

ROADMAP - FASE 6

## Objetivo

Preparar los datos para comparación.

## Entrada

Datos extraídos.

## Desarrollo requerido

Normalizar:

- Fechas.
- Monedas.
- Identificaciones.
- Notarías.
- Estados civiles.

Nunca eliminar el valor original.

## Salida esperada

Datos normalizados.

## Criterios de aceptación

□ Conserva valor original.

□ Permite comparación automática.

---

# GIOJ-008
# Validación documental

Relacionado con:

ROADMAP - FASE 7

## Objetivo

Comparar información entre documentos.

## Entrada

Datos normalizados.

## Desarrollo requerido

Comparar:

Documento origen.

Documento destino.

Campo.

Valor esperado.

Valor encontrado.

## Salida esperada

Resultado:

- Cumple.
- No cumple.
- No existe información.
- No aplica.

## Criterios de aceptación

□ Cada comparación queda registrada.

□ Las diferencias son identificables.

---

# GIOJ-009
# Motor jurídico

Relacionado con:

ROADMAP - FASE 8

## Objetivo

Aplicar reglas jurídicas.

## Entrada

Archivo:

04_Reglas_Negocio

## Desarrollo requerido

Ejecutar todas las reglas definidas.

No programar reglas manualmente.

## Salida esperada

Resultado jurídico del expediente.

## Criterios de aceptación

□ Todas las reglas son leídas desde Excel.

□ Cada regla tiene resultado.

---

# GIOJ-010
# Trazabilidad completa

Relacionado con:

ROADMAP - FASE 9

## Objetivo

Registrar evidencia del análisis.

## Entrada

Resultados de validaciones.

## Desarrollo requerido

Registrar:

- Documento.
- Página.
- Campo.
- Valor encontrado.
- Valor esperado.
- Resultado.
- Observación.

## Salida esperada

Reporte de trazabilidad.

## Criterios de aceptación

☑ Cada incumplimiento tiene evidencia.

☑ El analista puede ubicar el error.

---

# GIOJ-011
# Generación del concepto jurídico

Relacionado con:

ROADMAP - FASE 10

## Objetivo

Generar resumen ejecutivo del análisis.

## Entrada

Resultados jurídicos.

## Desarrollo requerido

Generar:

- Concepto favorable.
- Concepto no favorable.
- Resumen de observaciones.

## Salida esperada

Concepto jurídico.

## Criterios de aceptación

☑ Diferencia correctamente conformidad y no conformidad.

☑ No reemplaza decisión del analista.

---

# GIOJ-012
# Generación del documento Word

Relacionado con:

ROADMAP - FASE 11

## Objetivo

Completar las plantillas oficiales.

## Entrada

Plantillas:

- Certificado_Conformidad.docx
- Certificado_No_Conformidad.docx

## Desarrollo requerido

Reemplazar únicamente marcadores.

## Salida esperada

Documento Word generado.

## Criterios de aceptación

☑ Conserva formato original.

☑ Todos los marcadores son reemplazados.

---

# GIOJ-013
# Conversión PDF

Relacionado con:

ROADMAP - FASE 12

## Objetivo

Generar PDF final.

## Entrada

Documento Word.

## Salida esperada

PDF listo para entrega.

## Criterios de aceptación

☑ PDF generado correctamente.

☑ Mantiene formato documental.

---

# GIOJ-014
# Validación completa del MVP

## Objetivo

Realizar prueba integral del sistema.

## Entrada

Expediente real de prueba.

## Desarrollo requerido

Ejecutar flujo completo:

Expediente

↓

OCR

↓

Extracción

↓

Validación

↓

Concepto

↓

Documento

↓

PDF

## Criterios de aceptación

☑ El sistema completa un análisis completo.

☑ Genera certificado correcto.

☑ Mantiene trazabilidad.

☑ No requiere intervención técnica.
