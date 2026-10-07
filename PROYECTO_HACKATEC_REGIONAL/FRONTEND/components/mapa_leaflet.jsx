// Mapa Leaflet: cámaras, alertas (rojo = abierta, verde = resuelta), patrullas
// (azul: libres en su base o en camino por la ruta de calles), rondines sugeridos
// (anillo azul) y capa de calor. Se usa Leaflet directamente (sin react-leaflet)
// para exponer a Reflex una API pequeña basada en props.
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Alertas en tonos de rojo: la severidad se lee en el tono, no en el tamaño.
const ROJO_SEVERIDAD = { critica: "#dc2626", alta: "#ef4444", media: "#f87171", baja: "#fca5a5" };
const AZUL = "#3b82f6";
const VERDE = "#22c55e";
// Una patrulla que ya llegó se sigue viendo en el lugar unos minutos.
const PATRULLA_VISIBLE_TRAS_LLEGAR_MS = 5 * 60 * 1000;

const CSS = `
.so-mapa { width: 100%; border-radius: 6px; background: #18181b; z-index: 0; }
.so-mapa .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(0.82) contrast(0.92) saturate(0.45); }
.so-mapa .leaflet-tooltip { background: #18181b; color: #ececee; border: 1px solid #2a2a2f; border-radius: 4px;
  box-shadow: none; font: 12px/1.4 Inter, system-ui, sans-serif; }
.so-mapa .leaflet-tooltip::before { display: none; }
.so-alerta { display: block; width: 11px; height: 11px; border-radius: 50%; background: var(--c);
  border: 2px solid #f8fafc; cursor: pointer; box-sizing: content-box; }
.so-alerta.so-sel { box-shadow: 0 0 0 4px rgba(248, 250, 252, 0.28); animation: so-latido 1.8s ease-out infinite; }
.so-resuelto { display: block; width: 11px; height: 11px; border-radius: 50%; background: ${VERDE};
  border: 2px solid #f8fafc; cursor: pointer; box-sizing: content-box; }
.so-camara { display: block; width: 8px; height: 8px; border-radius: 2px; background: #d4d4d8; border: 1px solid #18181b; }
.so-camara.so-inactiva { background: #52525b; }
.so-rondin { display: block; width: 9px; height: 9px; border-radius: 50%; border: 2px solid ${AZUL}; background: transparent; }
.so-unidad { display: block; width: 11px; height: 11px; border-radius: 50%; background: ${AZUL};
  border: 2px solid #f8fafc; box-sizing: content-box; }
.so-patrulla { display: block; width: 13px; height: 13px; border-radius: 50%; background: ${AZUL};
  border: 2px solid #f8fafc; box-sizing: content-box; box-shadow: 0 0 0 0 rgba(59,130,246,.55);
  animation: so-sirena 1.4s ease-out infinite; }
.so-patrulla.so-llego { animation: none; box-shadow: 0 0 0 3px rgba(34,197,94,.5); }
@keyframes so-sirena { 70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@keyframes so-latido { 70% { box-shadow: 0 0 0 7px transparent; } 100% { box-shadow: 0 0 0 4px rgba(248,250,252,.28); } }
@media (prefers-reduced-motion: reduce) { .so-patrulla, .so-alerta.so-sel { animation: none; } }
`;

// Distancia aproximada en metros entre [lat, lng]: suficiente para repartir el avance.
function distancia(a, b) {
  const k = 111320;
  const dx = (b[1] - a[1]) * k * Math.cos((a[0] * Math.PI) / 180);
  const dy = (b[0] - a[0]) * k;
  return Math.hypot(dx, dy);
}

// Punto de la ruta a la `fraccion` (0-1) de su longitud total.
function sobreRuta(ruta, acum, fraccion) {
  const meta = acum[acum.length - 1] * fraccion;
  let i = 1;
  while (i < acum.length - 1 && acum[i] < meta) i++;
  const tramo = acum[i] - acum[i - 1] || 1;
  const t = Math.min(1, Math.max(0, (meta - acum[i - 1]) / tramo));
  return [ruta[i - 1][0] + (ruta[i][0] - ruta[i - 1][0]) * t, ruta[i - 1][1] + (ruta[i][1] - ruta[i - 1][1]) * t];
}

function icono(html, lado) {
  return L.divIcon({ className: "", html, iconSize: [lado, lado], iconAnchor: [lado / 2, lado / 2] });
}

export function MapaLeaflet({
  centro,
  zoom = 16,
  cuadrantes = [],
  camaras = [],
  alertas = [],
  rondines = [],
  unidades = [],
  patrullas = [],
  foco = [],
  calor = [],
  seleccion = "",
  altura = "380px",
  onAlerta,
}) {
  const nodo = useRef(null);
  const mapa = useRef(null);
  const capas = useRef(null);
  const alClic = useRef(onAlerta);
  alClic.current = onAlerta;

  useEffect(() => {
    const m = L.map(nodo.current, { center: centro, zoom, attributionControl: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(m);
    capas.current = {
      cuadrantes: L.layerGroup().addTo(m),
      calor: L.layerGroup().addTo(m),
      camaras: L.layerGroup().addTo(m),
      rondines: L.layerGroup().addTo(m),
      rutas: L.layerGroup().addTo(m),
      unidades: L.layerGroup().addTo(m),
      alertas: L.layerGroup().addTo(m),
      patrullas: L.layerGroup().addTo(m),
    };
    mapa.current = m;
    const observador = new ResizeObserver(() => m.invalidateSize());
    observador.observe(nodo.current);
    return () => {
      observador.disconnect();
      m.remove();
      mapa.current = null;
    };
  }, []);

  // El centro se conoce hasta que carga el inventario de cámaras.
  useEffect(() => {
    if (mapa.current) mapa.current.setView(centro, mapa.current.getZoom(), { animate: false });
  }, [centro[0], centro[1]]);

  useEffect(() => {
    const capa = capas.current.cuadrantes.clearLayers();
    cuadrantes.forEach((q) =>
      L.polygon(q.coords, { color: "#3f3f46", weight: 1, dashArray: "3 5", fill: false })
        .bindTooltip(q.nombre, { sticky: true })
        .addTo(capa),
    );
  }, [cuadrantes]);

  useEffect(() => {
    const capa = capas.current.camaras.clearLayers();
    camaras.forEach((c) =>
      L.marker([c.lat, c.lng], {
        icon: icono(`<span class="so-camara${c.activa ? "" : " so-inactiva"}"></span>`, 8),
        keyboard: false,
      })
        .bindTooltip(`${c.nombre}${c.activa ? "" : " (fuera de servicio)"}`)
        .addTo(capa),
    );
  }, [camaras]);

  useEffect(() => {
    const capa = capas.current.alertas.clearLayers();
    alertas.forEach((a) => {
      const sel = a.id === seleccion ? " so-sel" : "";
      const resuelto = a.caso === "resuelto";
      const html = resuelto
        ? `<span class="so-resuelto${sel}"></span>`
        : `<span class="so-alerta${sel}" style="--c:${ROJO_SEVERIDAD[a.severidad] || ROJO_SEVERIDAD.alta}"></span>`;
      const estado = { pendiente: "pendiente", en_camino: "unidad en camino", resuelto: "atendido / resuelto" }[a.caso] || "";
      L.marker([a.lat, a.lng], {
        icon: icono(html, 15),
        title: `${a.tipo_txt}, severidad ${a.sev_txt}, ${estado}`,
        zIndexOffset: resuelto ? 600 : 1000,
      })
        .bindTooltip(`${a.tipo_txt} · ${a.sev_txt} · ${estado} · ${a.hora}`)
        .on("click", () => alClic.current && alClic.current(a.id))
        .addTo(capa);
    });
  }, [alertas, seleccion]);

  useEffect(() => {
    const capa = capas.current.rondines.clearLayers();
    rondines.forEach((r) =>
      L.marker([r.lat, r.lng], { icon: icono('<span class="so-rondin"></span>', 13), keyboard: false, zIndexOffset: 500 })
        .bindTooltip(r.texto)
        .addTo(capa),
    );
  }, [rondines]);

  // Patrullas libres en su base (las que van en camino las dibuja la animación).
  useEffect(() => {
    const capa = capas.current.unidades.clearLayers();
    unidades
      .filter((u) => u.estado === "libre")
      .forEach((u) =>
        L.marker([u.lat, u.lng], { icon: icono('<span class="so-unidad"></span>', 15), keyboard: false, zIndexOffset: 1500 })
          .bindTooltip(`${u.id} · libre · ${u.base}`)
          .addTo(capa),
      );
  }, [unidades]);

  // --- Patrullas en camino: se crean/actualizan al cambiar la lista; un bucle de
  // animación las mueve por su ruta según la hora real de salida y de llegada.
  const enRuta = useRef(new Map());
  useEffect(() => {
    const vigentes = new Set();
    const ahora = Date.now();
    patrullas.forEach((p) => {
      const llego = p.estado === "resuelto";
      if (llego && ahora - (p.llegada_real_ms || p.llegada_ms) > PATRULLA_VISIBLE_TRAS_LLEGAR_MS) return;
      if (!p.ruta || p.ruta.length < 2) return;
      vigentes.add(p.id);
      let u = enRuta.current.get(p.id);
      if (!u) {
        const acum = [0];
        for (let i = 1; i < p.ruta.length; i++) acum.push(acum[i - 1] + distancia(p.ruta[i - 1], p.ruta[i]));
        u = {
          linea: L.polyline(p.ruta, { color: AZUL, weight: 3, opacity: 0.75, dashArray: "6 6" }).addTo(capas.current.rutas),
          marca: L.marker(p.ruta[0], { icon: icono('<span class="so-patrulla"></span>', 17), zIndexOffset: 3000, keyboard: false })
            .bindTooltip(`${p.unidad} · en camino`)
            .addTo(capas.current.patrullas),
          acum,
        };
        enRuta.current.set(p.id, u);
        // Recién despachada: encuadrar toda la ruta para ver a la unidad acercarse.
        if (!llego && mapa.current && ahora - p.inicio_ms < 15000) {
          mapa.current.flyToBounds(u.linea.getBounds(), { padding: [40, 40], duration: 1.2, maxZoom: 17 });
        }
      }
      u.datos = p;
      if (llego) {
        u.linea.setStyle({ opacity: 0 });
        u.marca.setIcon(icono('<span class="so-patrulla so-llego"></span>', 17));
        u.marca.setTooltipContent(`${p.unidad} · en el lugar · caso resuelto`);
      }
    });
    for (const [id, u] of enRuta.current) {
      if (!vigentes.has(id)) {
        capas.current.rutas.removeLayer(u.linea);
        capas.current.patrullas.removeLayer(u.marca);
        enRuta.current.delete(id);
      }
    }
  }, [patrullas]);

  useEffect(() => {
    let cuadro;
    const animar = () => {
      const ahora = Date.now();
      for (const u of enRuta.current.values()) {
        const p = u.datos;
        const fraccion = p.estado === "resuelto" ? 1 : Math.min(1, Math.max(0, (ahora - p.inicio_ms) / (p.llegada_ms - p.inicio_ms)));
        u.marca.setLatLng(sobreRuta(p.ruta, u.acum, fraccion));
      }
      cuadro = requestAnimationFrame(animar);
    };
    cuadro = requestAnimationFrame(animar);
    return () => cancelAnimationFrame(cuadro);
  }, []);

  // Violencia detectada: el mapa vuela al lugar.
  useEffect(() => {
    if (foco.length === 3 && mapa.current) mapa.current.flyTo([foco[0], foco[1]], 17, { duration: 1.2 });
  }, [foco[2]]);

  useEffect(() => {
    const elegida = alertas.find((a) => a.id === seleccion);
    if (!elegida || !mapa.current) return;
    // Solo se desplaza si la alerta elegida queda fuera (o al borde) de la vista.
    const punto = L.latLng(elegida.lat, elegida.lng);
    if (!mapa.current.getBounds().pad(-0.15).contains(punto)) mapa.current.panTo(punto);
  }, [seleccion]);

  useEffect(() => {
    let vigente = true;
    const capa = capas.current.calor.clearLayers();
    if (!calor.length) return;
    // leaflet.heat se registra sobre el `L` global, por eso se importa después.
    window.L = L;
    import("leaflet.heat").then(() => {
      if (!vigente) return;
      L.heatLayer(calor, {
        radius: 16,
        blur: 14,
        minOpacity: 0.3,
        max: Math.max(4, calor.length / 40),
        gradient: { 0.3: "#7f1d1d", 0.6: "#dc2626", 0.85: "#f97316", 1: "#fde68a" },
      }).addTo(capa);
    });
    return () => {
      vigente = false;
    };
  }, [calor]);

  return (
    <>
      <style>{CSS}</style>
      <div ref={nodo} className="so-mapa" style={{ height: altura }} role="application" aria-label="Mapa del Tecnológico de Mérida" />
    </>
  );
}
