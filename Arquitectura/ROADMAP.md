# ROADMAP.md

# Hoja de Ruta del Proyecto
## Gestor Inteligente de Operaciones Jurídicas (GIOJ)

---

# Objetivo

Construir un MVP completamente funcional capaz de analizar expedientes jurídicos y generar automáticamente un documento de Conformidad o No Conformidad.

Toda decisión de desarrollo deberá priorizar el motor jurídico sobre cualquier funcionalidad visual.

---

# Regla principal

No avanzar a la siguiente fase hasta que la anterior funcione correctamente.

Cada fase debe quedar completamente funcional antes de iniciar la siguiente.

---

# Estado actual

Actualmente ya se encuentran diseñadas las siguientes estructuras:

✅ Arquitectura de datos

✅ Campos de extracción

✅ Matriz de origen documental

✅ Catálogos

✅ Reglas de negocio

✅ Motor de extracción documental (definido)

✅ Flujo de análisis jurídico

✅ Salida del análisis

✅ Trazabilidad

✅ Marcadores del documento

La arquitectura funcional ya existe.

A partir de este punto comienza la programación.

---

# FASE 1
## Lectura del expediente

Objetivo

Permitir que el usuario seleccione una carpeta local.

El sistema deberá:

• Detectar automáticamente todos los archivos.

• Identificar su tipo documental.

• Crear el expediente interno.

Entrada

Carpeta local.

Salida

Objeto Expediente.

Criterio de finalización

El sistema identifica correctamente todos los documentos del expediente.

---

# FASE 2
## OCR

Objetivo

Extraer texto de todos los documentos.

Debe funcionar con:

PDF

PDF escaneado

Imágenes

Salida

Texto completo de cada documento.

Criterio de finalización

Todo documento genera texto utilizable.

---

# FASE 3
## Clasificación documental

Objetivo

Clasificar automáticamente cada archivo.

Ejemplos

Escritura de firma

Escritura antigua

Reglamento PH

CTL

Promesa

Minuta

Documento identidad

Poder

Otro Sí

Cámara de Comercio

Salida

Tipo documental.

---

# FASE 4
## Motor de extracción

Objetivo

Extraer todos los campos definidos en:

01_Campos_Extraccion

utilizando

05_Extraccion_Documental

No programar campos manualmente.

Toda extracción debe depender de la arquitectura.

Salida

JSON estructurado.

---

# FASE 5
## Normalización

Objetivo

Normalizar únicamente cuando sea necesario.

Ejemplos

Fechas

Números

Monedas

Documentos

Nunca modificar el texto original.

---

# FASE 6
## Validación documental

Objetivo

Comparar la información entre todos los documentos.

Ejemplos

Documento identidad

↓

Escritura

↓

Promesa

↓

CTL

↓

Minuta

Salida

Cumple

No cumple

No existe información

No aplica

---

# FASE 7
## Motor jurídico

Objetivo

Aplicar todas las reglas de

04_Reglas_Negocio

Toda regla deberá leerse desde Excel.

Nunca programarlas manualmente.

---

# FASE 8
## Trazabilidad

Objetivo

Registrar absolutamente todas las decisiones.

Cada validación deberá indicar:

Documento

Página

Campo

Valor encontrado

Valor esperado

Resultado

Observación

---

# FASE 9
## Concepto jurídico

Objetivo

Construir un resumen del análisis.

Si todas las reglas cumplen

↓

Conformidad

Si alguna regla obligatoria falla

↓

No Conformidad

El sistema nunca toma la decisión jurídica.

Solo propone un borrador.

---

# FASE 10
## Generación documental

Objetivo

Utilizar la plantilla oficial.

Nunca modificar:

Formato

Estilos

Encabezados

Pies

Numeración

Únicamente reemplazar marcadores.

---

# FASE 11
## Conversión a PDF

Objetivo

Convertir automáticamente el documento Word generado.

Salida

Documento PDF listo para entregar.

---

# FASE 12
## Interfaz

La interfaz será el último componente del MVP.

El flujo será:

Nuevo Proyecto

↓

Seleccionar carpeta

↓

Analizar

↓

Visualizar resumen

↓

Visualizar trazabilidad

↓

Generar documento

---

# Arquitectura esperada

Proyecto/

├── Arquitectura/
│   ├── Arquitectura.xlsx
│   ├── README.md
│   ├── PROJECT.md
│   ├── AGENTS.md
│   ├── ROADMAP.md
│   └── config.json
│
├── Plantillas/
│   ├── Conformidad.docx
│   └── No_Conformidad.docx
│
├── Expedientes/
│
├── Conocimiento/
│
├── Salida/
│
├── Logs/
│
├── Codigo/
│
└── main.py

---

# Definición de MVP terminado

El MVP estará terminado únicamente cuando sea capaz de:

✅ Leer un expediente completo.

✅ Extraer toda la información.

✅ Aplicar las reglas jurídicas.

✅ Mostrar la trazabilidad.

✅ Generar el concepto jurídico.

✅ Generar automáticamente un documento Word.

✅ Convertir el documento a PDF.

Hasta cumplir estos objetivos no deberán desarrollarse funcionalidades adicionales.

---

# Evolución futura (Fuera del MVP)

Una vez finalizado el MVP podrán desarrollarse:

• CRM

• Gestión de clientes

• Gestión de usuarios

• Roles

• Panel administrativo

• Estadísticas

• Versionado de expedientes

• Integración con bases de datos

• API

• Procesamiento en la nube

Estas funcionalidades no hacen parte del MVP y no deben implementarse antes de completar el motor jurídico.