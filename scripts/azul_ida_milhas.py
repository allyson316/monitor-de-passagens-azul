#!/usr/bin/env python3
"""
Monitor Azul Airlines — IDA (Campinas → Europa) em MILHAS
Busca só ida de VCP para Lisboa/Porto/Madri.

Pré-requisitos:
    pip install playwright requests
    playwright install chromium

Uso:
    python3 azul_ida_milhas.py
"""

import json
import warnings
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")

import requests as http_requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ─── Configurações ──────────────────────────────────────────────────────────
ORIGEM = {"code": "VCP", "geoId": "6300637", "nome": "Campinas (VCP)"}

DESTINOS = [
    {"code": "LIS", "geoId": "6301792", "nome": "Lisboa (LIS)"},
    {"code": "OPO", "geoId": "6299688", "nome": "Porto (OPO)"},
    {"code": "MAD", "geoId": "6299345", "nome": "Madri (MAD)"},
]

DESTINOS_PRIORITARIOS = ["Lisboa (LIS)"]

PRECO_MAX_BRL    = 1700
PRECO_MAX_MILHAS = 110_000

URL_SITE    = "https://passagens.voeazul.com.br/pt/melhores-ofertas"
URL_GRAPHQL = "https://vg-api.airtrfx.com/graphql"

MODULE_ID   = "6389704d8a79d3457f65333f"  # "Voos da Azul com preços especiais"

GRAPHQL_QUERY = (
    "query GetStandardFareModule($page: PageInput!, $id: String!, "
    "$pageNumber: Int, $limit: Int, $flatContext: FlatContextInput, "
    "$urlParameters: StandardFareModuleUrlParameters, "
    "$filters: StandardFareModuleFiltersInput, "
    "$nearestOriginAirport: AirportInput) {\n"
    "  standardFareModule(page: $page, id: $id, pageNumber: $pageNumber, "
    "limit: $limit, flatContext: $flatContext, urlParameters: $urlParameters, "
    "filters: $filters, nearestOriginAirport: $nearestOriginAirport) {\n"
    "    id\n    pagination { currentPage lastPage total __typename }\n"
    "    fares(pageNumber: $pageNumber, limit: $limit, "
    "urlParameters: $urlParameters, "
    "nearestOriginAirport: $nearestOriginAirport) {\n"
    "      originCity destinationCity\n"
    "      originAirportCode destinationAirportCode\n"
    "      departureDate formattedDepartureDate\n"
    "      returnDate formattedReturnDate\n"
    "      flightType formattedFlightType\n"
    "      totalPrice formattedTotalPrice\n"
    "      currencyCode currencySymbol\n"
    "      redemption { unit amount formattedAmount category __typename }\n"
    "      priceLastSeen { value unit __typename }\n"
    "      __typename\n"
    "    }\n    error\n    __typename\n  }\n}\n"
)

# ─── Obter token JWT ─────────────────────────────────────────────────────────

def obter_token():
    """Abre o site com Playwright apenas para capturar o Bearer token."""
    token = None

    def on_request(req):
        nonlocal token
        if 'graphql' in req.url.lower() and req.method == 'POST':
            auth = req.headers.get('authorization', '')
            if auth.startswith('Bearer ') and not token:
                token = auth

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        page = ctx.new_page()
        page.on("request", on_request)
        page.goto(URL_SITE, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(10_000)
        browser.close()

    return token

# ─── Chamada GraphQL ──────────────────────────────────────────────────────────

def buscar_fares_graphql(token, destino, journey_type="ONE_WAY", page_num=1):
    """Faz chamada GraphQL direta para buscar fares filtrados."""
    variables = {
        "page": {"tenant": "ad", "slug": "melhores-ofertas", "siteEdition": "pt"},
        "id": MODULE_ID,
        "pageNumber": page_num,
        "limit": 50,
        "flatContext": {"templateId": "6232e481fe2bcb1d00002c49", "templateName": "home"},
        "filters": {
            "origin": {"code": ORIGEM["code"], "geoId": ORIGEM["geoId"]},
            "destination": {"code": destino["code"], "geoId": destino["geoId"]},
            "budget": {"max": PRECO_MAX_MILHAS},
            "redemptionUnit": "POINTS",
            "journeyType": journey_type,
            "sorting": "PRICE_ASC",
        },
        "urlParameters": {},
        "nearestOriginAirport": {},
    }

    payload = [{
        "operationName": "GetStandardFareModule",
        "variables": variables,
        "query": GRAPHQL_QUERY,
    }]

    headers = {
        "authorization": token,
        "content-type": "application/json",
        "referer": URL_SITE,
        "accept": "*/*",
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    }

    resp = http_requests.post(URL_GRAPHQL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if isinstance(data, list) and len(data) > 0:
        sfm = data[0].get("data", {}).get("standardFareModule", {})
        return sfm.get("fares", []), sfm.get("pagination", {})

    return [], {}

# ─── Processar fares ──────────────────────────────────────────────────────────

def processar_fare(fare, destino_nome):
    """Converte um fare da API em oferta padronizada."""
    preco_brl = None
    preco_milhas = None

    redemption = fare.get("redemption")
    if redemption and redemption.get("amount"):
        preco_milhas = float(redemption["amount"])

    # totalPrice em BRL só faz sentido quando NÃO é redemption (pontos)
    total_price = fare.get("totalPrice")
    if total_price and fare.get("currencyCode") == "BRL" and not redemption:
        preco_brl = float(total_price)

    oferta = {
        "destinos": [destino_nome],
        "origem": f"{fare.get('originCity', '')} ({fare.get('originAirportCode', '')})",
        "tem_origem_vcp": fare.get("originAirportCode") == ORIGEM["code"],
        "preco_brl": preco_brl,
        "preco_milhas": preco_milhas,
        "data_embarque": fare.get("formattedDepartureDate"),
        "data_retorno": fare.get("formattedReturnDate"),
        "tipo": fare.get("formattedFlightType", ""),
        "last_seen": None,
        "link": URL_SITE,
        "alerta": False,
        "motivos": [],
    }

    pls = fare.get("priceLastSeen")
    if pls:
        unit_map = {"day": "dia", "hour": "hora", "hours": "hora", "minute": "minuto", "minutes": "minuto"}
        unit_pt = unit_map.get(pls["unit"], pls["unit"])
        val = int(pls["value"]) if pls["value"] else 0
        plural = "s" if val > 1 else ""
        oferta["last_seen"] = f"Visto: {val} {unit_pt}{plural} atrás"

    if preco_brl and preco_brl <= PRECO_MAX_BRL:
        oferta["alerta"] = True
        oferta["motivos"].append(f"R${preco_brl:.0f} ≤ R${PRECO_MAX_BRL}")

    if preco_milhas and preco_milhas <= PRECO_MAX_MILHAS:
        oferta["alerta"] = True
        oferta["motivos"].append(f"{preco_milhas:,.0f} milhas ≤ {PRECO_MAX_MILHAS:,}")

    return oferta

# ─── Busca principal ──────────────────────────────────────────────────────────

def buscar_ofertas():
    print("Obtendo token de autenticação...")
    token = obter_token()
    if not token:
        print("ERRO: não foi possível obter o token JWT.")
        return []

    print(f"Token obtido. Buscando ofertas via API...\n")

    todas_ofertas = []

    for destino in DESTINOS:
        print(f"  {ORIGEM['nome']} → {destino['nome']}...")

        for jt, jt_label in [("ONE_WAY", "Só ida")]:
            try:
                fares, pagination = buscar_fares_graphql(token, destino, journey_type=jt)
                total = pagination.get("total", len(fares))
                print(f"    {jt_label}: {len(fares)} fares (total disponível: {total})")

                for fare in fares:
                    oferta = processar_fare(fare, destino["nome"])
                    oferta["tipo"] = jt_label
                    todas_ofertas.append(oferta)

            except Exception as e:
                print(f"    ERRO ({jt_label}): {e}")

    return todas_ofertas

# ─── Formatação ───────────────────────────────────────────────────────────────

def formatar_preco(oferta):
    partes = []
    if oferta["preco_brl"]:
        partes.append(f"R${oferta['preco_brl']:,.2f}")
    if oferta["preco_milhas"]:
        partes.append(f"{oferta['preco_milhas']:,.0f} pontos")
    return " | ".join(partes) or "preço não identificado"


def imprimir_lista_ofertas(titulo, ofertas):
    if not ofertas:
        return
    print(f"\n{titulo}\n")
    for oferta in ofertas:
        destino = ", ".join(oferta["destinos"])
        preco = formatar_preco(oferta)
        data = oferta["data_embarque"] or "?"
        tipo = oferta["tipo"]
        seen = oferta.get("last_seen") or ""
        print(f"  - {destino} | {preco} | {tipo} | embarque {data} | {seen}")

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*55}")
    print(f"Monitor Azul Airlines — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"Rota: {ORIGEM['nome']} → {' / '.join(d['nome'] for d in DESTINOS)}")
    print(f"Limites: ≤ R${PRECO_MAX_BRL:,} | ≤ {PRECO_MAX_MILHAS:,} pontos")
    print(f"{'='*55}\n")

    ofertas = buscar_ofertas()
    alertas = [o for o in ofertas if o["alerta"]]

    print(f"\nOfertas encontradas : {len(ofertas)}")
    print(f"Dentro do limite    : {len(alertas)}")

    if alertas:
        print(f"\n🚨 ALERTA! {len(alertas)} oferta(s) dentro do seu limite.")
        imprimir_lista_ofertas("Ofertas dentro do limite:", alertas)
    else:
        print("\n✅ Nenhuma oferta dentro do limite agora.")

    imprimir_lista_ofertas("Todas as ofertas encontradas:", ofertas)

if __name__ == "__main__":
    main()
