// Mapa Leaflet de la ciudad: cuadrantes, cámaras, alertas (rojo = pendiente,
// verde = resuelta), patrullas en camino (azul, animadas por la ruta de calles),
// rondines sugeridos (anillo azul) y capa de calor.
// Se usa Leaflet directamente (sin react-leaflet) para exponer a Reflex una
// API pequeña basada en props.
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Toda alerta es un punto rojo de inseguridad; la severidad se lee en el tamaño.
const ROJO = "#ef4444";
const AZUL = "#3b82f6";
const VERDE = "#22c55e";
// Una patrulla que ya llegó se sigue viendo en el lugar unos minutos.
const PATRULLA_VISIBLE_TRAS_LLEGAR_MS = 5 * 60 * 1000;
const TAMANO_SEVERIDAD = { critica: 20, alta: 17, media: 14, baja: 12 };

const CSS = `
.so-mapa { width: 100%; border-radius: 16px; background: #0f172a; z-index: 0; }
.so-mapa .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(0.85) contrast(0.9) saturate(0.6); }
.so-mapa .leaflet-tooltip { background: #0f172a; color: #f8fafc; border: 1px solid #334155; box-shadow: none; }
.so-mapa .leaflet-tooltip::before { display: none; }
.so-pulso { display: block; width: 16px; height: 16px; border-radius: 50%; background: var(--c);
  border: 2px solid #0f172a; box-shadow: 0 0 0 0 var(--c); animation: so-pulso 1.6s ease-out infinite; cursor: pointer; }
.so-pulso.so-sel { outline: 2px solid #f8fafc; outline-offset: 3px; }
.so-camara { display: block; width: 12px; height: 12px; border-radius: 3px; background: #e2e8f0; border: 2px solid #0f172a; }
.so-camara.so-inactiva { background: #475569; }
.so-rondin { display: block; width: 14px; height: 14px; border-radius: 50%; background: transparent;
  border: 3px solid ${AZUL}; }
.so-resuelto { display: block; width: 14px; height: 14px; border-radius: 50%; background: ${VERDE};
  border: 2px solid #f8fafc; cursor: pointer; }
.so-patrulla { display: block; width: 18px; height: 18px; border-radius: 50%; background: ${AZUL};
  border: 3px solid #f8fafc; box-shadow: 0 0 0 0 rgba(59,130,246,.7); animation: so-sirena 1s ease-out infinite; }
.so-patrulla.so-llego { animation: none; box-shadow: 0 0 0 4px rgba(34,197,94,.45); }
@keyframes so-sirena { 70% { box-shadow: 0 0 0 12px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@keyframes so-pulso { 70% { box-shadow: 0 0 0 16px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@media (prefers-reduced-motion: reduce) { .so-pulso { animation: none; box-shadow: 0 0 0 5px color-mix(in srgb, var(--c) 35%, transparent); } }
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
  zoom = 17,
  cuadrantes = [],
  camaras = [],
  alertas = [],
  rondines = [],
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
      patrullas: L.layerGroup().addTo(m),
      alertas: L.layerGroup().addTo(m),
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
      L.polygon(q.coords, { color: "#64748b", weight: 1, dashArray: "4 4", fillColor: "#38bdf8", fillOpacity: 0.04 })
        .bindTooltip(q.nombre, { sticky: true })
        .addTo(capa),
    );
  }, [cuadrantes]);

  useEffect(() => {
    const capa = capas.current.camaras.clearLayers();
    camaras.forEach((c) =>
      L.marker([c.lat, c.lng], {
        icon: icono(`<span class="so-camara${c.activa ? "" : " so-inactiva"}"></span>`, 12),
        keyboard: false,
      })
        .bindTooltip(`${c.id} · ${c.nombre}${c.activa ? "" : " (en revisión)"}`)
        .addTo(capa),
    );
  }, [camaras]);

  useEffect(() => {
    const capa = capas.current.alertas.clearLayers();
    alertas.forEach((a) => {
      const lado = TAMANO_SEVERIDAD[a.severidad] || 14;
      const sel = a.id === seleccion ? " so-sel" : "";
      const resuelto = a.caso === "resuelto";
      const html = resuelto
        ? `<span class="so-resuelto${sel}"></span>`
        : `<span class="so-pulso${sel}" style="--c:${ROJO};width:${lado}px;height:${lado}px"></span>`;
      const estado = { pendiente: "pendiente", en_camino: "unidad en camino", resuelto: "atendido y resuelto" }[a.caso] || "";
      L.marker([a.lat, a.lng], {
        icon: icono(html, resuelto ? 14 : lado),
        title: `${a.tipo_txt}, severidad ${a.sev_txt}, ${estado}`,
        zIndexOffset: resuelto ? 600 : 1000,
      })
        .bindTooltip(`${a.tipo_txt} · ${a.sev_txt} · ${estado} · ${a.camara_id} · ${a.hora}`)
        .on("click", () => alClic.current && alClic.current(a.id))
        .addTo(capa);
    });
  }, [alertas, seleccion]);

  useEffect(() => {
    const capa = capas.current.rondines.clearLayers();
    rondines.forEach((r) =>
      // Por encima de las alertas: un rondín junto a un foco rojo no debe quedar tapado.
      L.marker([r.lat, r.lng], { icon: icono('<span class="so-rondin"></span>', 14), keyboard: false, zIndexOffset: 2000 })
        .bindTooltip(r.texto)
        .addTo(capa),
    );
  }, [rondines]);

  // --- Patrullas: se crean/actualizan al cambiar la lista; un bucle de animación
  // las mueve por su ruta según la hora real de salida y de llegada.
  const unidades = useRef(new Map());
  useEffect(() => {
    const vigentes = new Set();
    const ahora = Date.now();
    patrullas.forEach((p) => {
      const llego = p.estado === "resuelto";
      if (llego && ahora - (p.llegada_real_ms || p.llegada_ms) > PATRULLA_VISIBLE_TRAS_LLEGAR_MS) return;
      if (!p.ruta || p.ruta.length < 2) return;
      vigentes.add(p.id);
      let u = unidades.current.get(p.id);
      if (!u) {
        const acum = [0];
        for (let i = 1; i < p.ruta.length; i++) acum.push(acum[i - 1] + distancia(p.ruta[i - 1], p.ruta[i]));
        u = {
          linea: L.polyline(p.ruta, { color: AZUL, weight: 4, opacity: 0.8, dashArray: "8 8" }).addTo(capas.current.rutas),
          marca: L.marker(p.ruta[0], { icon: icono('<span class="so-patrulla"></span>', 18), zIndexOffset: 3000, keyboard: false })
            .bindTooltip(`${p.unidad} · en camino`)
            .addTo(capas.current.patrullas),
          acum,
        };
        unidades.current.set(p.id, u);
        // Recién despachada: encuadrar toda la ruta para ver a la unidad acercarse.
        if (!llego && mapa.current && ahora - p.inicio_ms < 15000) {
          mapa.current.flyToBounds(u.linea.getBounds(), { padding: [40, 40], duration: 1.2, maxZoom: 17 });
        }
      }
      u.datos = p;
      if (llego) {
        u.linea.setStyle({ opacity: 0 });
        u.marca.setIcon(icono('<span class="so-patrulla so-llego"></span>', 18));
        u.marca.setTooltipContent(`${p.unidad} · en el lugar: caso resuelto`);
      }
    });
    for (const [id, u] of unidades.current) {
      if (!vigentes.has(id)) {
        capas.current.rutas.removeLayer(u.linea);
        capas.current.patrullas.removeLayer(u.marca);
        unidades.current.delete(id);
      }
    }
  }, [patrullas]);

  useEffect(() => {
    let cuadro;
    const animar = () => {
      const ahora = Date.now();
      for (const u of unidades.current.values()) {
        const p = u.datos;
        const fraccion = p.estado === "resuelto" ? 1 : Math.min(1, Math.max(0, (ahora - p.inicio_ms) / (p.llegada_ms - p.inicio_ms)));
        u.marca.setLatLng(sobreRuta(p.ruta, u.acum, fraccion));
      }
      cuadro = requestAnimationFrame(animar);
    };
    cuadro = requestAnimationFrame(animar);
    return () => cancelAnimationFrame(cuadro);
  }, []);

  // Violencia detectada (o unidad enviada): el mapa vuela al lugar.
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
        radius: 28,
        blur: 22,
        minOpacity: 0.35,
        max: Math.max(4, calor.length / 40),
        // Rojo = inseguridad (el azul queda reservado para los rondines).
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
      <div ref={nodo} className="so-mapa" style={{ height: altura }} role="application" aria-label="Mapa de Mérida, Yucatán" />
    </>
  );
}
