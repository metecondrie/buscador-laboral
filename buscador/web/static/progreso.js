/* Búsqueda manual: lanzar la corrida y seguir el progreso real.
 *
 * El estado nunca se guarda en el navegador: cada consulta a /progreso.json
 * devuelve lo que dice la base. Recargar la página, abrir otra pestaña o
 * cambiar de vista no pierde nada, y dos pestañas muestran lo mismo.
 *
 * Se eligió consulta periódica en lugar de SSE. El avance cambia en pasos
 * gruesos (una fuente tarda segundos) y el dato ya está persistido: empujar
 * eventos no agregaría fidelidad, sí una conexión abierta por pestaña en un
 * servidor sincrónico y un flujo difícil de probar con el cliente de pruebas.
 */
(function () {
  "use strict";

  const INTERVALO_MS = 1200;
  const MIN_ENTRE_REFRESCOS_MS = 1000;

  const estado = {
    ultimo: null,
    versionLista: null,
    ultimoRefresco: 0,
    timer: null,
    esperandoHasta: 0,
    enviando: false,
  };

  const $ = (sel) => document.querySelector(sel);

  function texto(n) {
    return (n === null || n === undefined) ? "—" : Number(n).toLocaleString("es-AR");
  }

  function duracion(ms) {
    if (ms === null || ms === undefined) return "—";
    const s = Math.round(ms / 1000);
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    const r = s % 60;
    return r ? m + " min " + r + " s" : m + " min";
  }

  function fase(estado) {
    if (!estado) return { clave: "inactiva", texto: "Sin búsquedas todavía" };
    if (estado.activo) {
      const f = estado.fuentes || {};
      const cola = (estado.cola && estado.cola.queued) || 0;
      if (!f.total) return { clave: "preparando", texto: "Preparando la búsqueda" };
      if (f.ejecutando > 0) {
        return {
          clave: "fuentes",
          texto: "Buscando fuentes · " + (f.actual_nombre || f.actual || "…"),
        };
      }
      if (cola > 0) return { clave: "analizando", texto: "Analizando ofertas" };
      return { clave: "fuentes", texto: "Buscando fuentes" };
    }
    if (estado.estado === "completed") return { clave: "finalizada", texto: "Búsqueda finalizada" };
    if (estado.estado === "cancelled") return { clave: "cancelada", texto: "Búsqueda cancelada" };
    if (estado.estado === "failed") return { clave: "fallida", texto: "La búsqueda falló" };
    if (estado.estado === "abandoned") {
      return { clave: "abandonada", texto: "La búsqueda quedó interrumpida" };
    }
    return { clave: "inactiva", texto: "Sin búsqueda en curso" };
  }

  function pintarCabecera(s) {
    const pill = $("#progreso-cabecera");
    if (!pill) return;
    if (s && s.activo) {
      const f = s.fuentes || {};
      pill.hidden = false;
      pill.textContent = "Buscando " + f.procesadas + "/" + f.total +
        (f.actual ? " · " + f.actual : "");
      pill.classList.add("activo");
    } else {
      pill.hidden = true;
      pill.textContent = "";
      pill.classList.remove("activo");
    }
  }

  function pintarPanel(s) {
    const panel = $("#panel-busqueda");
    if (!panel) return;

    const f = s.fuentes || {};
    const o = s.ofertas || {};
    const ia = s.ia || {};
    const ficha = fase(s);

    const faseEl = $("#busqueda-fase");
    if (faseEl) {
      faseEl.textContent = ficha.texto;
      faseEl.dataset.fase = ficha.clave;
    }

    const barra = $("#busqueda-barra");
    const relleno = $("#busqueda-relleno");
    if (barra && relleno) {
      const pct = Math.round((f.fraccion || 0) * 100);
      barra.hidden = !f.total;
      relleno.style.width = pct + "%";
      barra.setAttribute("aria-valuenow", String(pct));
    }
    const detalle = $("#busqueda-fuentes");
    if (detalle) {
      detalle.textContent = f.total
        ? f.procesadas + " de " + f.total + " fuentes · " +
          f.completadas + " correctas · " + f.fallidas + " con error" +
          (f.canceladas ? " · " + f.canceladas + " sin consultar" : "") +
          (f.pendientes ? " · " + f.pendientes + " pendientes" : "")
        : "Todavía no hay fuentes planificadas.";
    }

    const set = (sel, valor) => { const el = $(sel); if (el) el.textContent = valor; };
    set("#c-revisadas", texto(o.revisadas));
    set("#c-nuevas", texto(o.nuevas));
    set("#c-duplicadas", texto(o.duplicadas));
    set("#c-elegibles", texto(o.elegibles));
    set("#c-dudosas", texto(o.dudosas));
    set("#c-incompatibles", texto(o.incompatibles));

    const iaEl = $("#busqueda-ia");
    if (iaEl) {
      let t;
      if (!ia.habilitada) {
        t = "IA desactivada · nada se envía fuera de la máquina";
      } else {
        t = "IA " + (ia.analizando > 0 ? "analizando ahora" : "en espera") +
          " · " + ia.pendientes + " pendiente(s) · " +
          ia.en_corrida + " analizada(s) en esta búsqueda · " +
          (ia.cuota && ia.cuota.disponible
            ? "cuota gratuita disponible"
            : "sin cuota: " + ((ia.cuota && ia.cuota.motivo) || "no disponible"));
      }
      iaEl.textContent = t;
    }

    const boton = $("#btn-buscar");
    if (boton) {
      boton.disabled = !!s.activo || estado.enviando;
      boton.textContent = s.activo ? "Buscando…" : "Buscar ahora";
    }
    const cancelar = $("#btn-cancelar");
    if (cancelar) cancelar.hidden = !s.activo;

    const colaEl = $("#busqueda-cola");
    if (colaEl) {
      const cola = (s.cola && s.cola.queued) || 0;
      colaEl.textContent = s.activo && cola > 0
        ? cola + " oferta(s) esperando clasificación"
        : "";
    }

    const resumen = $("#busqueda-resumen");
    if (resumen) {
      const r = s.resumen || {};
      const finalizada = !s.activo && (s.estado === "completed" || s.estado === "cancelled");
      if (finalizada && r && r.fuentes_total !== undefined) {
        const errores = (r.errores || []);
        resumen.hidden = false;
        resumen.innerHTML =
          "<strong>" + (s.estado === "cancelled" ? "Búsqueda cancelada" : "Búsqueda finalizada") +
          "</strong> · " + duracion(r.duracion_ms) +
          " · " + (r.fuentes_ok || 0) + "/" + (r.fuentes_total || 0) + " fuentes correctas" +
          (errores.length
            ? " · " + errores.length + " con error: " +
              errores.map((e) => (e.nombre || e.source_id) + " (" + (e.motivo || "error") + ")").join(", ")
            : " · sin errores") +
          " · " + texto(r.nuevas) + " nuevas" +
          " · " + texto(r.candidatas_nuevas) + " candidatas nuevas" +
          " · en total " + texto(r.candidatas) + " candidatas (" +
          texto(r.elegibles) + " elegibles / " + texto(r.dudosas) + " dudosas)";
      } else {
        resumen.hidden = true;
        resumen.innerHTML = "";
      }
    }
  }

  async function refrescarLista(s) {
    const contenedor = $("#lista-ofertas");
    if (!contenedor) return;
    const clave = (s.ofertas && s.ofertas.clasificadas) || 0;
    if (estado.versionLista === null) { estado.versionLista = clave; return; }
    if (clave === estado.versionLista) return;
    const ahora = Date.now();
    if (ahora - estado.ultimoRefresco < MIN_ENTRE_REFRESCOS_MS) return;
    estado.ultimoRefresco = ahora;
    const anterior = estado.versionLista;
    estado.versionLista = clave;

    try {
      const url = new URL(window.location.href);
      url.searchParams.set("_", String(ahora));
      const respuesta = await fetch(url.toString(), { credentials: "same-origin" });
      if (!respuesta.ok) return;
      const doc = new DOMParser().parseFromString(await respuesta.text(), "text/html");
      const nuevo = doc.querySelector("#lista-ofertas");
      if (!nuevo) return;
      const previos = contenedor.querySelectorAll("article.card").length;
      contenedor.innerHTML = nuevo.innerHTML;
      const actuales = contenedor.querySelectorAll("article.card").length;
      const delta = actuales - previos;
      const aviso = $("#busqueda-nuevas");
      if (aviso && delta > 0) {
        aviso.textContent = delta + " resultado(s) incorporado(s)";
        aviso.hidden = false;
        window.setTimeout(() => { aviso.hidden = true; }, 6000);
      }
      const pie = $("#conteo-ofertas");
      if (pie) {
        const total = Number(pie.dataset.total || actuales);
        pie.textContent = actuales + " ofertas en esta pagina · " + total + " en la vista";
      }
      void anterior;
    } catch (e) {
      /* sin red local: la próxima consulta reintenta */
    }
  }

  async function consultar() {
    try {
      const r = await fetch("/progreso.json", {
        credentials: "same-origin",
        headers: { "Accept": "application/json" },
      });
      if (!r.ok) return;
      const s = await r.json();
      pintarCabecera(s);
      pintarPanel(s);
      refrescarLista(s);
      estado.ultimo = s;
    } catch (e) {
      /* servidor detenido: se reintenta en el próximo ciclo */
    }
  }

  function agendar() {
    if (estado.timer) window.clearTimeout(estado.timer);
    const activo = estado.ultimo && estado.ultimo.activo;
    // Tras pulsar el botón la corrida tarda un instante en publicarse en la
    // base: se sondea rápido un momento para no mostrar "sin búsqueda" justo
    // cuando el usuario acaba de iniciarla.
    const esperando = estado.esperandoHasta && Date.now() < estado.esperandoHasta;
    estado.timer = window.setTimeout(async () => {
      await consultar();
      agendar();
    }, (activo || esperando) ? INTERVALO_MS : 8000);
  }

  async function accion(url, cuerpo) {
    estado.enviando = true;
    const boton = $("#btn-buscar");
    if (boton) boton.disabled = true;
    try {
      const datos = new FormData();
      Object.entries(cuerpo).forEach(([k, v]) => datos.append(k, v));
      const r = await fetch(url, {
        method: "POST",
        body: datos,
        credentials: "same-origin",
        headers: { "Accept": "application/json" },
      });
      return await r.json().catch(() => ({}));
    } catch (e) {
      return { error: "no se pudo contactar al servidor" };
    } finally {
      estado.enviando = false;
    }
  }

  function conectar() {
    const panel = $("#panel-busqueda");
    const buscar = $("#btn-buscar");
    if (buscar && panel) {
      buscar.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const csrf = panel.dataset.csrf || "";
        const r = await accion("/buscar/ahora", { csrf });
        const nota = $("#busqueda-nota");
        if (r && r.iniciada) estado.esperandoHasta = Date.now() + 15000;
        if (nota) {
          if (r && r.iniciada) nota.textContent = "Búsqueda iniciada.";
          else if (r && r.motivo) nota.textContent = r.motivo;
          else nota.textContent = "No se pudo iniciar la búsqueda.";
        }
        await consultar();
        agendar();
      });
    }
    const cancelar = $("#btn-cancelar");
    if (cancelar && panel) {
      cancelar.addEventListener("click", async (ev) => {
        ev.preventDefault();
        if (!window.confirm("¿Cancelar la búsqueda en curso? Lo ya descargado y clasificado se conserva.")) {
          return;
        }
        const csrf = panel.dataset.csrf || "";
        const r = await accion("/buscar/cancelar", { csrf });
        const nota = $("#busqueda-nota");
        if (nota && r && r.motivo) nota.textContent = r.motivo;
        await consultar();
        agendar();
      });
    }
    consultar().then(agendar);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", conectar);
  } else {
    conectar();
  }
})();
