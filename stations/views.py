import json
import logging
from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .services.optimizer import InfeasibleRoute
from .services.planner import StationDataError, plan_route
from .services.routing import LocationError, RoutingError

log = logging.getLogger(__name__)

MAX_INPUT_LEN = 200


def read_places(request):
    if request.method == "POST":
        try:
            body = json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            raise LocationError("Body must be valid JSON.")
        if not isinstance(body, dict):
            raise LocationError("Body must be a JSON object.")
        start, finish = body.get("start"), body.get("finish")
    else:
        start, finish = request.GET.get("start"), request.GET.get("finish")

    if not isinstance(start, str) or not isinstance(finish, str) or not start.strip() or not finish.strip():
        raise LocationError("'start' and 'finish' are both required.")
    if len(start) > MAX_INPUT_LEN or len(finish) > MAX_INPUT_LEN:
        raise LocationError("Location text is too long.")
    return start.strip(), finish.strip()


def run(request):
    """Returns (start, finish, plan) or a JsonResponse describing the failure."""
    try:
        start, finish = read_places(request)
        return start, finish, plan_route(start, finish)
    except LocationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except InfeasibleRoute as exc:
        return JsonResponse({"error": str(exc)}, status=422)
    except RoutingError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    except StationDataError as exc:
        log.error("%s", exc)
        return JsonResponse({"error": "Station data isn't loaded on the server."}, status=503)


@csrf_exempt  # JSON API with no cookies or sessions, so there's nothing for CSRF to protect
@require_http_methods(["GET", "POST"])
def route_api(request):
    out = run(request)
    if isinstance(out, JsonResponse):
        return out
    start, finish, plan = out
    map_url = request.build_absolute_uri("/api/route/map/") + "?" + urlencode({"start": start, "finish": finish})
    return JsonResponse({**plan, "map_url": map_url})


@require_http_methods(["GET"])
def route_map(request):
    out = run(request)
    if isinstance(out, JsonResponse):
        return out
    return render(request, "stations/map.html", {"plan": out[2]})
