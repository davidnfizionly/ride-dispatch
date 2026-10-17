import { useEffect, useReducer, useRef, useCallback } from 'react';

// Lifecycle order; a ride only moves forward (events may arrive out of order).
export const STEPS = ['REQUESTED', 'SEARCHING', 'MATCHED', 'DRIVER_EN_ROUTE', 'DRIVER_ARRIVED', 'IN_TRIP', 'COMPLETED'];

const STATE_FOR_EVENT = {
  RideRequested: 'REQUESTED',
  RideSearching: 'SEARCHING',
  RideMatched: 'MATCHED',
  RideNoDriver: 'NO_DRIVER',
  DriverEnRoute: 'DRIVER_EN_ROUTE',
  DriverArrived: 'DRIVER_ARRIVED',
  TripStarted: 'IN_TRIP',
  TripCompleted: 'COMPLETED',
};

const rank = (s) => (s === 'NO_DRIVER' ? 99 : STEPS.indexOf(s));

const initial = { status: 'connecting', drivers: [], zones: [], rides: {}, log: [], lastMatch: null };

function reducer(state, action) {
  if (action.kind === 'status') return { ...state, status: action.status };
  const msg = action.msg;
  if (msg.type === 'PositionsSnapshot') {
    return { ...state, drivers: msg.detail.drivers, zones: msg.detail.zones || [] };
  }
  if (msg.type === 'requestAck') {
    if (msg.statusCode !== 200 || !msg.client_id) return state;
    const prev = state.rides[msg.client_id];
    if (prev && prev.ride_id === msg.ride_id) return state;
    const ride = { ride_id: msg.ride_id, client_id: msg.client_id, status: 'REQUESTED', steps: { REQUESTED: Date.now() } };
    return { ...state, rides: { ...state.rides, [msg.client_id]: ride } };
  }
  const target = STATE_FOR_EVENT[msg.type];
  if (!target) return state;
  const d = msg.detail;
  const log = [{ at: Date.now(), type: msg.type, ride_id: d.ride_id, client_id: d.client_id, driver_id: d.driver_id }, ...state.log].slice(0, 12);
  const prev = state.rides[d.client_id];
  // A new ride for this client replaces the previous one once it is requested.
  let ride = prev && prev.ride_id === d.ride_id ? prev : null;
  if (!ride) {
    if (target !== 'REQUESTED' && prev && rank(prev.status) < rank('COMPLETED') && prev.ride_id !== d.ride_id) {
      return { ...state, log };
    }
    ride = { ride_id: d.ride_id, client_id: d.client_id, status: 'REQUESTED', steps: {} };
  }
  if (rank(target) < rank(ride.status) || ride.status === 'COMPLETED' || ride.status === 'NO_DRIVER') {
    return { ...state, log };
  }
  const merged = { ...ride, status: target, steps: { ...ride.steps, [target]: d.ts || Date.now() } };
  for (const k of ['pickup', 'dropoff', 'driver_id', 'driver_name', 'eta_s', 'sim_eta_s', 'price_kes', 'surge', 'zone', 'trip_distance_m']) {
    if (d[k] !== undefined && d[k] !== null) merged[k] = d[k];
  }
  const lastMatch = msg.type === 'RideMatched' ? { lookup_ms: d.lookup_ms, total_ms: d.total_ms, at: Date.now() } : state.lastMatch;
  return { ...state, log, lastMatch, rides: { ...state.rides, [d.client_id]: merged } };
}

// Live WebSocket when VITE_WS_URL is set, otherwise replay of public/replay.json.
export function useFeed() {
  const [state, dispatch] = useReducer(reducer, initial);
  const wsRef = useRef(null);
  const url = import.meta.env.VITE_WS_URL;
  const mode = url ? 'live' : 'replay';

  useEffect(() => {
    if (mode === 'live') {
      let closed = false;
      let retry;
      const open = () => {
        const ws = new WebSocket(`${url}?token=${encodeURIComponent(import.meta.env.VITE_WS_TOKEN || '')}`);
        wsRef.current = ws;
        // Only the current socket may change state (React StrictMode opens and
        // closes a first socket in development).
        ws.onopen = () => wsRef.current === ws && dispatch({ kind: 'status', status: 'connected' });
        ws.onmessage = (e) => dispatch({ kind: 'msg', msg: JSON.parse(e.data) });
        ws.onclose = () => {
          if (wsRef.current !== ws) return;
          dispatch({ kind: 'status', status: 'disconnected' });
          if (!closed) retry = setTimeout(open, 2000);
        };
      };
      open();
      return () => {
        closed = true;
        clearTimeout(retry);
        const ws = wsRef.current;
        wsRef.current = null;
        ws?.close();
      };
    }
    let timers = [];
    let stopped = false;
    fetch('/replay.json')
      .then((r) => r.json())
      .then((messages) => {
        dispatch({ kind: 'status', status: 'replay' });
        const play = () => {
          if (stopped) return;
          timers = messages.map((m) => setTimeout(() => dispatch({ kind: 'msg', msg: m.msg }), m.t));
          timers.push(setTimeout(play, messages[messages.length - 1].t + 3000));
        };
        play();
      });
    return () => {
      stopped = true;
      timers.forEach(clearTimeout);
    };
  }, [mode, url]);

  const requestRide = useCallback((client_id, pickup, dropoff) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ action: 'requestRide', client_id, pickup, dropoff }));
    return true;
  }, []);

  return { ...state, mode, requestRide };
}
