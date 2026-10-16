import { useState } from 'react';
import { useFeed } from './feed.js';
import ClientPanel from './ClientPanel.jsx';
import OpsMap from './OpsMap.jsx';

const STATUS_STYLE = {
  connected: 'bg-emerald-500 text-black',
  replay: 'bg-amber-400 text-black',
  connecting: 'bg-slate-500 text-white',
  disconnected: 'bg-red-600 text-white',
};

export default function App() {
  const feed = useFeed();
  const [view, setView] = useState('clients');
  const tab = (id, label) => (
    <button
      data-testid={`tab-${id}`}
      onClick={() => setView(id)}
      className={`px-6 py-3 rounded-lg text-xl font-bold ${view === id ? 'bg-sky-400 text-black' : 'bg-slate-800 text-slate-100 hover:bg-slate-700'}`}
    >
      {label}
    </button>
  );
  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center gap-4 px-5 py-3 bg-slate-950 border-b border-slate-700">
        <h1 className="text-2xl font-extrabold mr-4">Ride Dispatch</h1>
        {tab('clients', 'Client Panel')}
        {tab('map', 'Live Ops Map')}
        <span data-testid="conn" className={`ml-auto px-4 py-2 rounded-full text-lg font-bold ${STATUS_STYLE[feed.status]}`}>
          {feed.mode === 'replay' ? 'Replay of recorded local run' : feed.status}
        </span>
      </header>
      <main className="flex-1 min-h-0">{view === 'clients' ? <ClientPanel feed={feed} /> : <OpsMap feed={feed} />}</main>
    </div>
  );
}
