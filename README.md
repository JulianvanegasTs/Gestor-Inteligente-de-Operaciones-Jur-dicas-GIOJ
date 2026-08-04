# Gestor Inteligente de Operaciones Jurídicas (GIOJ)

## Descripción

GIOJ es un sistema local diseñado para automatizar el análisis jurídico de solicitudes de conformidad para escrituras públicas.

El sistema replica el flujo de trabajo realizado por un analista jurídico mediante extracción documental, validaciones jurídicas, generación de conceptos y elaboración automática de certificados de conformidad o no conformidad.

---

# Objetivo del proyecto

Reducir el tiempo de análisis de expedientes mediante inteligencia artificial y reglas jurídicas parametrizadas.

---

# Estructura del proyecto

Arquitectura/
Contiene todas las reglas de negocio.

Plantillas/
Contiene los documentos Word utilizados para generar certificados.

Expedientes/
Contiene cada expediente que será analizado.

Conocimiento/
Contiene la base documental utilizada por la IA.

Programa/
Contiene el código fuente del sistema.

---

# Flujo general

Expediente

↓

OCR

↓

Extracción

↓

Normalización

↓

Validaciones

↓

Concepto Jurídico

↓

Generación del Certificado

---

# Documentación

PROJECT.md
Descripción funcional completa.

MVP.md
Alcance de la primera versión.

AGENTS.md
Instrucciones para Codex.

---

# Estado

Versión actual:

MVP en desarrollo.

---

# Inicialización (GIOJ-001)

Desde la raíz del proyecto, ejecute:

```powershell
python -m Codigo
```

Se requiere Python 3.11 o superior instalado y disponible como `python` en el
PATH del sistema.

El comando lee `Arquitectura/config.json`, crea las carpetas operativas
configuradas, inicializa `Logs/inicializacion.log` y valida el libro de
arquitectura, sus hojas obligatorias y las plantillas declaradas.

El proceso termina con código `0` si el sistema queda listo y con código `1`
si encuentra una inconsistencia. Actualmente las plantillas existentes tienen
nombres distintos de los declarados en `config.json`; por seguridad, el
diagnóstico las reportará como faltantes sin modificar ningún archivo oficial.

Para ejecutar las pruebas de inicialización:

```powershell
python -m unittest discover -s tests -v
```
