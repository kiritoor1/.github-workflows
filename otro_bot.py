import requests
from bs4 import BeautifulSoup
import os
import re
import urllib.parse
import ssl
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
import urllib3
import concurrent.futures

# --------------------------
# Configuración inicial
# --------------------------
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
BASE_URL = "https://www.clasificadosonline.com"

API_HISTORIAL = "https://ckrapps.tech/api_historial1.php"
BOT_TOKEN = os.getenv("BOT_TOKEN1")
CHAT_ID = os.getenv("CHAT_ID", "-4745765501")

# Nuevos pueblos solicitados
PUEBLOS = [
    "Metro",
    "Fajardo",
    "Cayey",
    "Caguas",
    "Salinas",
    "Canovanas",
    "R%EDo+Grande"  # Río Grande codificado correctamente
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9"
}

PATRONES = {
    'cuartos': re.compile(r"Cuartos[\s:\-]+(\d+)", re.IGNORECASE),
    'banos': re.compile(r"Baños[\s:\-]+([\d½¾¼]+(?:\s*[\d½¾¼/]+)?)", re.IGNORECASE),
    'telefono': re.compile(r'(\(\d{3}\)\s?\d{3}-\d{4}|\d{3}-\d{3}-\d{4}|\d{10})'),
    'precio': re.compile(r'\$(\d{1,3}(?:[.,]\d{3})*|\d+)', re.IGNORECASE)
}

class TLSAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx,
            **pool_kwargs
        )

def cargar_historial_remoto():
    try:
        resp = requests.get(API_HISTORIAL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        enlaces = data.get("enlaces", [])
        print(f"Debug: Se cargaron {len(enlaces)} enlaces del historial remoto.")
        return set(enlaces)
    except Exception as e:
        print(f"❌ Error al cargar historial remoto: {str(e)}")
        return set()

def guardar_historial_remoto(historial_set):
    data = {"enlaces": list(historial_set)}
    try:
        resp = requests.post(API_HISTORIAL, json=data, timeout=30)
        resp.raise_for_status()
        print("✅ Historial remoto actualizado correctamente.")
        print("Debug:", resp.text)
    except Exception as e:
        print(f"❌ Error al guardar historial remoto: {str(e)}")

def construir_url_busqueda(pueblo, offset=0):
    base = "https://www.clasificadosonline.com/UDREListing.asp"
    params = {
        'Category': '%',  # Cambiado a cualquier tipo de propiedad
        'LowPrice': '10000',  # Precio mínimo $10,000
        'HighPrice': '125000',  # Precio máximo $125,000
        'Bedrooms': '%',  # Cualquier cantidad de cuartos
        'Area': '',
        'Repo': 'Repo',
        'Opt': 'Opt',
        'BtnSearchListing': 'Ver Listado',
        'redirecturl': '/udrelistingmap.asp',
        'IncPrecio': '1'
    }
    if offset:
        params['offset'] = str(offset)
    query_string = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    return f"{base}?RESPueblos={pueblo}&{query_string}"

def obtener_listados_busqueda(url, pueblo):
    try:
        session = requests.Session()
        session.mount("https://", TLSAdapter())
        response = session.get(url, headers=HEADERS, verify=False, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"Error obteniendo listados para {pueblo} (url={url}): {str(e)}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    resultados = []

    bloques = soup.find_all("div", class_="dv-classified-row dv-classified-row-v2")
    if not bloques:
        bloques_alt = soup.find_all("div", class_=re.compile("classified-row"))
        if bloques_alt:
            bloques = bloques_alt

    for bloque in bloques:
        link_tag = bloque.find("a", href=re.compile("UDRealEstateDetail\\.asp"))
        if link_tag:
            enlace = urllib.parse.urljoin(BASE_URL, link_tag['href'])
            titulo = link_tag.get_text(strip=True)
            if enlace not in [r['link'] for r in resultados]:
                resultados.append({
                    'titulo': titulo,
                    'link': enlace,
                    'pueblo': pueblo
                })
    return resultados

def obtener_listados_por_pueblo(pueblo, max_offset=150, step=30):
    todos_listados = []
    for offset in range(0, max_offset + 1, step):
        url_busqueda = construir_url_busqueda(pueblo, offset)
        print(f"🔍 Buscando propiedades en {pueblo} con offset {offset}... URL: {url_busqueda}")
        listados = obtener_listados_busqueda(url_busqueda, pueblo)
        print(f"   ✅ Encontradas {len(listados)} propiedades en {pueblo} (offset {offset})")
        if not listados:
            break
        todos_listados.extend(listados)
        if len(listados) < step:
            break
    return todos_listados

def extraer_detalles(url):
    detalles = {'telefono': None, 'cuartos': None, 'banos': None, 'precio': None}
    try:
        session = requests.Session()
        session.mount("https://", TLSAdapter())
        response = session.get(url, headers=HEADERS, verify=False, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        contenido = soup.get_text()

        match_cuartos = PATRONES['cuartos'].search(contenido)
        if match_cuartos:
            detalles['cuartos'] = match_cuartos.group(1)

        match_banos = PATRONES['banos'].search(contenido)
        if match_banos:
            detalles['banos'] = match_banos.group(1)

        match_telefono = PATRONES['telefono'].search(contenido)
        if match_telefono:
            detalles['telefono'] = match_telefono.group()

        match_precio = PATRONES['precio'].search(contenido)
        if match_precio:
            precio = match_precio.group(1).replace(',', '').replace('.', '')
            precio_formateado = "{:,}".format(int(precio))
            detalles['precio'] = precio_formateado
    except Exception as e:
        print(f"Error extrayendo detalles de {url}: {str(e)}")
    return detalles

def limpiar_nombre_pueblo(pueblo):
    return urllib.parse.unquote(pueblo).replace("+", " ")

def dividir_mensaje_en_partes(mensaje, limite=4096):
    partes = []
    while len(mensaje) > limite:
        corte = mensaje[:limite].rfind('\n')
        if corte == -1:
            corte = limite
        partes.append(mensaje[:corte])
        mensaje = mensaje[corte:].strip()
    if mensaje:
        partes.append(mensaje)
    return partes

def enviar_telegram(nuevos):
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN no está definido. No se puede enviar a Telegram.")
        return

    mensaje_base = "<b>🚨 Nuevas Propiedades Encontradas</b>\n\n"
    for prop in nuevos:
        mensaje_base += f"🏠 <b>{prop['titulo']}</b>\n"
        mensaje_base += f"📍 Pueblo: {limpiar_nombre_pueblo(prop['pueblo'])}\n"
        mensaje_base += f"🔗 <a href='{prop['link']}'>Ver propiedad</a>\n"
        if prop.get('cuartos'):
            mensaje_base += f"🛏 Cuartos: {prop['cuartos']}\n"
        if prop.get('banos'):
            mensaje_base += f"🚿 Baños: {prop['banos']}\n"
        if prop.get('precio'):
            mensaje_base += f"💰 Precio: ${prop['precio']}\n"
        if prop.get('telefono'):
            mensaje_base += f"📞 Tel: {prop['telefono']}\n"
        mensaje_base += "\n"

    partes_mensaje = dividir_mensaje_en_partes(mensaje_base, 4096)
    for idx, parte in enumerate(partes_mensaje, 1):
        respuesta = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                'chat_id': CHAT_ID,
                'text': parte,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True
            }
        )
        if respuesta.status_code == 200:
            print(f"✅ Mensaje (parte {idx}/{len(partes_mensaje)}) enviado a Telegram.")
        else:
            print(f"❌ Error Telegram: {respuesta.text}")

def main():
    historial = cargar_historial_remoto()
    print(f"Debug: Antes de procesar, historial remoto tiene {len(historial)} enlaces.")

    nuevos = []

    for pueblo in PUEBLOS:
        print(f"=== Buscando en {pueblo} ===")
        listados_pueblo = obtener_listados_por_pueblo(pueblo, max_offset=150, step=30)
        print(f"   Total encontrados en {pueblo}: {len(listados_pueblo)}")

        listados_filtrados = [lst for lst in listados_pueblo if lst['link'] not in historial]
        print(f"   -> Nuevos en {pueblo}: {len(listados_filtrados)}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_listado = {
                executor.submit(extraer_detalles, lst['link']): lst
                for lst in listados_filtrados
            }
            for future in concurrent.futures.as_completed(future_to_listado):
                listado = future_to_listado[future]
                try:
                    detalles = future.result()
                    listado.update(detalles)
                    nuevos.append(listado)
                except Exception as exc:
                    print(f"Error procesando {listado['link']}: {exc}")

    if nuevos:
        print(f"🎉 Se encontraron {len(nuevos)} nuevas propiedades en total.")
        for prop in nuevos:
            historial.add(prop['link'])

        guardar_historial_remoto(historial)
        enviar_telegram(nuevos)
    else:
        print("🤷 No se encontraron nuevas propiedades en ninguno de los pueblos.")

if __name__ == "__main__":
    main()
