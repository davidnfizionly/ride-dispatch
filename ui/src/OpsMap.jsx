import { CircleMarker, MapContainer, Polygon, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { cellToBoundary } from 'h3-js';

const COLORS = { available: '#22c55e', en_route: '#f59e0b', in_trip: '#3b82f6', offline: '#94a3b8' };
const LEGEND = [
  ['available', 'Available'],
  ['en_route', 'En route to pickup'],
  ['in_trip', 'In trip'],
  ['offline', 'Offline'],
];

const surgeColor = (s) => (s <= 1 ? '#64748b' : s < 1.5 ? '#f97316' : '#dc2626');

export default function OpsMap({ feed }) {
  const byId = Object.fromEntries(feed.drivers.map((d) => [d.driver_id, d]));
  const active = Object.values(feed.rides).filter((r) => r.driver_id && ['MATCHED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_TRIP'].includes(r.status));
  const counts = feed.drivers.reduce((acc, d) => ({ ...acc, [d.status]: (acc[d.status] || 0) + 1 }), {});

  return (
    <div className="h-full relative">
      <MapContainer center={[-1.282, 36.812]} zoom={13} minZoom={12} maxZoom={16} preferCanvas>
        <TileLayer
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        />
        {feed.zones.map((z) => (
          <Polygon
            key={z.zone}
            positions={cellToBoundary(z.zone)}
            pathOptions={{ color: surgeColor(z.surge), weight: 1.5, fillOpacity: z.surge > 1 ? 0.25 : 0.04 }}
          >
            {z.surge > 1 && (
              <Tooltip permanent direction="center" className="zone-label">
                x{z.surge}
              </Tooltip>
            )}
          </Polygon>
        ))}
        {active.map((r) => {
          const d = byId[r.driver_id];
          const target = r.status === 'IN_TRIP' ? r.dropoff : r.pickup;
          if (!d || !target) return null;
          return (
            <Polyline key={r.ride_id} positions={[[d.lat, d.lng], [target.lat, target.lng]]} pathOptions={{ color: '#facc15', weight: 4, dashArray: '8 6' }} />
          );
        })}
        {active.map((r) =>
          r.pickup ? (
            <CircleMarker key={`p-${r.ride_id}`} center={[r.pickup.lat, r.pickup.lng]} radius={9} pathOptions={{ color: '#fff', fillColor: '#facc15', fillOpacity: 1, weight: 3 }}>
              <Tooltip>Client {r.client_id} pickup</Tooltip>
            </CircleMarker>
          ) : null,
        )}
        {feed.drivers.map((d) => (
          <CircleMarker key={d.driver_id} center={[d.lat, d.lng]} radius={8} pathOptions={{ color: '#0b1220', weight: 2, fillColor: COLORS[d.status] || '#fff', fillOpacity: 1 }}>
            <Tooltip>
              {d.driver_id} ({d.status})
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>

      <div className="absolute top-4 right-4 z-[500] bg-slate-950/90 border border-slate-600 rounded-xl p-4 w-80 text-lg">
        <div className="text-xl font-extrabold mb-2" data-testid="driver-count">
          {feed.drivers.length} drivers
        </div>
        {LEGEND.map(([k, label]) => (
          <div key={k} className="flex items-center gap-3">
            <span className="inline-block w-4 h-4 rounded-full" style={{ background: COLORS[k] }} />
            <span className="flex-1">{label}</span>
            <b>{counts[k] || 0}</b>
          </div>
        ))}
        <div className="mt-3 border-t border-slate-700 pt-3">
          Active rides: <b data-testid="active-rides">{active.length}</b>
        </div>
        {feed.lastMatch && (
          <div className="mt-1">
            Last match lookup: <b>{feed.lastMatch.lookup_ms} ms</b>
            <div className="text-sm text-slate-400">Redis search and driver claim, measured in the matching function</div>
          </div>
        )}
        <div className="mt-3 border-t border-slate-700 pt-3 text-base">
          <div className="font-bold mb-1">Zone surge (H3)</div>
          <span className="text-slate-300">Hexagons turn orange or red when local supply is short.</span>
        </div>
      </div>

      <div className="absolute bottom-8 left-4 z-[500] bg-slate-950/90 border border-slate-600 rounded-xl p-3 w-96 text-base">
        <div className="font-bold text-lg mb-1">Latest events</div>
        {feed.log.slice(0, 6).map((e, i) => (
          <div key={i} className="truncate">
            <b>{e.type}</b> {e.client_id} {e.driver_id || ''}
          </div>
        ))}
      </div>
    </div>
  );
}
