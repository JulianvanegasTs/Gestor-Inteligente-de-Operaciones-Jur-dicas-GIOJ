# AGENTS.md
# Gestor Inteligente de Operaciones Jurídicas (GIOJ)

## Objetivo del proyecto

Construir un MVP funcional para automatizar el análisis jurídico de solicitudes de conformidad inmobiliaria.

El sistema debe reducir el tiempo de revisión realizado por un analista jurídico mediante:

1. Extracción automática de información.
2. Validación contra reglas jurídicas.
3. Generación de concepto jurídico.
4. Generación automática del documento de conformidad o no conformidad.

La prioridad absoluta es la funcionalidad.

No debe desarrollarse un CRM completo hasta finalizar el motor de análisis.

---

# Arquitectura de conocimiento

Toda la lógica jurídica del sistema se encuentra en el archivo

Arquitectura/Arquitectura.xlsx

Este archivo es la única fuente oficial de conocimiento.

Codex nunca debe duplicar reglas que ya existan allí.

Si una regla no existe deberá agregarse al archivo y no programarse de forma fija dentro del código.

---

# Hojas oficiales del conocimiento

El archivo Arquitectura.xlsx contiene las siguientes hojas.

01_Campos_Extraccion

Define todas las entidades y atributos que pueden extraerse.

02_Matriz_Origen_Datos

Define en qué documento aparece cada dato.

03_Catalogos

Contiene todos los catálogos del sistema.

04_Reglas_Negocio

Contiene las reglas jurídicas.

05_Extraccion_Documental

Define cómo extraer cada dato.

06_Flujo_Analisis_Conformidad

Describe paso a paso el proceso realizado por un analista.

07_Salida_Analisis

Define la estructura de salida del análisis.

08_Trazabilidad

Permite rastrear cada validación realizada.

09_Marcadores_Documento

Define los marcadores utilizados para generar el documento Word.

---

# Flujo obligatorio

Todo expediente debe seguir exactamente el siguiente flujo.

Documento PDF

↓

OCR

↓

Extracción

↓

Normalización

↓

Validaciones

↓

Aplicación de reglas jurídicas

↓

Resumen del análisis

↓

Concepto jurídico

↓

Generación del documento Word

↓

Conversión a PDF

No se permite alterar este flujo.

---

# Principios de extracción

Toda información extraída debe conservar exactamente el texto encontrado.

Nunca modificar:

• nombres

• números

• fechas

• matrículas

• direcciones

• linderos

• notarías

• poderes

La normalización debe hacerse en una capa independiente.

---

# Principios de validación

Toda validación debe producir:

Cumple

No cumple

No existe información

No aplica

Nunca utilizar otros estados.

---

# Trazabilidad

Toda validación debe indicar:

Documento utilizado

Página

Campo comparado

Valor encontrado

Valor esperado

Resultado

Observación

Esto permitirá al analista revisar rápidamente cualquier diferencia.

---

# Concepto jurídico

El sistema nunca reemplaza al analista.

Debe generar únicamente un borrador.

Si todas las validaciones cumplen:

Resultado:

Conformidad

Si existe al menos una validación obligatoria incumplida:

Resultado:

No Conformidad

El concepto deberá resumir únicamente las diferencias encontradas.

---

# Documento generado

El documento nunca debe construirse desde cero.

Siempre deberá utilizar la plantilla oficial ubicada en

Plantillas/

Los marcadores definidos en:

09_Marcadores_Documento

son la única forma autorizada para reemplazar información.

Nunca modificar estilos.

Nunca modificar formatos.

Nunca modificar encabezados.

Nunca modificar pies de página.

Nunca modificar numeración.

---

# Interfaz

La interfaz ya existe.

Codex deberá mejorarla sin alterar el flujo de trabajo del analista.

El proceso esperado es:

Nuevo Proyecto

↓

Seleccionar carpeta del expediente

↓

Analizar

↓

Mostrar resumen

↓

Mostrar validaciones

↓

Mostrar trazabilidad

↓

Generar documento

---

# Organización del código

Todo el código deberá dividirse por módulos.

OCR

Extractor

Normalizador

Validador

Motor Jurídico

Generador Documento

Interfaz

Nunca crear archivos gigantes.

---

# Reglas de programación

Priorizar claridad antes que complejidad.

No duplicar código.

Utilizar funciones reutilizables.

Documentar únicamente funciones públicas.

No programar reglas jurídicas directamente.

Siempre leerlas desde Arquitectura.xlsx.

---

# Objetivo del MVP

El MVP estará terminado cuando sea capaz de:

Abrir un expediente.

Extraer automáticamente la información.

Aplicar todas las reglas jurídicas.

Generar la trazabilidad.

Mostrar el resumen del análisis.

Generar automáticamente un documento de Conformidad o No Conformidad utilizando la plantilla oficial.

Todo desarrollo futuro deberá mantener compatibilidad con esta arquitectura.