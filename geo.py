"""Calculs de distance aux gares RER A."""
from math import asin, cos, radians, sin, sqrt
from urllib.parse import quote


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    a = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(a))


def gare_la_plus_proche(lat, lon, stations):
    """Retourne (station, distance_km) pour la gare active la plus proche, ou None."""
    best = None
    for s in stations:
        if not s.get("actif", True):
            continue
        d = haversine_km(lat, lon, s["lat"], s["lon"])
        if best is None or d < best[1]:
            best = (s, d)
    return best


def minutes_a_pied(km):
    # ~4,5 km/h + 20 % de détour par rapport au vol d'oiseau
    return max(1, round(km * 1.2 / 4.5 * 60))


def lien_trajet(origine, destination, mode="walking"):
    """Lien Google Maps (origine/destination : (lat, lon) ou adresse texte)."""
    def fmt(x):
        return f"{x[0]},{x[1]}" if isinstance(x, (tuple, list)) else quote(x)
    return (f"https://www.google.com/maps/dir/?api=1&origin={fmt(origine)}"
            f"&destination={fmt(destination)}&travelmode={mode}")
