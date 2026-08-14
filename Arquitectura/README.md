# Arquitectura del Sistema

## Alcance operativo del MVP

La persona analista selecciona desde la interfaz los archivos que desea
analizar, sin importar la carpeta del computador donde se encuentren. El
sistema recibe esos archivos temporalmente en memoria y no crea copias, no los
mueve y no modifica los originales.

El límite total de la selección se define en `config.json` mediante
`mvp.tamano_maximo_seleccion_mb`; la interfaz debe consultarlo y mostrar un
mensaje de tamaño explícito antes de transmitir una selección que lo exceda.

Los resultados derivados y la trazabilidad sí se guardan bajo `Salida/` con el
identificador temporal de la selección. La barra de estado debe acompañar las
fases de OCR, clasificación, extracción, normalización, validación y concepto.

El resultado del motor jurídico es preliminar. La interfaz debe mostrar el
concepto y todas las validaciones, registrar una segunda revisión humana con
estado `Pendiente`, `Confirmado` o `Rechazado`, y bloquear la generación
documental salvo cuando el analista confirme expresamente el análisis. Cada
nuevo análisis restablece la revisión a `Pendiente`.

Los casos ubicados fuera del proyecto, incluidos los de `GIOJ_PRUEBAS`, son
material de consulta. No son una ruta configurada ni una entrada del motor de
análisis.

Esta carpeta contiene toda la configuración funcional del proyecto.

El sistema obtiene desde estos archivos todas las reglas necesarias para ejecutar el análisis.

No deben programarse reglas jurídicas directamente en el código.

Toda modificación funcional debe realizarse desde Arquitectura.xlsx.

---

# Archivos

Arquitectura.xlsx

Contiene:

- Campos de extracción
- Catálogos
- Reglas jurídicas
- Flujo del analista
- Motor de extracción
- Salidas
- Trazabilidad
- Marcadores
- Formateadores
- Regla de consolidación del resultado preliminar
- Estado y trazabilidad de la revisión del analista

config.json

Contiene parámetros generales del sistema.

---

# Objetivo

Separar completamente la lógica jurídica del código fuente.

El programa únicamente interpreta esta arquitectura.

Nunca debe modificarla.

---

# Requisito permanente de interfaz

La interfaz oficial debe mantener una barra de estado sencilla, ubicada debajo
del botón **Iniciar análisis** y visible mientras se ejecuta el flujo. Debe
mostrar la etapa actual, el porcentaje y el progreso accesible mediante
`role="progressbar"` y `aria-valuenow`.

Este control visual no modifica el motor jurídico ni las reglas de
`Arquitectura.xlsx`, pero es obligatorio para todos los ciclos de integración
de la interfaz. No debe eliminarse ni trasladarse a un área que pueda quedar
oculta durante el análisis.

---

# Diseño vigente del ciclo integral

Además de las diez hojas base, el libro contiene:

- `11_Perfiles_Documentales`: señales obligatorias, positivas, negativas y
  umbrales del tipo físico.
- `12_Roles_Documentales`: diferencia la naturaleza física del papel de su
  función dentro del expediente, incluida `Escritura_Firma`.
- `13_Criterios_Extraccion`: anclas, exclusiones, fuente, contraste,
  cardinalidad, precedencia, normalizador y confianza mínima por campo.
- `14_Normalizadores_Entrada`: reglas canónicas que conservan siempre el valor
  bruto como evidencia.
- `15_Segmentacion_Documental`: límites, continuidad y rol sugerido de cada
  documento lógico.

El orden obligatorio es OCR, segmentación, clasificación física y funcional,
extracción, normalización, validación, motor jurídico, trazabilidad, revisión
individual, generación Word y conversión PDF.

La regla `DOC-002` es permanente: el consecutivo de los certificados lo
diligencia exclusivamente el analista. El sistema no debe crear el marcador
`{{CONSECUTIVO}}`, solicitar el dato en interfaz, calcularlo ni reemplazar la
línea en blanco de las plantillas.

La generación documental consume únicamente los marcadores vigentes de
`09_Marcadores_Documento`, verifica que no queden variables sin reemplazar y
comprueba que el hash de la plantilla fuente sea idéntico antes y después. La
revisión humana debe cubrir cada comprobación antes de habilitar esta fase.

Los estados jurídicos se conservan siempre con su codificación canónica:
`Cumple`, `No cumple`, `No existe información` y `No aplica`. El rol funcional
clasificado tiene prioridad sobre similitudes físicas: una escritura antigua o
de compraventa no puede utilizarse como `Escritura_Firma` si la clasificación
no le asignó ese rol. Cuando falta la escritura sometida a firma, el flujo debe
terminar en no conformidad trazable y no en un error técnico.

Los identificadores de arquitectura, como `OBL-CRE-002`, permanecen en JSON y
Logs para auditoría, pero no son denominaciones visibles en la interfaz. El
concepto, la trazabilidad y la revisión del analista utilizan `Nombre_Regla` y
los nombres funcionales de `01_Campos_Extraccion`.
