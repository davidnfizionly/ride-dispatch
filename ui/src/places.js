// Named pickup and dropoff points inside the service area.
export const PLACES = {
  'Nairobi CBD': { lat: -1.2864, lng: 36.8172 },
  Westlands: { lat: -1.2676, lng: 36.8108 },
  'Upper Hill': { lat: -1.2995, lng: 36.8143 },
  Kilimani: { lat: -1.2921, lng: 36.7856 },
  Lavington: { lat: -1.28, lng: 36.77 },
  Ngara: { lat: -1.2741, lng: 36.827 },
  'South B': { lat: -1.3105, lng: 36.835 },
  Parklands: { lat: -1.263, lng: 36.815 },
  Hurlingham: { lat: -1.295, lng: 36.799 },
};

// Synthetic demo clients.
export const CLIENTS = [
  { id: 'C1', name: 'Amina', pickup: 'Nairobi CBD', dropoff: 'Westlands' },
  { id: 'C2', name: 'Brian', pickup: 'Kilimani', dropoff: 'Upper Hill' },
  { id: 'C3', name: 'Wanjiru', pickup: 'Westlands', dropoff: 'Ngara' },
  { id: 'C4', name: 'Otieno', pickup: 'Upper Hill', dropoff: 'Lavington' },
  { id: 'C5', name: 'Grace', pickup: 'Parklands', dropoff: 'Hurlingham' },
];
