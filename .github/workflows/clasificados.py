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
ARCHIVO_LISTADOS = "listings.txt"  # Archivo de historial

# Configuración de Telegram (ajusta con tus datos)
BOT_TOKEN = "7659368647:AAEpvdAnkC7D3OcHK0uEHwzui44id8L25vI"
# Asegúrate de usar el Chat ID correcto (para grupos suele ser un número negativo)
CHAT_ID = "-4653605997"

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
    'telefono': re.compile(r'(\(\d{3}\)\s?\d{3}-\d{4}|\d{3}-\d{3}-\d{4}|\d{10})')
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

# --------------------------
# Función para construir la URL de búsqueda para un pueblo y un offset dado
# --------------------------
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

# --------------------------
# Función para extraer listados de una página (usando el bloque de anuncios)
# --------------------------
def obtener_listados_busqueda(url, pueblo):
    try:
        session = requests.Session()
        session.mount("https://", TLSAdapter())
        response = session.get(url, headers=HEADERS, verify=False, timeout=30)
        response.raise_for_status()
    except Exception as e:
        print(f"Error obteniendo listados para {pueblo} (offset incluido): {str(e)}")
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
            if enlace not in [r['link'] for r in resultados]:
                resultados.append({
                    'titulo': titulo,
                    'link': enlace,
                    'pueblo': pueblo
                })
    return resultados

# --------------------------
# Función para iterar sobre la paginación para un mismo pueblo
# --------------------------
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
        # Si se reciben menos resultados de los esperados (menos que el step), asumimos que es la última página.
        if len(listados) < step:
            break
    return todos_listados

# --------------------------
# Función para extraer detalles de la página individual de cada propiedad
# --------------------------
def extraer_detalles(url):
    detalles = {'telefono': None, 'cuartos': None, 'banos': None}
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
    except Exception as e:
        print(f"Error extrayendo detalles de {url}: {str(e)}")
    return detalles

# --------------------------
# Funciones para manejar historial (para evitar duplicados)
# --------------------------
def cargar_historial():
    if not os.path.exists(ARCHIVO_LISTADOS):
        return set()
    with open(ARCHIVO_LISTADOS, 'r', encoding='utf-8') as f:
        return {linea.strip() for linea in f if linea.strip()}

def guardar_historial(historial_set):
    with open(ARCHIVO_LISTADOS, 'w', encoding='utf-8') as f:
        for link in historial_set:
            f.write(link + '\n')

# --------------------------
# Función para enviar notificaciones a Telegram,
# dividiendo el mensaje si excede el límite de caracteres.
# --------------------------
def enviar_telegram(nuevos):
    # Construimos el mensaje base
    mensaje_base = "<b>🚨 Nuevas Propiedades Encontradas</b>\n\n"
    for prop in nuevos:
        mensaje_base += f"🏠 <b>{prop['titulo']}</b>\n"
        mensaje_base += f"📍 Pueblo: {prop['pueblo']}\n"
        mensaje_base += f"🔗 <a href='{prop['link']}'>Ver propiedad</a>\n"
        if prop.get('cuartos'):
            mensaje_base += f"🛏 Cuartos: {prop['cuartos']}\n"
        if prop.get('banos'):
            mensaje_base += f"🚿 Baños: {prop['banos']}\n"
        if prop.get('telefono'):
            mensaje_base += f"📞 Tel: {prop['telefono']}\n"
        mensaje_base += "\n"
    
    # Límite oficial de caracteres para el campo "text" en Telegram
    LIMITE_TELEGRAM = 4096
    
    # Función para dividir el mensaje en partes
    def dividir_mensaje_en_partes(mensaje, limite):
        partes = []
        while len(mensaje) > limite:
            # Encontrar la posición para partir (lo más cercano al final sin pasarse)
            corte = mensaje[:limite].rfind('\n')
            if corte == -1:
                # Si no encuentra salto de línea, cortamos en el límite exacto
                corte = limite
            partes.append(mensaje[:corte])
            mensaje = mensaje[corte:].strip()
        # Agregar la última parte (o la única si nunca excedió el límite)
        if mensaje:
            partes.append(mensaje)
        return partes
    
    partes_mensaje = dividir_mensaje_en_partes(mensaje_base, LIMITE_TELEGRAM)
    
    for parte in partes_mensaje:
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
            print("✅ Mensaje enviado a Telegram (parte).")
        else:
            print(f"❌ Error Telegram: {respuesta.text}")

# --------------------------
# Función principal
# --------------------------
def main():
    historial = cargar_historial()
    nuevos = []
    
    for pueblo in PUEBLOS:
        print(f"=== Buscando en {pueblo} ===")
        listados_pueblo = obtener_listados_por_pueblo(pueblo, max_offset=150, step=30)
        print(f"   Total encontrados en {pueblo}: {len(listados_pueblo)}")
        
        # Filtrar los listados que aún no han sido procesados
        listados_filtrados = [lst for lst in listados_pueblo if lst['link'] not in historial]
        
        # Usar ThreadPoolExecutor para extraer detalles en paralelo
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_listado = {executor.submit(extraer_detalles, lst['link']): lst for lst in listados_filtrados}
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
        # Actualizar historial
        for prop in nuevos:
            historial.add(prop['link'])
        guardar_historial(historial)
        
        # Enviar solo a Telegram
        enviar_telegram(nuevos)
    else:
        print("🤷 No se encontraron nuevas propiedades en ninguno de los pueblos.")

if __name__ == "__main__":
    main()
