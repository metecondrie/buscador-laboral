# Anexo · casos de clasificación anonimizados

Material de apoyo para la revisión independiente. **No contiene ofertas reales**:
los textos son sintéticos, redactados para reproducir un comportamiento concreto
del motor, sin nombres de empresa, sin URLs y sin identificadores de aviso.

Cada caso dice qué se espera hoy (`rules-3.1.0`) y qué convendría revisar.

Terminología (corregida el 2026-11-10 · V04; antes estaba invertida):

- **[FP] falso positivo**: el motor **acepta** (o deja pasar) algo que debería
  rechazar.
- **[FN] falso negativo**: el motor **rechaza** algo que debería aceptar.
- **[duda]**: el motor no acepta ni rechaza; lo manda a revisión. Una oferta
  `doubtful` **no** es un falso negativo: es una decisión pendiente.

Los casos A, C y M cambiaron de comportamiento con la revisión del 2026-11-10.
Se conserva el diagnóstico original y se agrega el estado nuevo, sin reescribir
el resultado que se observó entonces.

El comportamiento esperado está codificado en
`tests/test_clasificacion_casos_sinteticos.py`. Si una mejora cambia alguno de
esos comportamientos, ese test falla: es la señal de que el cambio es
deliberado y no un efecto colateral.

## Perfil de referencia de los casos

Todos los casos usan el mismo perfil sintético, definido dentro del archivo de
pruebas. No es el perfil real ni el de ejemplo del repositorio: es uno mínimo,
escrito para que el resultado no dependa de datos de ninguna persona.

- habilidades demostradas: SQL, Python, Excel;
- inglés B2, español nativo;
- 1 año de experiencia, nivel junior;
- residencia Argentina, remoto obligatorio, zona presencial «La Plata»;
- categorías: Data Analyst, Business Analyst, BI Analyst, Reporting Analyst,
  SQL Analyst, Data Operations, Research Analyst, VA/Data Entry, Customer Support.

## Caso A · idioma en lista «plus» **[FN, ya corregido]**

> **Aviso.** Customer Support Specialist. Región: Anywhere in the World.
> «SQL required. Excel required. Bilingual (English/Spanish or Italian, Dutch,
> French) is a plus.»

**Comportamiento actual:** `eligible`. El texto enumera idiomas **alternativos**
dentro de un «is a plus», no una exigencia. El motor no lo toma como requisito.

**Qué mirar:** el caso histórico que lo motivaba (un aviso con «bilingual
English/Spanish or Italian, Dutch, French is a plus» descartado por «exige
francés») está **resuelto** en `rules-3.1.0`. Conviene confirmarlo con la prueba
`test_idioma_en_lista_plus_no_es_requisito` y no volver atrás.

## Caso B · zona horaria restrictiva en el cuerpo **[resuelto]**

> **Aviso.** Customer Support Specialist. Región: Anywhere in the World.
> «SQL required. Excel required. This position is open to candidates in Central,
> Mountain and Eastern time zones only, Sunday to Thursday 8:30 to 17 CST.»

**Comportamiento actual:** `incompatible`, motivo «el aviso exige residir en una
zona horaria restringida: no admite Argentina».

**Qué mirar:** la restricción del cuerpo **sí** se lee, aunque la fuente declare
alcance global. Es el contrapeso del caso C.

## Caso C · el cuerpo contradice a la fuente y gana la fuente **[FN · corregido el 2026-11-10: ahora va a `doubtful`]**

> **Aviso.** Customer Support Specialist. Región declarada por la fuente:
> `United States`.
> «SQL required. Excel required. This is a Worldwide Remote position open to
> applicants from all countries.»

**Comportamiento observado en `rules-3.1.0`:** `incompatible`, motivo «la fuente
restringe la ubicación a United States».

**Comportamiento desde el 2026-11-10:** `doubtful`, con el conflicto nombrado
(«metadatos contradictorios, confirmar el alcance»). No se acepta solo ni se
descarta por la etiqueta.

**Por qué era un falso negativo:** el cuerpo dice explícitamente que se acepta a
todo el mundo. El motor descartaba por el campo de la fuente y **no** dejaba
registro de que el cuerpo lo contradice. En el catálogo real hay **405 ofertas** con
alcance global declarado que aun así quedan descartadas (ver
`docs/INFORME_CLASIFICACION.md` §7.1): este caso es el mecanismo probable.

**Preguntas para la revisión:**

1. ¿Debería el cuerpo del aviso poder contradecir a la fuente, o al revés?
2. Si no puede, ¿debería la oferta pasar a `doubtful` en vez de `incompatible`,
   para que una persona la revise?
3. ¿Conviene registrar la contradicción como incertidumbre, aunque no cambie
   el veredicto?

**Dato relevante:** el motor **sí** sabe detectar una contradicción parecida
cuando la etiqueta de la fuente enumera países y el cuerpo dice «desde
cualquier punto de las Américas»: en ese caso el motivo es «la etiqueta enumera
países pero el aviso declara trabajo desde cualquier punto de las Américas:
contradicción sin resolver» y la oferta queda **dudosa**, no descartada. Existe,
o sea, el mecanismo de contradicción sin resolver para un caso particular. Lo
que falta es el caso general del ejemplo C, donde la fuente declara un solo
territorio y el cuerpo declara alcance mundial. La pregunta para la revisión es
si conviene generalizar el mecanismo que ya existe.

## Caso D · híbrido fuera de la zona **[correcto]**

> **Aviso.** Data Analyst. Región: Berlin.
> «SQL required. Excel required. Hybrid 3 days per week in the office.»

**Comportamiento actual:** `incompatible`, motivo «híbrido fuera de tu zona».

**Qué mirar:** correcto dado el perfil. El mismo aviso con `region` en la zona
presencial del perfil pasa a `doubtful` («está en tu zona, pero no es remoto»).

## Caso E · formación exigida **[FN, abierto]**

> **Aviso.** Data Analyst. Región: Anywhere in the World.
> «SQL required. Excel required. A bachelor's degree is required.»

**Comportamiento actual:** `incompatible`, motivo «exige título terminado: título
universitario obligatorio».

**Por qué es un falso negativo:** el motor descarta por la sola presencia de un
título, sin mirar **qué** título ni de qué disciplina. En el catálogo real, la
dimensión `formacion` es la principal causa de descarte en **103** ofertas.

**Preguntas para la revisión:**

1. ¿El título es exigible en un rol de datos, o sólo en uno de negocio?
2. ¿Debería la disciplina del título pesar distinto según la categoría?
3. ¿Qué pasa con títulos en otro idioma o con «degree or equivalent experience»?

## Caso F · formación preferida **[correcto]**

> **Aviso.** Data Analyst. Región: Anywhere in the World.
> «SQL required. Excel required. A bachelor's degree is preferred.»

**Comportamiento actual:** `doubtful`, motivo «formación: título universitario
preferido».

**Qué mirar:** el motor distingue bien `required` de `preferred`. Conviene que
esas dos palabras sigan siendo distinguibles después de cualquier cambio.

## Caso G · experiencia por encima del perfil **[correcto]**

> **Aviso.** Data Analyst. Región: Anywhere in the World.
> «SQL required. Excel required. 8+ years of experience.»

**Comporamiento actual:** `incompatible`, motivo «pide 8+ años de experiencia».

**Qué mirar:** la regla de «excepción por competencias» (entre 2 y 7 años con
cobertura suficiente **no** excluye) está en el mismo archivo. Con 8 años el
descart es correcto; entre 2 y 7 depende de la cobertura de habilidades.

## Caso H · categoría ajena **[correcto]**

> **Aviso.** Paid Ads Specialist. Región: Anywhere in the World.
> «SQL required. Excel required. Run Meta and Google ads campaigns.»

**Comportamiento actual:** `incompatible`, motivo «el título no es afín a las
categorías del perfil».

**Qué mirar:** correcto para este puesto. Pero es el mismo mecanismo que
descarta las **2.330 ofertas sin categoría asignada** (91,6 % del catálogo). El
detector de categorías es el mayor bloque de descarte y el que más puede estar
fallando en títulos legítimos.

## Caso I · remoto sin territorio publicado **[duda, correcto]**

> **Aviso.** Data Analyst. Sin región declarada.
> «SQL required. Excel required. This is a fully remote position.»

**Comportamiento actual:** `doubtful`, motivo «la fuente no publica el territorio
admitido». **No es un falso negativo**: el motor no rechaza la oferta, la manda a
revisión. Antes este caso figuraba como FN, lo que inflaba el conteo de errores.

**Por qué importa:** las **22 dudosas** del catálogo están todas frenadas por
información ausente (idioma no declarado, experiencia no declarada, territorio no
publicado). El motor no inventa datos, y está bien que no lo haga; pero el
resultado es que el 99 % del catálogo muere en una fase que no es de decisión.

**Preguntas para la revisión:**

1. ¿Es correcto que la duda se resuelva con una consulta al aviso original?
2. ¿Qué información mínima justificaría subir una `doubtful` a `eligible`?
3. ¿Conviene un tercer estado («candidato a revisión manual»)?

## Caso J · inglés fluido exigido con perfil B2 **[resuelto]**

> **Aviso.** Customer Support Specialist. Región: Anywhere in the World.
> «SQL required. Excel required. Fluent spoken English is required.»

**Comportamiento actual:** `doubtful`, motivo «exige inglés fluido o nativo; el
perfil declara B2». **No** excluye.

**Qué mirar:** correcto. Un requisito de idioma incumplido bloquea, pero deja
la oferta en `doubtful` y no la descarta. Conviene que siga así.

## Caso K · aviso con datos mínimos **[línea base]**

> **Aviso.** Data Analyst. Región: Anywhere in the World.
> «SQL required.»

**Comportamiento actual:** `eligible`, confianza `media`.

**Qué mirar:** línea base. Si una mejora sube la confianza, este caso cambia.

## Caso L · equipo remoto mundial declarado en el cuerpo **[resuelto]**

> **Aviso.** Technical Customer Support. Sin región declarada.
> «SQL required. Excel required. Fully remote worldwide team. No years of
> experience required.»

**Comportamiento actual:** `eligible`, motivo territorial «el texto declara
alcance mundial».

**Qué mirar:** el cuerpo **sí** sirve cuando la fuente no dice nada (contraste
con el caso C, donde la fuente sí dice algo y el cuerpo no puede contradecirla).
Esta asimetría es el punto central a revisar.

## Matriz rápida

| Caso | Situación | Hoy | Preocupación |
| --- | --- | --- | --- |
| A | idioma en lista «plus» | eligible | FN ya corregido |
| B | zona horaria en el cuerpo | incompatible | correcto |
| C | cuerpo contradice a la fuente | doubtful | FN corregido: conflicto explícito |
| D | híbrido fuera de zona | incompatible | correcto |
| E | título exigido sin alternativa | incompatible | FN abierto: revisar disciplina, no abolir el requisito |
| F | título preferido | doubtful | correcto |
| G | 8+ años | incompatible | correcto |
| H | categoría ajena | incompatible | correcto en sí, ver §6 del informe |
| I | remoto sin territorio | doubtful | duda correcta (no es FN) |
| J | inglés fluido con B2 | doubtful | correcto |
| K | datos mínimos | eligible | línea base |
| L | mundial en el cuerpo, fuente muda | eligible | correcto |
| M | aviso corto en inglés | duda de idioma declarada | FP corregido: deja trazabilidad |

## Caso M · el aviso corto no deja rastro de idioma **[FP · corregido el 2026-11-10: deja trazabilidad]**

> **Aviso.** Customer Support Specialist. Región: Anywhere in the World.
> «SQL required. Excel required.»

**Comportamiento observado en `rules-3.1.0`:** `eligible`, y **ninguna razón de
idioma**.

**Comportamiento desde el 2026-11-10:** sigue sin bloquear, pero declara
«idioma no evaluado» entre las razones. El aviso ya no pasa como si el idioma
hubiera sido aprobado. Un aviso
ligeramente más largo con el mismo english
(«… We are looking for a customer support specialist to join our team.») sí
genera la razón «el aviso está en inglés pero no declara el nivel exigido».

**Por qué importa:** la detección de idioma dominante necesita texto suficiente.
Cuando no alcanza, el resultado es «desconocido» y **no queda ningún rastro** de
que el idioma nunca llegó a evaluarse. Como las 22 dudosas del catálogo tienen
**todas** una razón de idioma, la banda accionable está sesgada hacia los
avisos con más texto: los avisos más escuetos pasan sin dejar marca.

**Preguntas para la revisión:**

1. ¿Un aviso sin idioma detectado debería quedar en `doubtful` por falta de
   evidencia, o con la confianza rebajada?
2. ¿Conviene registrar «idioma no evaluado» como incertidumbre explícita, en
   lugar de dejarlo en silencio?

