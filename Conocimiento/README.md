# Base de Conocimiento

Esta carpeta contiene la información utilizada como apoyo para el análisis jurídico.

No contiene expedientes de trabajo.

No contiene resultados temporales.

Su objetivo es proporcionar información de referencia para el sistema.

---

# Estructura

Poderes/

Tablas de poderes y apoderados autorizados.

Minutas/

Minutas oficiales utilizadas para comparación.

Entidades/

Información institucional de entidades financieras.

Configuracion/

Catálogos auxiliares.

Casos externos

Los casos históricos y de prueba no se almacenan dentro de `Conocimiento/` ni
se versionan en Git. Su ubicación relativa configurada es
`../GIOJ_PRUEBAS/Casos`.

Cada caso externo conserva `01_Documentos`, `02_Datos_estructurados` y
`03_Resultados`. Durante el MVP su consumo permanece desactivado. La
organización externa no agrega reglas jurídicas ni modifica las validaciones
vigentes; cualquier observación histórica requiere revisión humana antes de
proponerse como cambio a la arquitectura oficial.

---

# Importante

Toda la información almacenada aquí deberá estar validada.

No deben almacenarse documentos duplicados.

Los cambios realizados en esta carpeta afectan el comportamiento futuro del sistema.
