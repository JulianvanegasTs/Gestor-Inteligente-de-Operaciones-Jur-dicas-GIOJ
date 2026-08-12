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
selección. El límite total del MVP es 100 MB.

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
Conformidad`. El resultado incluye un `concepto_juridico` resumido y trazable
para revisión profesional.

El resultado se guarda en:

```text
Salida/{id_seleccion}/resultado_juridico.json
```

Para probarlo, ejecute:

```powershell
python -m unittest tests.test_motor_juridico -v
```

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
