import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import type { ProductResult, StoreResult } from '../types'

// Normalised marker shape used internally
interface MapMarker {
  lat: number
  lng: number
  name: string
  subtitle?: string
}

function productResultsToMarkers(results: ProductResult[]): MapMarker[] {
  return results
    .filter((r) => r.store.lat != null && r.store.lng != null)
    .map((r) => ({
      lat: r.store.lat!,
      lng: r.store.lng!,
      name: r.store.name_he,
      subtitle: `${r.canonical_name}${r.price != null ? ` · ₪${r.price}` : ''}`,
    }))
}

function storeResultsToMarkers(results: StoreResult[]): MapMarker[] {
  return results
    .filter((r) => r.lat != null && r.lng != null)
    .map((r) => ({
      lat: r.lat!,
      lng: r.lng!,
      name: r.name_he,
      subtitle: r.city ?? undefined,
    }))
}

interface ProductProps { results: ProductResult[]; mode?: 'product' }
interface StoreProps  { results: StoreResult[];   mode: 'store' }
type Props = ProductProps | StoreProps

export function StoreMap(props: Props) {
  const markers: MapMarker[] =
    props.mode === 'store'
      ? storeResultsToMarkers(props.results as StoreResult[])
      : productResultsToMarkers(props.results as ProductResult[])

  if (markers.length === 0) return null

  const center: [number, number] = [markers[0].lat, markers[0].lng]

  return (
    <div className="rounded-xl overflow-hidden border border-gray-200 h-72">
      <MapContainer center={center} zoom={11} style={{ height: '100%', width: '100%' }}>
        <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {markers.map((m, i) => (
          <Marker key={i} position={[m.lat, m.lng]}>
            <Popup>
              <strong>{m.name}</strong>
              {m.subtitle && <><br />{m.subtitle}</>}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  )
}
