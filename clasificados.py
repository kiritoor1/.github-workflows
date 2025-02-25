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

# ======== RUTAS REMOTAS (en tu servidor) ========
API_HISTORIAL = "https://ckrapps.tech/api_historial.php"  # Ajusta si cambia la ruta

# ======== TOKEN Y CHAT_ID DESDE VARIABLES DE ENTORNO ========
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Se toma del entorno (sin exponerlo)
CHAT_ID = os.getenv("CHAT_ID", "-1002252436524")

# Lista de pueblos deseados
PUEBLOS = [
    "Ponce", "Juana Díaz", "Santa Isabel", "Coamo", 
    "Guayama", "Peñuelas", "Guanica", "Guayanilla", "Yauco"
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9"
}

# Patrones para extraer datos de la página de detalle
PATRONES = {
    'cuartos': re.compile(r"Cuartos[\s:\-]+(\d+)", re.IGNORECASE),
    'banos': re.compile(r"Baños[\s:\-]+([\d½¾¼]+(?:\s*[\d½¾¼/]+)?)", re.IGNORECASE),
    'telefono': re.compile(r'(\(\d{3}\)\s?\d{3}-\d{4}|\d{3}-\d{3}-\d{4}|\d{10})'),
    'precio': re.compile(r'\$(\d{1,3}(?:[.,]\d{3})*|\d+)', re.IGNORECASE)  # Patrón para capturar precios como "$120,000" o "$120000"
}

# --------------------------
# Adaptador para conexiones SSL sin verificación
# --------------------------
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

# ---------------------------------------------------------
# FUNCIONES PARA MANEJAR EL HISTORIAL EN TU SERVIDOR PHP
# ---------------------------------------------------------
def cargar_historial_remoto():
    """
    Hace un GET a https://ckrapps.tech/api_historial.php
    Debe retornar un JSON con {"enlaces": [...]}.
    Lo convertimos a un set() para manejar duplicados en Python.
    """
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
    """
    Hace un POST a https://ckrapps.tech/api_historial.php con {"enlaces": [...]}
    sobrescribiendo el historial remoto.
    """
    data = {"enlaces": list(historial_set)}
    try:
        resp = requests.post(API_HISTORIAL, json=data, timeout=30)
        resp.raise_for_status()
        print("✅ Historial remoto actualizado correctamente.")
        print("Debug:", resp.text)
    except Exception as e:
        print(f"❌ Error al guardar historial remoto: {str(e)}")

# ---------------------------------------------------------
# Resto de funciones para scraping
# ---------------------------------------------------------
def construir_url_busqueda(pueblo, offset=0):
    base = "https://www.clasificadosonline.com/UDREListing.asp"
    params = {
        'RESPueblos': pueblo,
        'Category': 'Casa',
        'LowPrice': '0',
        'HighPrice': '999999999',
        'Bedrooms': '%',
        'Area': '',
        'Repo': 'Repo',
        'Opt': 'Opt',
        'BtnSearchListing': 'Ver Listado',
        'redirecturl': '/udrelistingmap.asp',
        'IncPrecio': '1'
    }
    if offset:
        params['offset'] = str(offset)
    return f"{base}?{urllib.parse.urlencode(params)}"

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
        print(f"No se encontraron bloques de listados en esta página para {pueblo}.")
        return []

    for bloque in bloques:
        link_tag = bloque.find("a", href=re.compile("UDRealEstateDetail\\.asp"))
        if link_tag:
            enlace = urllib.parse.urljoin(BASE_URL, link_tag['href'])
            titulo = link_tag.get_text(strip=True)
            # Evitamos duplicados en la misma búsqueda
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
        print(f"🔍 Buscando casas en {pueblo} con offset {offset}...")
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
        # Usamos BeautifulSoup para obtener el texto limpio
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
            # Normalizamos el precio, eliminando comas y asegurándonos de que sea un formato limpio
            precio = match_precio.group(1).replace(',', '').replace('.', '')
            # Formateamos el precio con comas para separar los miles
            precio_formateado = "{:,}".format(int(precio))
            detalles['precio'] = precio_formateado
    except Exception as e:
        print(f"Error extrayendo detalles de {url}: {str(e)}")
    return detalles
# ---------------------------------------------------------
# Dividir mensaje en caso de exceder 4096 caracteres (Telegram)
# ---------------------------------------------------------
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
        mensaje_base += f"📍 Pueblo: {prop['pueblo']}\n"
        mensaje_base += f"🔗 <a href='{prop['link']}'>Ver propiedad</a>\n"
        if prop.get('cuartos'):
            mensaje_base += f"🛏 Cuartos: {prop['cuartos']}\n"
        if prop.get('banos'):
            mensaje_base += f"🚿 Baños: {prop['banos']}\n"
        if prop.get('precio'):
            # Aquí agregamos el símbolo $ antes del precio formateado
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

# ---------------------------------------------------------
# Función principal (ya sin listings.txt local)
# ---------------------------------------------------------
def main():
    # 1. Cargar historial desde tu servidor PHP
    historial = cargar_historial_remoto()
    print(f"Debug: Antes de procesar, historial remoto tiene {len(historial)} enlaces.")

    nuevos = []

    # 2. Recorrer los pueblos y obtener listados
    for pueblo in PUEBLOS:
        print(f"=== Buscando en {pueblo} ===")
        listados_pueblo = obtener_listados_por_pueblo(pueblo, max_offset=150, step=30)
        print(f"   Total encontrados en {pueblo}: {len(listados_pueblo)}")

        # Filtrar los que no están en el historial
        listados_filtrados = [lst for lst in listados_pueblo if lst['link'] not in historial]
        print(f"   -> Nuevos en {pueblo}: {len(listados_filtrados)}")

        # 3. Extraer detalles en paralelo
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

    # 4. Si hay propiedades nuevas, actualizar historial remoto y notificar
    if nuevos:
        print(f"🎉 Se encontraron {len(nuevos)} nuevas propiedades en total.")
        # Agregar los nuevos al historial
        for prop in nuevos:
            historial.add(prop['link'])

        # Guardar historial REMOTO
        guardar_historial_remoto(historial)

        # Enviar notificaciones a Telegram
        enviar_telegram(nuevos)
    else:
        print("🤷 No se encontraron nuevas propiedades en ninguno de los pueblos.")

# ---------------------------------------------------------
if __name__ == "__main__":
    main()
