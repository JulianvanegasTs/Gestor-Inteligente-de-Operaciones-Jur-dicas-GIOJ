# ROADMAP.md

# Hoja de Ruta del Proyecto
## Gestor Inteligente de Operaciones Jurídicas (GIOJ)

---

# Objetivo

Construir un MVP completamente funcional capaz de analizar expedientes jurídicos y generar automáticamente un Certificado de Conformidad o No Conformidad.

El desarrollo deberá centrarse en implementar el motor jurídico utilizando la arquitectura definida en Arquitectura.xlsx.

La interfaz HTML existente será la base del programa.

---

# Principios de desarrollo

1. No modificar la arquitectura funcional.

2. No modificar las plantillas Word.

3. No programar reglas jurídicas manualmente.

4. Toda regla deberá obtenerse desde Arquitectura.xlsx.

5. Toda modificación funcional deberá realizarse mediante la arquitectura y no mediante código.

6. Cada fase deberá quedar completamente funcional antes de iniciar la siguiente.

---

# Estado actual

Actualmente ya se encuentran finalizados:

✅ Arquitectura funcional

✅ Arquitectura.xlsx

✅ Plantillas Word

✅ Interfaz HTML

✅ Flujo jurídico

✅ Reglas de negocio

✅ Marcadores

✅ Trazabilidad

✅ Formateadores

A partir de este punto inicia únicamente el desarrollo del software.

---

# FASE 0
## Inicialización del proyecto

Objetivo

Crear la estructura interna del sistema.

El programa deberá:

• Leer config.json.

• Validar Arquitectura.xlsx.

• Validar las plantillas.

• Crear automáticamente las carpetas temporales necesarias.

• Inicializar logs.

Resultado esperado

Sistema listo para iniciar.

---

# FASE 1
## Integración de la interfaz

La interfaz HTML existente será utilizada como interfaz del MVP.

No deberá reemplazarse.

Únicamente deberán conectarse sus componentes con el motor del sistema.

Botones esperados

• Nuevo Proyecto

• Analizar

• Generar Documento

Paneles esperados

• Concepto Jurídico

• Información relevante identificada

• Resultado del análisis

• Trazabilidad

Resultado esperado

La interfaz abre correctamente y permite iniciar un expediente.

---

# FASE 2
## Lectura del expediente

Objetivo

Seleccionar una carpeta local.

Detectar automáticamente todos los documentos.

Identificar:

PDF

DOCX

Imágenes

Resultado esperado

Objeto Expediente completamente construido.

---

# FASE 3
## OCR

Objetivo

Extraer texto de todos los documentos.

Debe soportar:

PDF digital

PDF escaneado

Imágenes

Resultado esperado

Texto utilizable para cada documento.

---

# FASE 4
## Clasificación documental

Objetivo

Identificar automáticamente:

Escritura objeto

Escrituras antecedentes

CTL

Promesa

Minuta

Documento identidad

Poder

Reglamento PH

Otro Sí

Cámara de Comercio

Resultado esperado

Cada documento posee un tipo documental.

---

# FASE 5
## Motor de extracción

Objetivo

Extraer todos los campos definidos en:

01_Campos_Extraccion

utilizando

05_Extraccion_Documental

No programar campos manualmente.

Resultado esperado

JSON estructurado.

---

# FASE 6
## Normalización

Objetivo

Normalizar únicamente cuando sea necesario.

Ejemplos

Fechas

Monedas

Documentos

Notarías

Estados civiles

Nunca modificar el texto original.

Resultado esperado

Datos normalizados.

---

# FASE 7
## Validación documental

Objetivo

Comparar todos los documentos que contengan un mismo dato.

Registrar:

Documento origen

Documento comparado

Página

Campo

Valor esperado

Valor encontrado

Resultado

Resultado esperado

Estado:

Cumple

No cumple

No aplica

Sin información

---

# FASE 8
## Motor jurídico

Objetivo

Aplicar automáticamente todas las reglas de:

04_Reglas_Negocio

Todas las reglas deberán leerse desde Arquitectura.xlsx.

Nunca programarlas manualmente.

Resultado esperado

Resultado jurídico completo.

---

# FASE 9
## Trazabilidad

Objetivo

Registrar absolutamente todas las decisiones del sistema.

Cada validación deberá contener:

Documento

Página

Campo

Valor encontrado

Valor esperado

Resultado

Observación

Resultado esperado

El analista puede conocer exactamente dónde ocurrió cada diferencia.

---

# FASE 10
## Concepto jurídico

Objetivo

Construir automáticamente un resumen ejecutivo del análisis.

El sistema nunca reemplaza el criterio profesional del analista.

Únicamente genera un borrador utilizando:

• Resultado de las reglas

• Información extraída

• Evidencia documental

Si todas las reglas cumplen:

Conformidad.

Si alguna regla obligatoria falla:

No Conformidad.

---

# FASE 11
## Generación documental

Objetivo

Completar automáticamente las plantillas Word.

Nunca modificar:

Formato

Estilos

Encabezados

Pies

Numeración

Únicamente reemplazar los marcadores definidos en:

09_Marcadores_Documento

Resultado esperado

Documento Word completamente diligenciado.

---

# FASE 12
## Conversión a PDF

Objetivo

Convertir automáticamente el documento Word generado a PDF.

Resultado esperado

PDF listo para entregar.

---

# Criterios de aceptación

Una fase únicamente podrá darse por finalizada cuando:

• Existan pruebas funcionales.

• No existan errores críticos.

• El resultado sea reproducible.

• El siguiente módulo pueda consumir su salida.

• No requiera intervención manual adicional.

---

# Definición de MVP terminado

El MVP estará terminado únicamente cuando sea capaz de:

✅ Leer un expediente completo.

✅ Clasificar automáticamente los documentos.

✅ Extraer toda la información.

✅ Aplicar las reglas jurídicas.

✅ Mostrar la trazabilidad.

✅ Generar el concepto jurídico.

✅ Generar automáticamente el documento Word.

✅ Convertir el documento a PDF.

Todo ello utilizando la interfaz HTML existente.

---

# Fuera del alcance del MVP

No desarrollar todavía:

• CRM

• Usuarios

• Roles

• Administración

• Estadísticas

• Base de datos

• API

• Nube

• Integraciones externas

Estas funcionalidades únicamente podrán desarrollarse después de finalizar completamente el motor jurídico.