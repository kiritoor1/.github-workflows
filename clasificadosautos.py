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
import time

# --------------------------
# Configuración inicial
# --------------------------
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
BASE_URL = "https://www.clasificadosonline.com"

# ======== RUTAS REMOTAS (en tu servidor) ========
API_HISTORIAL = "https://ckrapps.tech/api_historial2.php"  # Ajusta si cambia la ruta

# ======== TOKEN Y CHAT_ID DESDE VARIABLES DE ENTORNO ========
BOT_TOKEN = os.getenv("BOT_TOKEN2")  # Se toma del entorno (sin exponerlo)
CHAT_ID = os.getenv("CHAT_ID", "-1002536693724")

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

# Patrones para extraer datos de la página de detalle de autos
PATRONES = {
    'marca_modelo': re.compile(r'Marca\s*:\s*([^<]+?)(?:<|$)', re.IGNORECASE),
    'ano': re.compile(r'Año\s*:\s*(\d{4})', re.IGNORECASE),
    'telefono': re.compile(r'(\(\d{3}\)\s?\d{3}-\d{4}|\d{3}-\d{3}-\d{4}|\d{10})'),
    'precio': re.compile(r'\$(\d{1,3}(?:[.,]\d{3})*|\d+)', re.IGNORECASE)
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
def cargar_historial_remoto(max_retries=3, delay=5):
    for attempt in range(max_retries):
        try:
            resp = requests.get(API_HISTORIAL, timeout=60)
            resp.raise_for_status()
            data = resp.json()
            enlaces = data.get("enlaces", [])
            print(f"Debug: Se cargaron {len(enlaces)} enlaces del historial remoto.")
            return set(enlaces)
        except Exception as e:
            print(f"❌ Intento {attempt + 1}/{max_retries} fallido: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(delay)
            else:
                print(f"❌ Todos los {max_retries} intentos fallaron. Devolviendo conjunto vacío.")
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

# ---------------------------------------------------------
# Funciones para scraping de autos
# ---------------------------------------------------------
def construir_url_busqueda(pueblo, offset=0):
    base = "https://www.clasificadosonline.com/UDTransListingADV.asp"
    params = {
        'Marca': '0',  # Todas las marcas
        'TipoC': '1',  # Tipo de vehículo (autos)
        'RESPueblos': pueblo,
        'FromYear': '0',  # Año mínimo
        'ToYear': '2025',  # Año máximo
        'LowPrice': '999',  # Precio mínimo
        'HighPrice': '10000',  # Precio máximo
        'Key': '',
        'Submit2': 'Buscar',
        'IncPrecio': '1',
        'AccessM': '0'
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
        link_tag = bloque.find("a", href=re.compile("UDTransDetail\\.asp"))
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
        print(f"🔍 Buscando autos en {pueblo} con offset {offset}...")
        listados = obtener_listados_busqueda(url_busqueda, pueblo)
        print(f"   ✅ Encontrados {len(listados)} autos en {pueblo} (offset {offset})")
        if not listados:
            break
        todos_listados.extend(listados)
        if len(listados) < step:
            break
    return todos_listados

def extraer_detalles(url):
    detalles = {'marca_modelo': None, 'ano': None, 'telefono': None, 'precio': None}
    try:
        session = requests.Session()
        session.mount("https://", TLSAdapter())
        response = session.get(url, headers=HEADERS, verify=False, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        contenido = soup.get_text()

        match_marca = PATRONES['marca_modelo'].search(contenido)
        if match_marca:
            detalles['marca_modelo'] = match_marca.group(1).strip()

        match_ano = PATRONES['ano'].search(contenido)
        if match_ano:
            detalles['ano'] = match_ano.group(1)

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

# ---------------------------------------------------------
# Dividir mensaje para Telegram
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

    mensaje_base = "<b>🚗 Nuevos Autos Encontrados</b>\n\n"
    for auto in nuevos:
        mensaje_base += f"🚙 <b>{auto['titulo']}</b>\n"
        mensaje_base += f"📍 Pueblo: {auto['pueblo']}\n"
        mensaje_base += f"🔗 <a href='{auto['link']}'>Ver auto</a>\n"
        if auto.get('marca_modelo'):
            mensaje_base += f"🏷 Marca/Modelo: {auto['marca_modelo']}\n"
        if auto.get('ano'):
            mensaje_base += f"📅 Año: {auto['ano']}\n"
        if auto.get('precio'):
            mensaje_base += f"💰 Precio: ${auto['precio']}\n"
        if auto.get('telefono'):
            mensaje_base += f"📞 Tel: {auto['telefono']}\n"
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
# Función principal
# ---------------------------------------------------------
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
        print(f"🎉 Se encontraron {len(nuevos)} nuevos autos en total.")
        for auto in nuevos:
            historial.add(auto['link'])

        guardar_historial_remoto(historial)
        enviar_telegram(nuevos)
    else:
        print("🤷 No se encontraron nuevos autos en ninguno de los pueblos.")

# ---------------------------------------------------------
if __name__ == "__main__":
    main()
