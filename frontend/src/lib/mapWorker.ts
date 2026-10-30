import { setWorkerUrl } from 'maplibre-gl'
// maplibre finds its worker next to its own module; Vite's dependency pre-bundling moves that
// module, so the worker URL is given explicitly (the worker file has no imports of its own).
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

// Keep a version on the worker request so browsers do not reuse a partial response
// cached before the server started serving .mjs as JavaScript.
setWorkerUrl(`${workerUrl}?v=20261030-1`)
