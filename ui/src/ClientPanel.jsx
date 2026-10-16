import { useState } from 'react';
import { CLIENTS, PLACES } from './places.js';
import { STEPS } from './feed.js';

const LABEL = {
  IDLE: ['Waiting', 'bg-slate-600'],
  REQUESTED: ['Searching', 'bg-amber-400 text-black'],
  SEARCHING: ['Searching', 'bg-amber-400 text-black'],
  MATCHED: ['Driver found', 'bg-sky-400 text-black'],
  DRIVER_EN_ROUTE: ['Driver found', 'bg-sky-400 text-black'],
  DRIVER_ARRIVED: ['Driver arrived', 'bg-violet-400 text-black'],
  IN_TRIP: ['In trip', 'bg-blue-600'],
  COMPLETED: ['Completed', 'bg-emerald-500 text-black'],
  NO_DRIVER: ['No driver available', 'bg-red-600'],
};

const minutes = (s) => `${Math.max(1, Math.round(s / 60))} min`;

function Card({ client, ride, onOpen }) {
  const status = ride ? ride.status : 'IDLE';
  const [label, style] = LABEL[status];
  const active = ride && !['COMPLETED', 'NO_DRIVER'].includes(status);
  const reached = ride ? STEPS.indexOf(status) : -1;
  return (
    <button
      data-testid={`card-${client.id}`}
      onClick={() => !active && onOpen(client)}
      className={`text-left rounded-2xl p-5 bg-slate-900 border-2 ${active ? 'border-sky-400' : 'border-slate-700 hover:border-slate-400'} flex flex-col gap-3`}
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xl font-extrabold">{client.name}</div>
          <div className="text-lg text-slate-300">Client {client.id}</div>
        </div>
        <span data-testid={`status-${client.id}`} className={`px-4 py-2 rounded-full text-lg font-bold ${style}`}>
          {label}
        </span>
      </div>
      {ride?.driver_id && (
        <div className="text-xl">
          Driver <b>{ride.driver_name ? `${ride.driver_name} (${ride.driver_id})` : ride.driver_id}</b>
          {['MATCHED', 'DRIVER_EN_ROUTE'].includes(status) && ride.eta_s != null && (
            <span>, ETA <b>{minutes(ride.eta_s)}</b> by road</span>
          )}
        </div>
      )}
      {ride?.price_kes != null && (
        <div className="text-xl">
          Fare <b>KES {ride.price_kes}</b>
          {ride.surge > 1 && <span className="ml-2 px-2 py-1 rounded bg-red-700 font-bold">surge x{ride.surge}</span>}
        </div>
      )}
      <div className="flex gap-1">
        {STEPS.slice(1).map((s, i) => (
          <div key={s} className={`h-2 flex-1 rounded ${i + 1 <= reached ? 'bg-sky-400' : 'bg-slate-700'}`} />
        ))}
      </div>
      <div className="text-base text-slate-400">{active ? 'Ride in progress' : 'Click to request a ride'}</div>
    </button>
  );
}

function RequestForm({ client, feed, onClose }) {
  const [pickup, setPickup] = useState(client.pickup);
  const [dropoff, setDropoff] = useState(client.dropoff);
  const [error, setError] = useState('');
  const select = (value, set, testid) => (
    <select data-testid={testid} value={value} onChange={(e) => set(e.target.value)} className="w-full text-xl p-3 rounded-lg bg-slate-800 border border-slate-500">
      {Object.keys(PLACES).map((p) => (
        <option key={p}>{p}</option>
      ))}
    </select>
  );
  const send = () => {
    if (pickup === dropoff) return setError('Pickup and dropoff must differ.');
    if (!feed.requestRide(client.id, PLACES[pickup], PLACES[dropoff])) {
      return setError(feed.mode === 'replay' ? 'Requests are disabled while replaying a recording.' : 'Not connected.');
    }
    onClose();
  };
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[1000]">
      <div className="bg-slate-900 border-2 border-slate-500 rounded-2xl p-8 w-[520px] flex flex-col gap-5">
        <h2 className="text-3xl font-extrabold">Ride for {client.name}</h2>
        <label className="text-xl font-bold">Pickup{select(pickup, setPickup, 'pickup')}</label>
        <label className="text-xl font-bold">Dropoff{select(dropoff, setDropoff, 'dropoff')}</label>
        {error && <div className="text-red-400 text-lg">{error}</div>}
        <div className="flex gap-4">
          <button data-testid="send" onClick={send} className="flex-1 py-4 rounded-xl bg-sky-400 text-black text-2xl font-extrabold">
            Send request
          </button>
          <button onClick={onClose} className="px-6 py-4 rounded-xl bg-slate-700 text-xl">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ClientPanel({ feed }) {
  const [open, setOpen] = useState(null);
  return (
    <div className="h-full overflow-auto p-6">
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
        {CLIENTS.map((c) => (
          <Card key={c.id} client={c} ride={feed.rides[c.id]} onOpen={setOpen} />
        ))}
      </div>
      {open && <RequestForm client={open} feed={feed} onClose={() => setOpen(null)} />}
    </div>
  );
}
