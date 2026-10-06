// Mapa Leaflet del campus: cuadrantes, cámaras, alertas en vivo y capa de calor.
// Se usa Leaflet directamente (sin react-leaflet) para exponer a Reflex una
// API pequeña basada en props.
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const COLOR_SEVERIDAD = {
  critica: "#f43f5e",
  alta: "#f97316",
  media: "#fbbf24",
  baja: "#22c55e",
};

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
@keyframes so-pulso { 70% { box-shadow: 0 0 0 16px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@media (prefers-reduced-motion: reduce) { .so-pulso { animation: none; box-shadow: 0 0 0 5px color-mix(in srgb, var(--c) 35%, transparent); } }
`;

function icono(html, lado) {
  return L.divIcon({ className: "", html, iconSize: [lado, lado], iconAnchor: [lado / 2, lado / 2] });
}

export function MapaLeaflet({
  centro,
  zoom = 17,
  cuadrantes = [],
  camaras = [],
  alertas = [],
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
      const color = COLOR_SEVERIDAD[a.severidad] || "#6366f1";
      const sel = a.id === seleccion ? " so-sel" : "";
      L.marker([a.lat, a.lng], {
        icon: icono(`<span class="so-pulso${sel}" style="--c:${color}"></span>`, 16),
        title: `${a.tipo_txt}, severidad ${a.sev_txt}`,
        zIndexOffset: 1000,
      })
        .bindTooltip(`${a.tipo_txt} · ${a.sev_txt} · ${a.camara_id} · ${a.hora}`)
        .on("click", () => alClic.current && alClic.current(a.id))
        .addTo(capa);
    });
  }, [alertas, seleccion]);

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
        gradient: { 0.3: "#0c4a6e", 0.6: "#0ea5e9", 0.85: "#7dd3fc", 1: "#f0f9ff" },
      }).addTo(capa);
    });
    return () => {
      vigente = false;
    };
  }, [calor]);

  return (
    <>
      <style>{CSS}</style>
      <div ref={nodo} className="so-mapa" style={{ height: altura }} role="application" aria-label="Mapa del campus" />
    </>
  );
}
