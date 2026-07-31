# MVP - Gestor Inteligente de Operaciones Jurídicas (GIOJ)

## Objetivo

Construir un sistema local capaz de analizar automáticamente expedientes de conformidad jurídica para escrituras públicas, reproduciendo el flujo de trabajo de un analista jurídico y reduciendo significativamente el tiempo de revisión.

El MVP debe permitir realizar el proceso completo desde la carga de documentos hasta la generación del certificado correspondiente.

---

# Flujo del usuario

El usuario únicamente realizará las siguientes acciones:

1. Abrir el sistema.

2. Presionar "Nuevo Proyecto".

3. Seleccionar una carpeta de expediente.

4. Presionar "Analizar".

5. Revisar el resultado del análisis.

6. Presionar "Generar Documento".

7. Obtener un PDF de Conformidad o No Conformidad.

No deben existir pasos adicionales.

---

# Entrada

Cada expediente contiene una carpeta llamada:

01_Documentos

Dentro de ella existirán uno o varios archivos PDF.

Ejemplos:

- Escritura de compraventa
- Escritura de hipoteca
- Certificado de tradición
- Promesa de compraventa
- Poderes
- Documentos de identidad
- Otros documentos relacionados

El sistema debe identificar automáticamente el tipo de documento.

No se solicitará al usuario clasificarlos manualmente.

---

# Proceso interno

El sistema debe ejecutar el siguiente flujo:

1. OCR.

2. Extracción de datos.

3. Normalización.

4. Validación de reglas.

5. Comparación jurídica.

6. Generación del concepto.

7. Generación del documento.

Todo el proceso debe ser automático.

---

# Salida

La interfaz mostrará:

- Resumen del análisis.

- Concepto jurídico resumido.

- Información relevante identificada.

- Estado de cada validación.

Cada validación debe indicar:

Cumple

No cumple

Cuando una regla no se cumpla deberá indicarse:

- Documento donde ocurrió.

- Página.

- Campo comparado.

- Valor esperado.

- Valor encontrado.

Esto permitirá realizar la revisión manual rápidamente.

---

# Generación documental

Si todas las reglas cumplen:

Generar Certificado de Conformidad.

Si existe al menos una regla incumplida:

Generar Certificado de No Conformidad.

En este último caso deberá construirse automáticamente una lista numerada de todas las observaciones encontradas.

---

# Arquitectura

Toda la lógica del sistema deberá obtenerse desde:

Arquitectura/Arquitectura.xlsx

No deben existir reglas jurídicas programadas directamente en el código.

Toda modificación futura deberá realizarse desde la arquitectura.

---

# Base de conocimiento

El MVP no utilizará inicialmente la carpeta Casos.

Únicamente deberá quedar preparada para futuras versiones.

El sistema sí utilizará:

- Poderes

- Minutas

- Entidades

- Configuración

como fuentes auxiliares.

---

# Objetivo del desarrollo

El objetivo NO es construir un sistema genérico de análisis documental.

El objetivo es reproducir el trabajo realizado actualmente por un analista jurídico del despacho.

Todas las decisiones deberán orientarse a facilitar el trabajo del analista y reducir el tiempo de elaboración del certificado.

---

# Restricciones

No modificar:

- Plantillas Word.

- Arquitectura.xlsx.

- Configuración.

Toda la información deberá ser consumida desde dichos archivos.

---

# Resultado esperado

Al finalizar el MVP deberá ser posible:

Seleccionar un expediente.

↓

Analizar automáticamente todos los documentos.

↓

Validar las reglas jurídicas.

↓

Mostrar el resultado.

↓

Generar automáticamente el certificado correspondiente.

Sin intervención adicional del usuario.