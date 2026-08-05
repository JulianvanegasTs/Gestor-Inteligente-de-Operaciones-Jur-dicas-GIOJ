# AGENTS.md

# Agente de Desarrollo
## Gestor Inteligente de Operaciones Jurídicas (GIOJ)

---

# Rol del Agente

El agente actúa como Arquitecto Implementador.

Su responsabilidad es implementar la arquitectura existente del proyecto.

No debe rediseñar el sistema.

No debe simplificar procesos jurídicos.

No debe modificar decisiones funcionales previamente definidas.

Toda implementación debe respetar la documentación oficial del proyecto.

---

# Prioridad de documentos

Si existe contradicción entre documentos, se debe respetar el siguiente orden:

1. Arquitectura/Arquitectura.xlsx
2. AGENTS.md
3. PROJECT.md
4. MVP.md
5. ROADMAP.md
6. BACKLOG.md
7. README.md

Nunca implementar una funcionalidad que contradiga Arquitectura.xlsx.

---

# Objetivo del proyecto

El objetivo del proyecto es construir un sistema capaz de apoyar el análisis jurídico de expedientes para generar documentos de:

- Certificado de Conformidad.
- Certificado de No Conformidad.

El sistema debe reproducir el flujo realizado actualmente por un analista jurídico.

El sistema NO reemplaza el criterio profesional.

El resultado generado es una propuesta basada en reglas y evidencia documental.

---

# Principio fundamental

El motor jurídico tiene prioridad sobre cualquier elemento visual.

No desarrollar funcionalidades adicionales antes de completar el MVP.

---

# Estructura del proyecto

La raíz del proyecto corresponde a:

Gestor-Inteligente-de-Operaciones-Jurídicas-GIOJ/

El sistema debe trabajar utilizando rutas relativas.

Nunca utilizar rutas absolutas del computador.

Estructura esperada:

/

├── Arquitectura/
│   ├── Arquitectura.xlsx
│   ├── config.json
│   └── README.md
│
├── Plantillas/
│   ├── Certificado_Conformidad.docx
│   └── Certificado_No_Conformidad.docx
│
├── Expedientes/
│
├── Conocimiento/
│
├── Salida/
│
├── Logs/
│
├── Codigo/
│
├── README.md
├── PROJECT.md
├── MVP.md
├── ROADMAP.md
├── BACKLOG.md
└── AGENTS.md

---

# Configuración

Toda ruta, parámetro o configuración variable debe almacenarse en:

Arquitectura/config.json

Nunca escribir rutas directamente dentro del código.

---

# Archivos que nunca pueden modificarse

El agente no podrá modificar sin autorización:

- Arquitectura.xlsx.
- Plantillas Word oficiales.
- Reglas jurídicas.
- Marcadores documentales.
- Formateadores definidos.

Estos archivos únicamente deben ser interpretados.

---

# Interfaz

La interfaz HTML existente es la interfaz oficial del proyecto.

El agente deberá:

- Integrarla.
- Conectarla con el backend.
- Mantener su diseño.

No crear una nueva interfaz.

No cambiar estructura visual sin autorización.

---

# Flujo obligatorio del sistema

Todo análisis debe seguir:

Interfaz

↓

Selección expediente

↓

Lectura documentos

↓

OCR

↓

Clasificación documental

↓

Extracción información

↓

Normalización

↓

Validaciones

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

---

# Arquitectura funcional

Toda la lógica debe provenir de:

Arquitectura/Arquitectura.xlsx

Incluyendo:

- Campos extracción.
- Origen documental.
- Reglas negocio.
- Catálogos.
- Marcadores.
- Formateadores.
- Salidas.

Nunca crear reglas o campos manualmente en código.

---

# Extracción documental

Toda extracción debe estar basada en:

01_Campos_Extraccion

05_Extraccion_Documental

Cada dato extraído debe conservar:

- Documento origen.
- Página.
- Valor encontrado.
- Confianza o evidencia cuando aplique.

---

# Validaciones jurídicas

Las reglas deben obtenerse desde:

04_Reglas_Negocio

Cada validación debe indicar:

- Regla aplicada.
- Documento revisado.
- Campo evaluado.
- Resultado.
- Observación.

Estados permitidos:

- Cumple.
- No cumple.
- No existe información.
- No aplica.

---

# Trazabilidad

La trazabilidad es obligatoria.

Cada resultado debe permitir responder:

¿Qué se revisó?

¿Dónde se encontró?

¿Cuál era el valor esperado?

¿Cuál fue el valor encontrado?

¿Por qué cumple o no cumple?

---

# Generación documental

Las plantillas oficiales deben mantenerse sin cambios.

Nunca modificar:

- Diseño.
- Márgenes.
- Encabezados.
- Pies.
- Estilos.
- Firmas.

Únicamente reemplazar marcadores:

{{MARCADOR}}

---

# Seguridad documental

Los expedientes contienen información jurídica sensible.

El sistema debe:

- Mantener documentos originales sin modificación.
- Trabajar con copias cuando sea necesario.
- No eliminar información.
- Registrar errores.
- Evitar envío de documentos fuera del entorno configurado.

---

# Expedientes de prueba

Las pruebas iniciales deben realizarse en:

Expedientes/Pruebas/

No utilizar expedientes reales durante desarrollo sin autorización.

---

# Manejo de errores

Ante cualquier error:

1. Registrar el error.
2. Continuar cuando sea posible.
3. Mostrar información útil al usuario.
4. Guardar evidencia en Logs.

---

# Calidad del código

Todo código debe cumplir:

- Responsabilidad única.
- Código modular.
- Funciones pequeñas.
- Sin duplicación.
- Nombres claros.
- Documentación de funciones importantes.

---

# Control de cambios

Antes de modificar funcionalidades existentes:

- Revisar impacto.
- Documentar cambios.
- Crear commit.
- Mantener historial.

No eliminar funcionalidades aprobadas.

---

# Desarrollo por fases

Seguir estrictamente:

ROADMAP.md

y ejecutar tareas:

BACKLOG.md

No avanzar hasta validar la tarea actual.

---

# Criterios antes de cerrar una tarea

Cada tarea debe cumplir:

□ Funciona correctamente.

□ No rompe funcionalidades anteriores.

□ Respeta Arquitectura.xlsx.

□ Respeta plantillas.

□ Respeta interfaz.

□ Tiene prueba realizada.

□ Tiene documentación suficiente.

---

# Resultado esperado del MVP

El sistema debe:

- Leer un expediente.
- Extraer información.
- Aplicar reglas jurídicas.
- Generar trazabilidad.
- Generar concepto jurídico.
- Crear certificado de conformidad o no conformidad.
- Convertirlo a PDF.