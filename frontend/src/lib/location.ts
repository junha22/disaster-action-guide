// The device's current position for the main screen. The driving screen stays a simulated drive.
const GPS: PositionOptions = { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 }
const NETWORK: PositionOptions = { enableHighAccuracy: false, timeout: 8000, maximumAge: 5 * 60 * 1000 }

// GPS first. Indoors it may never get a fix, so a timeout falls back to Wi-Fi and cell towers.
export function locate(onSuccess: (position: GeolocationPosition) => void, onFailure: () => void) {
  navigator.geolocation.getCurrentPosition(onSuccess, error => {
    if (error.code === error.PERMISSION_DENIED) onFailure()
    else navigator.geolocation.getCurrentPosition(onSuccess, onFailure, NETWORK)
  }, GPS)
}
