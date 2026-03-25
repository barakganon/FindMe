import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import type { SearchResult } from '../types'

interface Props { results: SearchResult[] }

export function StoreMap({ results }: Props) {
  const located = results.filter((r) => r.lat != null && r.lng != null)
  if (located.length === 0) return null

  const center: [number, number] = [located[0].lat!, located[0].lng!]

  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 h-72">
      <MapContainer center={center} zoom={11} style={{ height: '100%', width: '100%' }}>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {located.map((r, i) => (
          <Marker key={i} position={[r.lat!, r.lng!]}>
            <Popup>
              <strong>{r.store_name}</strong><br />
              {r.product_name}<br />
              {r.price != null && `₪${r.price}`}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  )
}
