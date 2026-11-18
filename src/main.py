"""Apify Actor & Standby MCP Server for IBGE Open Data APIs."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Callable

try:
    from aiohttp import web
    from apify import Actor
except ImportError:
    web = None  # type: ignore[assignment]
    Actor = None  # type: ignore[assignment]

EVENT_NAME = "record-delivered"

UF_TO_CODE: dict[str, int] = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17,
    "MA": 21, "PI": 22, "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27,
    "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35,
    "PR": 41, "SC": 42, "RS": 43,
    "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_brazil_ibge",
        "description": (
            "Query official Brazilian IBGE geodemographics: municipalities & 7-digit codes, "
            "population estimates, municipal GDP (PIB), CNAE 2.3 classes, and GeoJSON meshes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": [
                        "municipalities",
                        "population",
                        "municipal_gdp",
                        "cnae_classes",
                        "geojson_mesh",
                    ],
                },
                "uf": {"type": "string", "default": "AL"},
                "ibgeIds": {"type": "array", "items": {"type": "string"}},
                "cnaeCode": {"type": "string", "default": ""},
                "query": {"type": "string", "default": ""},
                "quality": {
                    "type": "string",
                    "enum": ["minima", "intermediaria", "maxima"],
                    "default": "minima",
                },
                "maxResults": {"type": "integer", "default": 50},
                "timeoutSecs": {"type": "integer", "default": 30},
            },
            "required": ["mode"],
        },
    }
]


def http_get_json(url: str, timeout: int = 30) -> Any:
    """Fetch a JSON response from IBGE APIs with explicit browser-friendly headers."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; apify-brazil-ibge/1.0)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_localidade_expr(ibge_ids: list[str] | None, uf: str) -> str:
    clean_ids = [str(item).strip() for item in (ibge_ids or []) if str(item).strip().isdigit()]
    if clean_ids:
        return f"N6[{','.join(clean_ids)}]"
    uf_upper = (uf or "").strip().upper()
    if uf_upper in UF_TO_CODE:
        return f"N6[N3[{UF_TO_CODE[uf_upper]}]]"
    # Fallback to Brazil state-level aggregate when no municipality/UF is given
    return "N3[all]"


def fetch_municipalities(
    uf: str = "",
    query: str = "",
    max_results: int = 100,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch and normalize Brazilian municipalities from IBGE Localidades API v1."""
    cap = max(1, min(int(max_results), 6000))
    uf_clean = (uf or "").strip().upper()
    if uf_clean and uf_clean in UF_TO_CODE:
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf_clean}/municipios"
    else:
        url = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"

    payload = fetcher(url, timeout)
    if not isinstance(payload, list):
        return []

    needle = (query or "").strip().lower()
    results: list[dict[str, Any]] = []
    for item in payload:
        micro = item.get("microrregiao") or {}
        meso = micro.get("mesorregiao") or {}
        uf_obj = meso.get("UF") or {}
        reg_obj = uf_obj.get("regiao") or {}
        reg_imed = item.get("regiao-imediata") or {}

        name = str(item.get("nome") or "")
        uf_sigla = str(uf_obj.get("sigla") or uf_clean)
        micro_name = str(micro.get("nome") or "")
        meso_name = str(meso.get("nome") or "")
        searchable = f"{name} {uf_sigla} {micro_name} {meso_name} {item.get('id', '')}".lower()
        if needle and needle not in searchable:
            continue

        results.append(
            {
                "recordType": "municipalities",
                "ibgeId": str(item.get("id") or ""),
                "name": name,
                "uf": uf_sigla,
                "ufName": str(uf_obj.get("nome") or ""),
                "macroRegion": str(reg_obj.get("nome") or ""),
                "mesoregion": meso_name,
                "microregion": micro_name,
                "immediateRegion": str(reg_imed.get("nome") or ""),
                "regionOrParent": meso_name or micro_name,
                "period": "current",
                "numericValue": int(item.get("id") or 0),
                "unit": "IBGE-7",
                "sourceUrl": url,
            }
        )
        if len(results) >= cap:
            break
    return results


def _fetch_sidra_aggregate(
    mode: str,
    aggregate_id: int,
    variable_id: int,
    uf: str = "",
    ibge_ids: list[str] | None = None,
    query: str = "",
    max_results: int = 100,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Shared parser for IBGE Agregados v3 (Population 6579 & Municipal GDP 5938)."""
    cap = max(1, min(int(max_results), 6000))
    loc_expr = urllib.parse.quote(_resolve_localidade_expr(ibge_ids, uf), safe="[],")
    url = (
        f"https://servicodados.ibge.gov.br/api/v3/agregados/{aggregate_id}"
        f"/periodos/-1/variaveis/{variable_id}?localidades={loc_expr}"
    )
    payload = fetcher(url, timeout)
    if not isinstance(payload, list) or not payload:
        return []

    block = payload[0]
    unit = str(block.get("unidade") or "")
    variable_name = str(block.get("variavel") or mode)
    needle = (query or "").strip().lower()

    results: list[dict[str, Any]] = []
    for res_group in block.get("resultados", []):
        for series in res_group.get("series", []):
            loc = series.get("localidade") or {}
            loc_id = str(loc.get("id") or "")
            loc_name = str(loc.get("nome") or "")
            if needle and needle not in loc_name.lower() and needle not in loc_id:
                continue

            serie_map = series.get("serie") or {}
            if not serie_map:
                continue
            period, raw_val = next(iter(serie_map.items()))
            try:
                num_val = float(str(raw_val).replace(",", "."))
            except ValueError:
                num_val = 0.0

            if " - " in loc_name:
                uf_part = loc_name.rsplit(" - ", 1)[1].strip()
            elif loc_name.endswith(")") and "(" in loc_name:
                uf_part = loc_name.rsplit("(", 1)[1].rstrip(")").strip()
            else:
                uf_part = (uf or "").upper()
            results.append(
                {
                    "recordType": mode,
                    "ibgeId": loc_id,
                    "name": loc_name,
                    "uf": uf_part,
                    "regionOrParent": variable_name,
                    "period": str(period),
                    "numericValue": num_val,
                    "unit": unit,
                    "sourceUrl": url,
                }
            )
            if len(results) >= cap:
                return results
    return results


def fetch_population(
    uf: str = "",
    ibge_ids: list[str] | None = None,
    query: str = "",
    max_results: int = 100,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch IBGE estimated resident population (Aggregate 6579, Variable 9324)."""
    return _fetch_sidra_aggregate(
        mode="population",
        aggregate_id=6579,
        variable_id=9324,
        uf=uf,
        ibge_ids=ibge_ids,
        query=query,
        max_results=max_results,
        timeout=timeout,
        fetcher=fetcher,
    )


def fetch_municipal_gdp(
    uf: str = "",
    ibge_ids: list[str] | None = None,
    query: str = "",
    max_results: int = 100,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch IBGE municipal GDP at current prices in thousand BRL (Aggregate 5938, Variable 37)."""
    return _fetch_sidra_aggregate(
        mode="municipal_gdp",
        aggregate_id=5938,
        variable_id=37,
        uf=uf,
        ibge_ids=ibge_ids,
        query=query,
        max_results=max_results,
        timeout=timeout,
        fetcher=fetcher,
    )


def fetch_cnae_classes(
    cnae_code: str = "",
    query: str = "",
    max_results: int = 50,
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch and filter IBGE CNAE 2.3 economic activity classes."""
    cap = max(1, min(int(max_results), 1000))
    clean_code = "".join(ch for ch in (cnae_code or "") if ch.isdigit())
    if clean_code:
        url = f"https://servicodados.ibge.gov.br/api/v2/cnae/classes/{clean_code}"
        raw = fetcher(url, timeout)
        items = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) and raw.get("id") else [])
    else:
        url = "https://servicodados.ibge.gov.br/api/v2/cnae/classes"
        raw = fetcher(url, timeout)
        items = raw if isinstance(raw, list) else []

    needle = (query or "").strip().lower()
    results: list[dict[str, Any]] = []
    for item in items:
        cid = str(item.get("id") or "")
        desc = str(item.get("descricao") or "")
        group = item.get("grupo") or {}
        division = group.get("divisao") or {}
        section = division.get("secao") or {}
        searchable = f"{cid} {desc} {division.get('descricao', '')} {section.get('descricao', '')}".lower()
        if needle and needle not in searchable:
            continue

        results.append(
            {
                "recordType": "cnae_classes",
                "ibgeId": cid,
                "name": desc,
                "uf": "BR",
                "sectionId": str(section.get("id") or ""),
                "sectionName": str(section.get("descricao") or ""),
                "divisionName": str(division.get("descricao") or ""),
                "groupName": str(group.get("descricao") or ""),
                "regionOrParent": str(section.get("descricao") or ""),
                "period": "CNAE 2.3",
                "numericValue": int(cid) if cid.isdigit() else 0,
                "unit": "CNAE-Class",
                "sourceUrl": url,
            }
        )
        if len(results) >= cap:
            break
    return results


def fetch_geojson_mesh(
    uf: str = "AL",
    ibge_ids: list[str] | None = None,
    quality: str = "minima",
    timeout: int = 30,
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Fetch official IBGE GeoJSON boundary mesh for a municipality or state."""
    qual = quality if quality in {"minima", "intermediaria", "maxima"} else "minima"
    clean_ids = [str(i).strip() for i in (ibge_ids or []) if str(i).strip().isdigit()]
    if clean_ids:
        target_id = clean_ids[0]
        url = f"https://servicodados.ibge.gov.br/api/v3/malhas/municipios/{target_id}?formato=application/vnd.geo+json&qualidade={qual}"
        scope_label = f"Municipality {target_id}"
        target_uf = ""
    else:
        uf_clean = (uf or "AL").strip().upper() or "AL"
        url = f"https://servicodados.ibge.gov.br/api/v3/malhas/estados/{uf_clean}?formato=application/vnd.geo+json&qualidade={qual}"
        scope_label = f"State {uf_clean}"
        target_uf = uf_clean
        target_id = str(UF_TO_CODE.get(uf_clean, ""))

    geojson_obj = fetcher(url, timeout)
    features = geojson_obj.get("features", []) if isinstance(geojson_obj, dict) else []
    return [
        {
            "recordType": "geojson_mesh",
            "ibgeId": target_id,
            "name": scope_label,
            "uf": target_uf,
            "regionOrParent": f"GeoJSON ({qual})",
            "period": "current",
            "numericValue": len(features),
            "unit": "features",
            "geojson": geojson_obj,
            "sourceUrl": url,
        }
    ]


def run_query(
    params: dict[str, Any],
    fetcher: Callable[[str, int], Any] = http_get_json,
) -> list[dict[str, Any]]:
    """Route Actor inputs or MCP tool arguments to the corresponding IBGE endpoint."""
    mode = str(params.get("mode") or "municipalities").strip().lower()
    timeout = max(5, min(int(params.get("timeoutSecs") or 30), 60))
    max_results = int(params.get("maxResults") or 50)
    uf = str(params.get("uf") or "")
    query = str(params.get("query") or "")
    ibge_ids = params.get("ibgeIds") if isinstance(params.get("ibgeIds"), list) else []

    if mode == "municipalities":
        return fetch_municipalities(uf=uf, query=query, max_results=max_results, timeout=timeout, fetcher=fetcher)
    if mode == "population":
        return fetch_population(uf=uf, ibge_ids=ibge_ids, query=query, max_results=max_results, timeout=timeout, fetcher=fetcher)
    if mode == "municipal_gdp":
        return fetch_municipal_gdp(uf=uf, ibge_ids=ibge_ids, query=query, max_results=max_results, timeout=timeout, fetcher=fetcher)
    if mode == "cnae_classes":
        return fetch_cnae_classes(
            cnae_code=str(params.get("cnaeCode") or ""),
            query=query,
            max_results=max_results,
            timeout=timeout,
            fetcher=fetcher,
        )
    if mode == "geojson_mesh":
        return fetch_geojson_mesh(
            uf=uf or "AL",
            ibge_ids=ibge_ids,
            quality=str(params.get("quality") or "minima"),
            timeout=timeout,
            fetcher=fetcher,
        )
    raise ValueError(f"Unsupported mode: {mode}")


async def _charge_records(count: int) -> int:
    if count <= 0:
        return 0
    max_items_env = os.environ.get("ACTOR_MAX_PAID_DATASET_ITEMS")
    allowed = min(count, int(max_items_env)) if max_items_env and max_items_env.isdigit() else count
    if allowed <= 0:
        return 0
    try:
        res = await Actor.charge(event_name=EVENT_NAME, count=allowed)
        if hasattr(res, "event_charge_limit_reached") and res.event_charge_limit_reached:
            Actor.log.warning("Pay-per-event limit reached on %s.", EVENT_NAME)
    except Exception as exc:
        Actor.log.warning("Charge skipped in local/non-monetized mode: %s", exc)
    return allowed


async def _handle_mcp_rpc(payload: dict[str, Any]) -> dict[str, Any]:
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "apify-brazil-ibge-geodemographics", "version": "0.0.1"},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": MCP_TOOLS}}
    if method == "tools/call":
        if params.get("name") != "query_brazil_ibge":
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Unknown tool"}}
        rows = await asyncio.to_thread(run_query, params.get("arguments") or {})
        await _charge_records(len(rows))
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"content": [{"type": "text", "text": json.dumps(rows, ensure_ascii=False)}]},
        }
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": f"Unsupported method: {method}"}}


async def _run_standby_server() -> None:
    port = int(os.environ.get("ACTOR_STANDBY_PORT", "8080"))

    async def handle_health(_request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "actor": "apify-brazil-ibge-geodemographics"})

    async def handle_root(request: web.Request) -> web.Response:
        if request.headers.get("x-apify-container-server-readiness-probe"):
            return web.Response(text="OK", status=200)
        args = {
            "mode": request.query.get("mode", "municipalities"),
            "uf": request.query.get("uf", "AL"),
            "cnaeCode": request.query.get("cnaeCode", ""),
            "query": request.query.get("query", ""),
            "quality": request.query.get("quality", "minima"),
            "maxResults": int(request.query.get("maxResults", "50")),
        }
        rows = await asyncio.to_thread(run_query, args)
        await _charge_records(len(rows))
        return web.json_response({"count": len(rows), "items": rows})

    async def handle_post(request: web.Request) -> web.Response:
        payload = await request.json()
        if isinstance(payload, dict) and payload.get("jsonrpc") == "2.0":
            return web.json_response(await _handle_mcp_rpc(payload))
        rows = await asyncio.to_thread(run_query, payload if isinstance(payload, dict) else {})
        await _charge_records(len(rows))
        return web.json_response({"count": len(rows), "items": rows})

    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_root)
    app.router.add_post("/", handle_post)
    app.router.add_post("/mcp", handle_post)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    Actor.log.info("Brazil IBGE Standby HTTP/MCP server listening on port %s", port)
    await asyncio.Event().wait()


async def main() -> None:
    if Actor is None:
        raise RuntimeError("apify package is required to run Actor.main()")
    async with Actor:
        if os.environ.get("APIFY_META_ORIGIN") == "STANDBY":
            await _run_standby_server()
            return
        actor_input = await Actor.get_input() or {}
        rows = await asyncio.to_thread(run_query, actor_input)
        allowed = await _charge_records(len(rows))
        to_push = rows[:allowed] if allowed else []
        if to_push:
            await Actor.push_data(to_push)
        Actor.log.info("Delivered %d IBGE records.", len(to_push))


if __name__ == "__main__":
    asyncio.run(main())
