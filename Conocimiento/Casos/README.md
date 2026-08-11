# Casos históricos de no conformidad

Esta carpeta conserva antecedentes documentales para consulta del analista.
No es una carpeta de expedientes activos ni de resultados temporales.

## Flujo de almacenamiento

1. Cree una carpeta con un identificador no sensible, por ejemplo
   `NC-2026-001`, en `Pendientes_Estructuracion/`.
2. Guarde el certificado emitido como `certificado_no_conformidad.pdf` o
   `certificado_no_conformidad.docx`.
3. Incluya una copia autorizada de los documentos analizados dentro de
   `01_Documentos_Analizados/`, especialmente la `Escritura_Firma` y los
   soportes necesarios para ubicar la evidencia.
4. Tras generar y revisar `caso_historico.json`, traslade la carpeta completa
   a `Validados/`.

## Estructura esperada

```text
Casos/
├── Pendientes_Estructuracion/
│   └── NC-2026-001/
│       ├── certificado_no_conformidad.pdf
│       └── 01_Documentos_Analizados/
│           └── escritura_firma.pdf
└── Validados/
    └── NC-2026-001/
        ├── certificado_no_conformidad.pdf
        ├── caso_historico.json
        └── 01_Documentos_Analizados/
```

Los motivos enumerados del certificado deben conservarse literalmente en el
JSON, junto con el documento, página y fragmento de evidencia cuando estén
disponibles. Son antecedentes históricos, no reglas jurídicas automáticas.
