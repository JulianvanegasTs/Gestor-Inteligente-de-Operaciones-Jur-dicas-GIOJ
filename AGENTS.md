# AGENTS.md

# Agente de Desarrollo
## Gestor Inteligente de Operaciones Jurídicas (GIOJ)

---

# Rol del Agente

El agente actúa como Arquitecto Implementador.

Su responsabilidad consiste exclusivamente en implementar la arquitectura existente.

No debe rediseñar el sistema.

No debe simplificar procesos jurídicos.

No debe modificar el funcionamiento definido por la arquitectura.

Todas las decisiones deberán respetar estrictamente la documentación del proyecto.

---

# Prioridad de documentos

Si existe una contradicción entre documentos, deberá respetarse el siguiente orden de prioridad:

1. Arquitectura/Arquitectura.xlsx
2. AGENTS.md
3. PROJECT.md
4. MVP.md
5. ROADMAP.md
6. README.md

Nunca deberá tomarse una decisión que contradiga Arquitectura.xlsx.

---

# Objetivo del proyecto

El objetivo del proyecto NO es construir:

- un OCR;
- un CRM;
- un gestor documental;
- un sistema de IA genérico.

El objetivo consiste en reproducir el trabajo realizado actualmente por un analista jurídico encargado de emitir conceptos de conformidad para escrituras públicas.

Toda decisión deberá orientarse a facilitar ese proceso.

---

# Arquitectura

Toda la lógica funcional se encuentra definida en:

Arquitectura/Arquitectura.xlsx

El código únicamente deberá interpretar dicha arquitectura.

Nunca deberán programarse reglas jurídicas manualmente.

---

# Archivos que nunca podrán modificarse

El agente NO podrá modificar:

Arquitectura.xlsx

Plantillas Word

Interfaz HTML

config.json

Marcadores definidos

Formateadores

Reglas de negocio

Únicamente podrá leer dichos archivos.

---

# Interfaz

La interfaz HTML existente constituye la interfaz oficial del proyecto.

El agente deberá reutilizarla.

No deberá crear una nueva interfaz.

No deberá modificar el diseño salvo autorización expresa.

El trabajo consiste en conectar la interfaz existente con el motor del sistema.

---

# Flujo obligatorio

Todo expediente deberá seguir exactamente este flujo:

Interfaz

↓

Selección del expediente

↓

OCR

↓

Clasificación documental

↓

Extracción

↓

Normalización

↓

Validación documental

↓

Motor jurídico

↓

Trazabilidad

↓

Concepto jurídico

↓

Generación Word

↓

Conversión PDF

Nunca alterar este orden.

---

# Desarrollo por fases

El desarrollo deberá seguir exactamente ROADMAP.md.

No podrá iniciarse una fase nueva hasta finalizar completamente la anterior.

Cada fase deberá ser funcional antes de continuar.

---

# Filosofía de implementación

Cada módulo deberá cumplir los siguientes principios:

- Responsabilidad única.
- Bajo acoplamiento.
- Alta cohesión.
- Fácil mantenimiento.
- Fácil ampliación.
- Fácil prueba.
- Código reutilizable.

---

# Arquitectura del código

Separar claramente:

Interfaz

Servicios

Motor OCR

Clasificador documental

Extractor

Normalizador

Motor jurídico

Generador documental

Utilidades

Nunca mezclar responsabilidades.

---

# Extracción

Toda extracción deberá obtenerse desde:

01_Campos_Extraccion

05_Extraccion_Documental

Nunca crear campos manualmente.

Nunca inventar nuevos campos.

---

# Validaciones

Todas las reglas deberán obtenerse desde:

04_Reglas_Negocio

Nunca escribir reglas directamente en el código.

---

# Trazabilidad

Cada validación deberá registrar como mínimo:

Documento

Página

Campo

Valor esperado

Valor encontrado

Resultado

Observación

Nunca eliminar trazabilidad.

---

# Concepto jurídico

El sistema nunca reemplaza el criterio profesional del analista.

Únicamente genera un borrador fundamentado utilizando:

Resultado de las reglas.

Información extraída.

Evidencia documental.

El analista conserva siempre la decisión final.

---

# Generación documental

El sistema deberá utilizar exclusivamente las plantillas oficiales.

Nunca modificar:

Formato

Estilos

Tablas

Encabezados

Pies de página

Numeración

Únicamente reemplazar los marcadores definidos.

---

# Manejo de errores

El sistema nunca deberá detener completamente un análisis por un único error.

Ante cualquier excepción deberá:

Registrar el error.

Continuar el análisis.

Mostrar el error al usuario.

Guardar el error en los logs.

---

# Calidad del código

Todo desarrollo deberá cumplir:

Código limpio.

Nombres descriptivos.

Funciones pequeñas.

Responsabilidad única.

Documentación de funciones públicas.

Sin duplicación de código.

---

# Preparación para crecimiento

Aunque el desarrollo corresponde únicamente al MVP, toda la arquitectura deberá permitir incorporar posteriormente:

CRM

Usuarios

Roles

Panel administrativo

Estadísticas

Base de datos

API

Procesamiento distribuido

Sin reescribir el motor jurídico.

---

# Criterios de aceptación

Antes de finalizar cualquier fase deberán cumplirse todos los siguientes puntos:

□ Compila correctamente.

□ No presenta errores críticos.

□ Respeta Arquitectura.xlsx.

□ Respeta las plantillas Word.

□ Respeta la interfaz HTML.

□ No rompe funcionalidades anteriores.

□ Está documentado.

□ Puede ser utilizado por el siguiente módulo.

---

# Restricciones

El agente nunca deberá:

Modificar la arquitectura funcional.

Modificar nombres de carpetas.

Cambiar la estructura del proyecto.

Inventar reglas jurídicas.

Inventar campos.

Eliminar trazabilidad.

Reemplazar la interfaz.

Modificar las plantillas.

Modificar la documentación sin autorización.

---

# Resultado esperado

Al finalizar el desarrollo del MVP el sistema deberá ser capaz de:

1. Seleccionar un expediente.

2. Leer automáticamente todos los documentos.

3. Extraer toda la información.

4. Aplicar las reglas jurídicas.

5. Mostrar la trazabilidad completa.

6. Generar un concepto jurídico.

7. Generar automáticamente un Certificado de Conformidad o No Conformidad en Word.

8. Convertir automáticamente el documento generado a PDF.

Todo ello utilizando exclusivamente la arquitectura definida y la interfaz HTML existente.