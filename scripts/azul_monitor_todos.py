#!/usr/bin/env python3
"""
Monitor Azul Airlines — Todos os cenários
Roda ida e volta, milhas e reais, com um único token.

Uso:
    python3 azul_monitor_todos.py
"""

import json
from pathlib import Path
import warnings
warnings.filterwarnings("ignore", message=".*urllib3.*OpenSSL.*")

import requests as http_requests
from datetime import datetime
from playwright.sync_api import sync_playwright

# ─── Configurações ──────────────────────────────────────────────────────────
VCP = {"code": "VCP", "geoId": "6300637", "nome": "Campinas (VCP)"}

NORDESTE = [
    {"code": "REC", "geoId": "6300663", "nome": "Recife (REC)"},
    {"code": "NAT", "geoId": "8531982", "nome": "Natal (NAT)"},
    {"code": "JDO", "geoId": "3402889", "nome": "Juazeiro do Norte (JDO)"},
]

PRECO_MAX_MILHAS = 20_000

# ─── Telegram ───────────────────────────────────────────────────────────────
TELEGRAM_CONFIG = json.loads(
    Path(__file__).with_name("telegram_config.json").read_text()
)

TELEGRAM_TOKEN = TELEGRAM_CONFIG["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_IDS = TELEGRAM_CONFIG["TELEGRAM_CHAT_IDS"]

URL_SITE    = "https://passagens.voeazul.com.br/pt/melhores-ofertas"
URL_GRAPHQL = "https://vg-api.airtrfx.com/graphql"
MODULE_ID   = "6389704d8a79d3457f65333f"

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

# ─── Token ────────────────────────────────────────────────────────────────────

def obter_token():
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

# ─── GraphQL ──────────────────────────────────────────────────────────────────

def buscar_fares(token, origem, destino, redemption_unit, budget_max):
    variables = {
        "page": {"tenant": "ad", "slug": "melhores-ofertas", "siteEdition": "pt"},
        "id": MODULE_ID,
        "pageNumber": 1,
        "limit": 50,
        "flatContext": {"templateId": "6232e481fe2bcb1d00002c49", "templateName": "home"},
        "filters": {
            "origin": {"code": origem["code"], "geoId": origem["geoId"]},
            "destination": {"code": destino["code"], "geoId": destino["geoId"]},
            "budget": {"max": budget_max},
            "redemptionUnit": redemption_unit,
            "journeyType": "ONE_WAY",
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

# ─── Helpers ──────────────────────────────────────────────────────────────────

def formatar_brl(valor):
    s = f"{valor:,.2f}"
    s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R${s}"


def last_seen_pt(fare):
    pls = fare.get("priceLastSeen")
    if not pls:
        return ""
    unit_map = {"day": "dia", "hour": "hora", "hours": "hora", "minute": "minuto", "minutes": "minuto"}
    unit_pt = unit_map.get(pls["unit"], pls["unit"])
    val = int(pls["value"]) if pls["value"] else 0
    plural = "s" if val > 1 else ""
    return f"visto {val} {unit_pt}{plural} atrás"


def is_recent_enough(fare, max_days=1):
    pls = fare.get("priceLastSeen")
    if not pls:
        return True
    unit = pls.get("unit", "").lower()
    val = int(pls.get("value") or 0)
    if "minute" in unit or "hour" in unit:
        return True
    if "day" in unit:
        return val <= max_days
    if "week" in unit or "month" in unit or "year" in unit:
        return False
    return True


def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {
            "chat_id": chat_id,
            "text": mensagem,
            "parse_mode": "HTML",
        }
        try:
            resp = http_requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                print(f"📩 Mensagem enviada ao Telegram (chat {chat_id}).")
            else:
                print(f"⚠️ Telegram erro (chat {chat_id}): {resp.status_code} — {resp.text}")
        except Exception as e:
            print(f"⚠️ Telegram erro (chat {chat_id}): {e}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"\n{'='*55}")
    print(f"  Monitor Azul Airlines — {agora}")
    print(f"  Limites: ≤ {PRECO_MAX_MILHAS:,} pontos")
    print(f"{'='*55}")

    print("\nObtendo token de autenticação...")
    token = obter_token()
    if not token:
        print("ERRO: não foi possível obter o token JWT.")
        return

    print("Token obtido.\n")

    total_ofertas = 0
    total_alertas = 0
    msg_partes = []
    msg_partes.append(f"✈️ <b>Azul Alert</b> — {agora}")
    msg_partes.append(f"Limites: ≤ {PRECO_MAX_MILHAS:,} pontos\n")

    cenarios = [
        ("IDA (VCP → Nordeste)",   VCP, NORDESTE, "POINTS",   PRECO_MAX_MILHAS, True),
        ("VOLTA (Nordeste → VCP)", NORDESTE, [VCP], "POINTS",   PRECO_MAX_MILHAS, True),
    ]

    for label, origens, destinos, unit, budget, is_milhas in cenarios:
        if isinstance(origens, dict):
            origens = [origens]

        all_ofertas = []

        print(f"\n{'─'*55}")
        print(f"  {label}")
        print(f"{'─'*55}")

        for origem in origens:
            for dest in destinos:
                rota = f"{origem['nome']} → {dest['nome']}"
                try:
                    fares, pagination = buscar_fares(token, origem, dest, unit, budget)
                    total = pagination.get("total", len(fares))
                    print(f"  {rota}: {len(fares)} fares (total: {total})")

                    for fare in fares:
                        if is_milhas:
                            redemption = fare.get("redemption")
                            preco = float(redemption["amount"]) if redemption and redemption.get("amount") else None
                            dentro = preco is not None and preco <= budget
                            preco_fmt = f"{preco:,.0f} pontos" if preco else "?"
                        else:
                            tp = fare.get("totalPrice")
                            preco = float(tp) if tp else None
                            dentro = preco is not None and preco <= budget
                            preco_fmt = formatar_brl(preco) if preco else "?"

                        recente = is_recent_enough(fare, max_days=1)
                        all_ofertas.append({
                            "rota": rota,
                            "preco_fmt": preco_fmt,
                            "data": fare.get("formattedDepartureDate", "?"),
                            "seen": last_seen_pt(fare),
                            "dentro": dentro and recente,
                        })

                except Exception as e:
                    print(f"  {rota}: ERRO — {e}")

        alertas = [o for o in all_ofertas if o["dentro"]]

        if alertas:
            print(f"\n  🚨 {len(alertas)} oferta(s) dentro do limite:\n")
            msg_partes.append(f"🚨 <b>{label}</b> ({len(alertas)} ofertas)")
            for o in alertas:
                print(f"    {o['rota']} | {o['preco_fmt']} | embarque {o['data']} | {o['seen']}")
                msg_partes.append(f"  • {o['rota']} | {o['preco_fmt']} | {o['data']} | {o['seen']}")
            msg_partes.append("")
        else:
            print(f"\n  ✅ Nenhuma oferta dentro do limite.")

        total_ofertas += len(all_ofertas)
        total_alertas += len(alertas)

    print(f"\n{'='*55}")
    print(f"  RESUMO: {total_ofertas} ofertas encontradas | {total_alertas} dentro do limite")
    print(f"{'='*55}\n")

    if total_alertas > 0:
        msg_partes.append(f"📊 {total_ofertas} ofertas | {total_alertas} dentro do limite")
        enviar_telegram("\n".join(msg_partes))
    else:
        print("Sem alertas — Telegram não notificado.")

if __name__ == "__main__":
    main()
