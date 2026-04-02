import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import type { ProductResult } from '../types'

interface Props { results: ProductResult[] }

export function StoreMap({ results }: Props) {
  const located = results.filter((r) => r.store.lat != null && r.store.lng != null)
  if (located.length === 0) return null

  const center: [number, number] = [located[0].store.lat!, located[0].store.lng!]

  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 h-72">
      <MapContainer center={center} zoom={11} style={{ height: '100%', width: '100%' }}>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {located.map((r, i) => (
          <Marker key={i} position={[r.store.lat!, r.store.lng!]}>
            <Popup>
              <strong>{r.store.name_he}</strong><br />
              {r.canonical_name}<br />
              {r.price != null && `₪${r.price}`}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  )
}
