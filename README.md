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

Durante el MVP, la persona analista selecciona en la interfaz los archivos que
desea analizar desde cualquier carpeta del computador. El backend conserva el
contenido únicamente en memoria durante la sesión: no copia, mueve ni modifica
los documentos originales.

Los casos conservados fuera del proyecto son antecedentes de consulta humana.
No se configuran como entrada del motor, no se consultan durante el análisis y
no reemplazan las reglas de `Arquitectura.xlsx`.

Los casos locales de regresión autorizados se organizan en
`Expedientes/Pruebas/Casos_Conformidad` y
`Expedientes/Pruebas/Casos_No_Conformidad`. Sus documentos y JSON derivados
están excluidos del repositorio por contener información jurídica sensible. El
formato, la doble verificación y las fuentes de verdad se documentan en
`Expedientes/Pruebas/README.md`. Estos casos no se consultan durante la
ejecución normal ni agregan reglas a la arquitectura.

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

---

# Interfaz local (GIOJ-002)

Para abrir la interfaz oficial conectada al backend local:

```powershell
python -m Codigo interfaz --puerto 8000
```

Abra `http://127.0.0.1:8000/` en el navegador. La interfaz se sirve desde
`Programa/index.html` sin modificar ese archivo. Los botones se conectan con
el backend: **Seleccionar archivos** recibe temporalmente los documentos en
memoria y **Iniciar análisis** ejecuta clasificación, OCR, extracción,
normalización, validación y concepto jurídico.

El servidor debe permanecer ejecutándose mientras se usa la interfaz. Si se
cierra la terminal o el proceso local, la página puede continuar visible en el
navegador, pero no podrá recibir ni analizar archivos. En ese caso, inicie de
nuevo el comando anterior, recargue la página y vuelva a seleccionar los
documentos.

Mantenga una sola instancia del servidor en el puerto 8000. La selección se
conserva en memoria del proceso que la recibe. Si ejecuta nuevamente el comando
mientras GIOJ ya está activo, la terminal mostrará la dirección de la instancia
existente; no es un error ni es necesario iniciar otro proceso. Recargue esa
página antes de volver a seleccionar los documentos.

Para detener limpiamente la instancia desde cualquier terminal, ejecute:

```powershell
python -m Codigo detener --puerto 8000
```

## Requisito permanente de progreso

La interfaz oficial debe conservar una barra de estado sencilla y visible
inmediatamente debajo del botón **Iniciar análisis**. Al comenzar el proceso
debe mostrar la etapa vigente y el porcentaje, actualizar `aria-valuenow`
durante el análisis y finalizar en `100%` o indicar visualmente el error.

Este componente forma parte de la interfaz aprobada. Los ciclos futuros no
deben retirarlo, ocultarlo detrás del panel de resultados ni sustituirlo sin
autorización funcional. La prueba `tests.test_ocr` protege este requisito.

La selección se hace con **Seleccionar archivos** y puede partir de cualquier
carpeta accesible para el navegador. El navegador transmite el contenido al
backend local sin revelar ni conservar las rutas absolutas. La selección
permanece en memoria y solo los resultados derivados se escriben en `Salida/`.

---

# Selección de archivos (GIOJ-003)

El botón **Seleccionar archivos** admite PDF, DOCX e imágenes compatibles
desde cualquier ubicación accesible para el navegador. Se rechazan archivos
vacíos, formatos no compatibles y nombres duplicados dentro de una misma
selección. El límite total configurado del MVP es 250 MB. Si se excede, la
interfaz informa el tamaño seleccionado antes de intentar la transmisión.

Los bytes seleccionados permanecen únicamente en la memoria del servidor
local. Los archivos fuente no se escriben en `Expedientes/` ni en otra carpeta.
Una nueva selección reemplaza la selección temporal anterior.

---

# OCR documental (GIOJ-004)

Al iniciar el análisis, GIOJ extrae texto de los PDF digitales, PDF
escaneados, DOCX e imágenes seleccionados. Conserva la relación entre documento,
página, texto, método de lectura y confianza OCR cuando aplica; los errores
de un documento se registran sin detener el procesamiento de los demás.

El resultado se guarda en:

```text
Salida/{id_seleccion}/texto_extraido.json
```

Para probarlo, ejecute:

```powershell
python -m unittest tests.test_ocr -v
```

---

# Clasificación documental (GIOJ-005)

Al terminar el OCR, el análisis clasifica cada documento con las definiciones
activas de `Arquitectura/Arquitectura.xlsx`. Consume el catálogo de tipos
documentales, la matriz de origen y las instrucciones de extracción; por ello,
no contiene una lista de tipos ni patrones jurídicos en el código.

El resultado se guarda en:

```text
Salida/{id_expediente}/clasificacion_documental.json
```

Cada registro conserva el documento original, el tipo y código definidos por
la arquitectura, la evidencia OCR por página o el estado `No identificado`
cuando no hay una coincidencia segura. También se registra el proceso en
`Logs/clasificacion.log`.

Para probarlo, ejecute:

```powershell
python -m unittest tests.test_clasificacion -v
```

O inicie la interfaz, seleccione los archivos y pulse **Iniciar análisis**:
la respuesta incluye la ubicación y el detalle de la clasificación.

---

# Extracción documental (GIOJ-006)

GIOJ extrae exclusivamente los campos e instrucciones definidos en
`01_Campos_Extraccion` y `05_Extraccion_Documental` de la arquitectura. Cada
valor conserva su documento, página, evidencia textual, método y confianza;
no se crean campos ni reglas de extracción en el código.

El resultado se guarda en:

```text
Salida/{id_expediente}/extraccion_documental.json
```

Para probarlo, ejecute:

```powershell
python -m unittest tests.test_extraccion -v
```

---

# Normalización de datos (GIOJ-007)

La normalización aplica los formateadores vigentes de `10_Formateadores` sin
modificar los datos originales. Produce valores de comparación para fechas,
monedas, nombres, notarías y otros formatos definidos, manteniendo las
evidencias de la extracción.

El resultado se guarda en:

```text
Salida/{id_expediente}/normalizacion_documental.json
```

Para probarlo, ejecute:

```powershell
python -m unittest tests.test_normalizacion -v
```

---

# Validaciones documentales (GIOJ-008)

`04_Reglas_Negocio` contiene controles ejecutables y no registros de
conocimiento. El motor identifica exactamente una `Escritura_Firma`, valida
los 39 datos obligatorios de `01_Campos_Extraccion`, compara las cláusulas
fijas contra `Conocimiento/Minutas/Minuta_hipoteca.docx`, verifica los poderes
contra `Conocimiento/Poderes/Poderes_ecopetrol_2026.xlsx` y ejecuta controles
de calidad documental.

Cada comparación conserva `Documento_Validado`, `Pagina_Validada`,
`Documento_Comparado`, `Pagina_Comparada`, `Valor_Esperado`,
`Valor_Encontrado` y `Estado_Interfaz`. Los estados internos permitidos son
`Cumple`, `No cumple`, `No existe información` y `No aplica`; la interfaz los
presenta como `Validado` o `No validado`.

La minuta mantiene intacto el clausulado definido por Ecopetrol. Sus anclas
internas `MIN_*` no son visibles en Word y permiten localizar cada diferencia
sin insertar identificadores en el texto jurídico.

El resultado se guarda en:

```text
Salida/{id_expediente}/validaciones_documentales.json
```

Para probarlo, ejecute:

```powershell
python -m unittest tests.test_validacion -v
```

---

# Motor jurídico (GIOJ-009)

El motor vuelve a leer todas las reglas de `04_Reglas_Negocio`, verifica que
cada una tenga una validación y consolida los controles por `Tipo_Regla`. En
los grupos estructurados todos los controles aplicables deben quedar
validados; cualquier incumplimiento o ausencia de evidencia produce `No
Conformidad`. `CON-001` consolida únicamente las reglas bloqueantes vigentes:
todas deben estar en `Cumple` o `No aplica`; cualquier `No cumple` o `No
existe información` produce `No Conformidad`. El resultado siempre es
preliminar. El `concepto_juridico` es conciso para Conformidad y detalla los
hallazgos que requieren corrección para No Conformidad.

El resultado se guarda en:

```text
Salida/{id_seleccion}/resultado_juridico.json
```

Para probarlo, ejecute:

```powershell
python -m unittest tests.test_motor_juridico -v
```

---

# Ciclo integral de análisis y generación

El flujo vigente es:

```text
Selección en memoria
→ OCR por página y segunda lectura condicional
→ Segmentación lógica
→ Clasificación por perfil físico y rol documental
→ Extracción con criterio y normalizador de entrada
→ Normalización de salida
→ Validación contra documentos fuente, minuta y poderes
→ Dictamen jurídico y trazabilidad
→ Revisión individual y decisión del analista
→ Certificado Word
→ PDF
```

La arquitectura incorpora las hojas `11_Perfiles_Documentales`,
`12_Roles_Documentales`, `13_Criterios_Extraccion`,
`14_Normalizadores_Entrada` y `15_Segmentacion_Documental`. Las nuevas fases
conservan documento físico, documento lógico, página, valor bruto, valor
normalizado, método, confianza OCR, segunda lectura y confianza semántica.

La interfaz mantiene una distribución 30% para ingreso y 70% para resultados.
Durante el procesamiento muestra únicamente `Concepto en curso` y
`Validaciones en curso` dentro de los campos de resultados; la etapa OCR y la
página se muestran en la barra de estado. Al terminar, **Validaciones
realizadas** enumera cada dato obligatorio con valor fuente, documento
contrastado, página numérica y resultado frente a la escritura.

## Regla permanente del consecutivo

La regla `DOC-002` de `04_Reglas_Negocio` establece que el consecutivo es
responsabilidad exclusiva del analista. GIOJ no lo extrae, calcula, solicita ni
reemplaza. No existe marcador `{{CONSECUTIVO}}`; la línea de ambas plantillas
permanece en blanco para su diligenciamiento manual después de generar el
documento.

## Generación oficial

Después de confirmar todas las comprobaciones, **Generar Documento** crea en
`Salida/{id_expediente}/`:

- `Certificado_Conformidad_{id_expediente}.docx` y su PDF; o
- `Certificado_No_Conformidad_{id_expediente}.docx` y su PDF.

Solo se reemplazan los marcadores de `09_Marcadores_Documento`. La salida de
no conformidad incorpora la lista de omisiones y discordancias confirmadas. La
conversión intenta LibreOffice en modo no interactivo y, en Windows, Microsoft
Word como alternativa. El entorno requiere `pypdf` y `lxml`, declarados en
`requirements.txt`.

## Pruebas automatizadas

Desde la raíz:

```powershell
python -m unittest discover -s tests -v
```

`tests/test_ciclo_integral.py` protege la regla manual del consecutivo, hashes
de plantillas, perfiles, segunda lectura OCR, falsos positivos de matrícula,
revisión individual, generación de ambos dictámenes y el corpus local de diez
casos positivos y diez negativos, con 65 hallazgos negativos verificados.

## Prueba manual de conformidad

1. Inicie `python -m Codigo interfaz --puerto 8000` y abra
   `http://127.0.0.1:8000/`.
2. Seleccione todos los documentos de
   `Expedientes/Pruebas/Casos_Conformidad/CON-005/01_Documentos`.
3. Pulse **Iniciar análisis**. Verifique `Concepto en curso`, `Validaciones en
   curso` y el avance técnico únicamente en la barra de estado.
4. Compruebe que Nombre muestre `JAVIER ALFONSO GARCIA CARVAJAL`, tipo de
   documento `Cédula de ciudadanía` y número `91292114`, todos vinculados a
   `CEDULA JAVIER.pdf`, página `1`.
5. Revise cada comprobación y márquela `Confirmada` u `Observada`; si observa
   una regla, registre su explicación. Confirme el análisis.
6. Genere el documento. Abra Word y PDF, verifique los datos reemplazados, la
   ausencia de marcadores pendientes y la línea de consecutivo en blanco.

## Prueba manual de no conformidad

1. Seleccione un caso de
   `Expedientes/Pruebas/Casos_No_Conformidad/NC-001/01_Documentos` a
   `NC-010/01_Documentos`.
2. Ejecute el análisis y compare cada hallazgo con
   `03_Resultados/resultado_esperado.json` del mismo expediente.
3. Verifique que el concepto explique las causas de no conformidad y que cada
   validación indique dato, valor encontrado, documento, página y discordancia.
4. Complete la revisión individual, confirme el análisis del sistema y genere
   el certificado de no conformidad.
5. Compruebe en Word y PDF que las observaciones enumeren la información
   faltante o discordante, y que el consecutivo siga reservado al analista.

## Resultados esperados del ciclo

- Todas las filas de `04_Reglas_Negocio` deben quedar evaluadas exactamente una
  vez.
- Las alternativas se consolidan por `Tipo_Regla`; una alternativa descartada
  no se trata como un incumplimiento independiente.
- Una coincidencia cuyo `Estado` sea `Vigente` permite `Conformidad`, siempre
  que no exista otra coincidencia no habilitante.
- Una coincidencia `No_Autorizado`, `Vencido`, `Suspendido` o `Revocado`
  produce `No Conformidad`.
- La ausencia de evidencia suficiente produce `No Conformidad` con estado `No
  existe información`; el sistema no presume conformidad.
- La salida debe registrar el resultado, las reglas evaluadas, el consolidado
  por tipo y las inconsistencias numeradas con archivo, página, valor esperado
  y valor encontrado.
- El resultado es una propuesta trazable para revisión del analista, no una
  sustitución de su criterio profesional.

# Doble análisis y autorización humana

Cada análisis crea `Salida/{id_seleccion}/revision_analista.json` con estado
`Pendiente`. La interfaz presenta el resultado preliminar, el concepto y el
listado completo de comprobaciones. El analista debe registrar una decisión:

- `Confirmado` habilita la siguiente fase documental.
- `Rechazado` exige una observación, mantiene bloqueada la generación y obliga
  a corregir o ejecutar un nuevo análisis.
- Un nuevo análisis restablece siempre el estado a `Pendiente`.

La revisión es individual por comprobación. Cada regla debe quedar como
`Confirmada` u `Observada` antes de registrar la decisión global. El endpoint
de generación exige estado global `Confirmado`, completa el Word oficial y lo
convierte a PDF. Las plantillas fuente se verifican por hash antes y después y
nunca se sobrescriben.

## Casos de regresión

La hoja `06_Casos_Prueba` documenta antecedentes de consulta: campos vacíos,
instrucciones internas, bloques duplicados, equivalencias de cuantía, orden de
secciones y cadenas de poderes. No es una fuente de ejecución. Las pruebas de
desarrollo usan archivos sintéticos controlados; los resultados de la interfaz
se guardan en `Salida/{id_seleccion}`.

Las pruebas deterministas de validación y consolidación se ejecutan con:

```powershell
python -m unittest tests.test_motor_juridico -v
```
