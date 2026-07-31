# PROJECT.md

# Gestor Inteligente de Operaciones Jurídicas (GIOJ)

Versión del proyecto: MVP 1.0

---

# Descripción

El Gestor Inteligente de Operaciones Jurídicas (GIOJ) es un sistema diseñado para asistir a un analista jurídico en la revisión de solicitudes de conformidad relacionadas con créditos hipotecarios otorgados por CAVIPETROL y ECOPETROL.

El sistema no reemplaza el criterio jurídico del analista.

Su objetivo es automatizar las tareas repetitivas para reducir significativamente el tiempo de revisión.

---

# Objetivo principal

El MVP debe ser capaz de:

• Leer automáticamente un expediente.

• Extraer toda la información jurídica relevante.

• Comparar dicha información entre todos los documentos del expediente.

• Aplicar reglas jurídicas previamente definidas.

• Generar un resumen del análisis.

• Identificar inconsistencias.

• Elaborar un borrador del concepto jurídico.

• Generar automáticamente un documento de Conformidad o No Conformidad utilizando una plantilla Word existente.

---

# Objetivo del negocio

Actualmente un analista revisa manualmente cada expediente.

El sistema busca reducir este tiempo mediante un proceso completamente asistido por IA.

---

# Alcance del MVP

El MVP únicamente debe cubrir el análisis documental.

No debe desarrollarse todavía:

- CRM
- Gestión de usuarios
- Roles
- Base de datos
- Control de permisos
- Módulo administrativo
- Reportes estadísticos

Toda la prioridad del proyecto está enfocada en construir el motor jurídico.

---

# Flujo general

Todo expediente seguirá exactamente este flujo.

```
Expediente

↓

OCR

↓

Extracción documental

↓

Normalización

↓

Validación documental

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
```

Este flujo nunca debe modificarse.

---

# Arquitectura del conocimiento

Toda la lógica jurídica se encuentra en:

Arquitectura/Arquitectura.xlsx

Ese archivo constituye la única fuente oficial del conocimiento jurídico.

El código únicamente debe consumir dicha información.

Nunca programar reglas jurídicas directamente.

---

# Hojas del conocimiento

## 01_Campos_Extraccion

Define todas las entidades jurídicas.

Ejemplo:

- Personas
- Inmuebles
- Créditos
- Escrituras
- Poderes

---

## 02_Matriz_Origen_Datos

Define dónde puede encontrarse cada dato.

Ejemplo:

Número de matrícula

↓

Certificado de tradición

↓

Escritura

↓

Promesa

---

## 03_Catalogos

Contiene todos los valores controlados del sistema.

Ejemplo:

Roles

Tipos de documento

Tipos de inmueble

Tipos de acto

Tipos de poder

Estados

Etc.

---

## 04_Reglas_Negocio

Contiene las reglas jurídicas.

Actualmente incluye:

- Poderes autorizados
- Entidades
- Fechas
- Notarías
- Estado

En el futuro contendrá cientos de reglas adicionales.

---

## 05_Extraccion_Documental

Describe exactamente cómo extraer cada campo.

No contiene código.

Contiene únicamente instrucciones funcionales.

---

## 06_Flujo_Analisis_Conformidad

Representa el trabajo del analista.

Cada paso corresponde a una futura función del sistema.

---

## 07_Salida_Analisis

Define exactamente qué debe producir el sistema.

---

## 08_Trazabilidad

Permite conocer:

Qué documento fue utilizado.

Qué valor fue encontrado.

Qué regla fue aplicada.

Qué resultado produjo.

---

## 09_Marcadores_Documento

Contiene todos los marcadores Word utilizados para generar automáticamente el documento final.

---

# Entrada del sistema

El usuario seleccionará una carpeta local.

Dentro existirán todos los documentos del expediente.

Ejemplo

```
Expediente_001/

CTL.pdf

Promesa.pdf

Documento_Comprador.pdf

Documento_Vendedor.pdf

Poder.pdf

Minuta_Hipoteca.pdf

Escritura.pdf

...
```

El sistema debe detectar automáticamente el tipo documental.

---

# Salida del sistema

El sistema debe producir:

Resumen del análisis.

Información relevante identificada.

Resultado de todas las validaciones.

Trazabilidad completa.

Concepto jurídico.

Documento Word.

Documento PDF.

---

# Principios de extracción

Toda extracción debe conservar exactamente el contenido original.

Nunca modificar:

Nombres.

Fechas.

Números.

Matrículas.

Notarías.

Linderos.

Direcciones.

Poderes.

La normalización siempre será una etapa posterior.

---

# Principios de validación

Toda validación debe producir únicamente uno de estos estados:

Cumple

No cumple

No existe información

No aplica

---

# Principios de trazabilidad

Toda decisión debe ser explicable.

Siempre deberá conocerse:

Documento.

Página.

Campo.

Valor encontrado.

Valor esperado.

Resultado.

Observación.

---

# Concepto jurídico

El sistema generará únicamente un borrador.

El analista será quien tome la decisión final.

Si todas las reglas obligatorias cumplen:

Resultado:

Conformidad

Si existe alguna regla obligatoria incumplida:

Resultado:

No Conformidad

---

# Generación documental

Nunca crear documentos desde cero.

Siempre utilizar la plantilla oficial ubicada en:

Plantillas/

Los datos se insertarán utilizando los marcadores definidos en:

09_Marcadores_Documento

---

# Interfaz

El usuario únicamente deberá realizar cuatro acciones.

1. Crear proyecto.

2. Seleccionar carpeta.

3. Analizar.

4. Generar documento.

Todo lo demás debe ser automático.

---

# Organización del proyecto

```
Proyecto/

Arquitectura/

Plantillas/

Expedientes/

Conocimiento/

Salida/

Logs/

Codigo/

README.md

PROJECT.md

AGENTS.md
```

---

# Prioridades

Prioridad 1

Motor de extracción.

Prioridad 2

Motor de validación.

Prioridad 3

Motor jurídico.

Prioridad 4

Generador documental.

Prioridad 5

Interfaz.

---

# Filosofía del proyecto

Toda decisión técnica debe responder a una única pregunta:

"¿Esto reduce el tiempo que hoy invierte un analista jurídico?"

Si la respuesta es no, entonces esa funcionalidad no pertenece al MVP.

---

# Estado actual del proyecto

Actualmente ya se encuentran diseñadas las siguientes estructuras:

✓ Arquitectura de datos

✓ Campos de extracción

✓ Matriz de origen documental

✓ Catálogos

✓ Reglas de negocio

✓ Motor de extracción documental

✓ Flujo de análisis jurídico

✓ Salida del análisis

✓ Trazabilidad

✓ Marcadores del documento

El siguiente paso consiste en implementar el motor funcional respetando toda esta arquitectura.