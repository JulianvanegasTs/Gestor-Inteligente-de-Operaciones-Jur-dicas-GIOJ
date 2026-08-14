# Casos de prueba del motor jurídico

Esta carpeta contiene únicamente expedientes de prueba del proyecto. Los
documentos ubicados fuera del repositorio, incluidos los de `GIOJ_PRUEBAS`, se
usan como material de consulta y no son una ruta de entrada del motor.

## Estructura

```text
Expedientes/Pruebas/
├── Casos_Conformidad/
│   └── CON-XXX/
│       ├── 01_Documentos/
│       ├── 02_Datos_estructurados/
│       └── 03_Resultados/
└── Casos_No_Conformidad/
    └── NC-XXX/
        ├── 01_Documentos/
        ├── 02_Datos_estructurados/
        └── 03_Resultados/
```

La estructura interna es la misma para conformidades y no conformidades. La
única diferencia es el resultado esperado del expediente.

## Contenido de cada caso

- `01_Documentos/`: copias de trabajo de los documentos del expediente. No
  modificar los originales.
- `02_Datos_estructurados/`: manifiesto esperado por campo, documento y
  página. Debe conservar el valor esperado y, si aplica, el valor que hace que
  el caso sea no conforme.
- `03_Resultados/`: resultado esperado del análisis: estado de cada validación,
  trazabilidad y tipo de certificado propuesto.

## Convención para casos negativos

Un caso `NC-XXX` debe aislar preferiblemente una inconsistencia principal. Por
ejemplo, una matrícula diferente, un número de documento inconsistente, un
poder no aplicable o un documento obligatorio ausente. Si requiere varias
inconsistencias, cada una debe quedar identificada por separado en la
trazabilidad esperada.

Los estados permitidos son: `Cumple`, `No cumple`, `No existe información` y
`No aplica`.

## Archivos JSON del corpus

Cada expediente procesado utiliza dos archivos estables:

```text
02_Datos_estructurados/datos_estructurados.json
03_Resultados/resultado_esperado.json
```

`datos_estructurados.json` conserva el inventario de documentos fuente, su
huella SHA-256, el texto por página, el método de lectura, la confianza OCR y
los datos detectados con documento, página y fragmento de evidencia. Esta
salida es un conjunto de prueba y no constituye una regla del motor.

Los documentos de identidad se procesan con un criterio reutilizable por tipo
documental. Cuando ambas lecturas lo permiten, se registran `Nombre`,
`Tipo_Documento` y `Numero_Documento`; no se crean excepciones por persona o
expediente. Las matrículas inmobiliarias requieren contexto registral y las
fechas numéricas deben ser calendáricamente plausibles, para evitar que códigos
o números de licencia se clasifiquen como campos jurídicos distintos.

`resultado_esperado.json` conserva el documento resultado sin modificarlo y
define el resultado jurídico esperado. Para conformidades, la fuente de verdad
es la escritura final aprobada. Para no conformidades, la fuente de verdad es
exclusivamente el certificado o plantilla manual elaborado por el analista;
cada observación se registra individualmente con las páginas de la escritura,
el valor esperado cuando esté expresamente indicado y el texto íntegro de la
observación.

Cuando la plantilla manual no identifica el valor equivocado de manera
literal, el JSON registra `No indicado expresamente en la plantilla manual`.
No se deducen ni inventan valores.

## Doble verificación

El procesamiento aplica dos revisiones:

1. Extracción por texto digital, estructura OOXML u OCR Tesseract con
   segmentación automática.
2. Contraste mediante texto digital o una segunda lectura OCR con distinta
   segmentación y mayor resolución para las páginas que contienen datos.

Los valores no confirmados por ambas lecturas no deben consumirse como verdad
de prueba sin revisión visual y se conservan por separado en
`hallazgos_no_confirmados`. El bloque `verificacion` registra cantidades,
errores y el estado final del expediente.

## Privacidad y control de versiones

Los directorios `CON-*` y `NC-*` están excluidos mediante `.gitignore`. Solo se
versionan este README y las carpetas `_PLANTILLA_CASO`. Los PDF, DOCX y JSON
del corpus permanecen en el entorno local autorizado.
