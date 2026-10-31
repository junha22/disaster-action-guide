"""Feature routers for the risk-avoiding route service. Registered in main.py."""
from .explain import router as explain_router
from .reroute import router as reroute_router
from .risk import router as risk_router
from .route import router as route_router
from .search import router as search_router
from .strategies import router as strategies_router
from .tts import router as tts_router
from .weather import router as weather_router

routers = [strategies_router, risk_router, weather_router, search_router, route_router, explain_router, reroute_router,
           tts_router]
