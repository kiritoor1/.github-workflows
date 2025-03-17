import requests
from bs4 import BeautifulSoup
import csv
from collections import Counter
from datetime import datetime, timedelta
import logging
import random
import pytz
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import telegram
import asyncio

# Configurar logging
logging.basicConfig(filename="pega_bot_avanzado.log", level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# Configuración de Telegram
TELEGRAM_TOKEN = "7458538344:AAG0dQvkgEA99oxY5OMTocN_UtS948Z5lnU"
TELEGRAM_CHAT_ID = "-1002594359155"

# Función para enviar mensaje a Telegram (asíncrona)
async def enviar_telegram(mensaje):
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje)
        logging.info("Mensaje enviado a Telegram.")
    except Exception as e:
        logging.error(f"Error al enviar a Telegram: {e}")
        print(f"Error al enviar a Telegram: {e}")

# Recolectar historial de LottoStrategies (combinado Día y Noche)
def buscar_historial_lottostrategies(juego="Pega 3"):
    sorteos = []
    urls = {
        "Pega 3": {
            "Día": "https://www.lottostrategies.com/cgi-bin/winning_of_past_month/100/PRE/PR/Puerto-Rico-PR-Pega-3-Day-lottery-results.html",
            "Noche": "https://www.lottostrategies.com/cgi-bin/winning_of_past_month/100/PRB/PR/Puerto-Rico-PR-Pega-3-Noche-lottery-results.html"
        },
        "Pega 2": {
            "Día": "https://www.lottostrategies.com/cgi-bin/winning_of_past_month/100/PRD/PR/Puerto-Rico-PR-Pega-2-Day-lottery-results.html",
            "Noche": "https://www.lottostrategies.com/cgi-bin/winning_of_past_month/100/PRC/PR/Puerto-Rico-PR-Pega-2-Noche-lottery-results.html"
        }
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    for tipo, url in urls[juego].items():
        try:
            response = requests.get(url, headers=headers, timeout=5)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            filas = soup.find_all("tr")[1:31]  # Limitar a 30 sorteos por tipo
            for fila in filas:
                celdas = fila.find_all("td")
                if len(celdas) >= 2:
                    fecha_raw = celdas[0].text.strip()
                    numeros = celdas[1].text.strip().replace("-", "")[:3 if juego == "Pega 3" else 2]
                    fecha_parts = fecha_raw.split()
                    if len(fecha_parts) >= 2:
                        fecha = fecha_parts[1]  # MM/DD/YY
                        if validar_datos(fecha, numeros):
                            sorteos.append({"fecha": fecha, "tipo": tipo, "numeros": numeros, "juego": juego})
        except requests.RequestException as e:
            logging.error(f"Error al acceder a LottoStrategies ({juego} {tipo}): {e}")
            print(f"Error al acceder a LottoStrategies ({juego} {tipo}): {e}")
    return sorteos

# Validar formato de fecha y números
def validar_datos(fecha, numeros):
    try:
        datetime.strptime(fecha, "%m/%d/%y")
        return (len(numeros) == 3 and numeros.isdigit()) or (len(numeros) == 2 and numeros.isdigit())
    except ValueError:
        return False

# Guardar datos en CSV
def guardar_datos_csv(sorteos, archivo="pega_datos_historico.csv"):
    sorteos_unicos = list({(s["fecha"], s["tipo"], s["juego"]): s for s in sorteos}.values())
    with open(archivo, "w", newline="") as csvfile:
        fieldnames = ["fecha", "tipo", "juego", "numeros"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorteos_unicos)
    return sorteos_unicos

# Preparar datos para ML (sin distinguir Día/Noche)
def preparar_datos_ml(sorteos, juego):
    df = pd.DataFrame([s for s in sorteos if s["juego"] == juego])
    df["fecha"] = pd.to_datetime(df["fecha"], format="%m/%d/%y")
    df = df.sort_values("fecha").tail(60)  # Últimos 60 sorteos (Día + Noche)
    
    df["dia_semana"] = df["fecha"].dt.dayofweek
    num_pos = 3 if juego == "Pega 3" else 2
    for i in range(num_pos):
        df[f"pos_{i+1}"] = df["numeros"].str[i].astype(int)
        df[f"freq_reciente_pos_{i+1}"] = df[f"pos_{i+1}"].rolling(window=20, min_periods=1).apply(lambda x: Counter(x).most_common(1)[0][0], raw=True)
    return df

# Entrenar modelo Random Forest
def entrenar_modelo(df, posicion):
    X = df[["dia_semana", f"freq_reciente_pos_{posicion}"]]
    y = df[f"pos_{posicion}"]
    modelo = RandomForestClassifier(n_estimators=50, random_state=42, max_depth=8)
    modelo.fit(X, y)
    return modelo

# Generar 20 predicciones para todo el día
def analizar_pega_avanzado(sorteos, juego, num_combinaciones=20, estrategia="balanceada"):
    sorteos_filtrados = [s for s in sorteos if s["juego"] == juego]
    if len(sorteos_filtrados) < 20:
        print(f"No hay suficientes sorteos de {juego}.")
        return None, ""

    # Preparar datos y entrenar modelos
    df = preparar_datos_ml(sorteos_filtrados, juego)
    modelos = [entrenar_modelo(df, i+1) for i in range(3 if juego == "Pega 3" else 2)]
    ultimos_sorteos = [s["numeros"] for s in sorteos_filtrados[-10:]]  # Últimos 10 sorteos

    # Frecuencias recientes
    posiciones = [df[f"pos_{i+1}"].tolist() for i in range(3 if juego == "Pega 3" else 2)]
    freq_posiciones = [Counter(pos[-20:]) for pos in posiciones]  # Últimos 20 sorteos
    top_posiciones = [[x[0] for x in freq.most_common(3)] for freq in freq_posiciones]

    # Generar combinaciones
    combinaciones = set()
    if estrategia == "segura" or estrategia == "balanceada":
        while len(combinaciones) < num_combinaciones:
            comb = "".join(str(modelo.predict(df[["dia_semana", f"freq_reciente_pos_{i+1}"]].iloc[-1:])[0]) 
                           for i, modelo in enumerate(modelos))
            if comb not in ultimos_sorteos and comb not in combinaciones:
                combinaciones.add(comb)
            else:
                comb = "".join(str(random.choice(top_posiciones[i])) for i in range(len(top_posiciones)))
                if comb not in ultimos_sorteos and comb not in combinaciones:
                    combinaciones.add(comb)
    elif estrategia == "arriesgada":
        while len(combinaciones) < num_combinaciones:
            comb = "".join(str(random.randint(0, 9)) for _ in range(3 if juego == "Pega 3" else 2))
            if comb not in ultimos_sorteos and comb not in combinaciones:
                combinaciones.add(comb)

    combinaciones = list(combinaciones)
    mensaje = f"🎲 *{juego} - Todo el Día (Estrategia: {estrategia})*\n"
    mensaje += f"20 Predicciones válidas para Día y Noche:\n"
    for i, comb in enumerate(combinaciones, 1):
        try:
            confianza = sum(modelo.predict_proba(df[["dia_semana", f"freq_reciente_pos_{j+1}"]].iloc[-1:])[0][int(comb[j])] 
                            for j, modelo in enumerate(modelos))
        except IndexError:  # Manejar casos donde un número no está en las clases del modelo
            confianza = sum(modelo.predict_proba(df[["dia_semana", f"freq_reciente_pos_{j+1}"]].iloc[-1:])[0][min(int(comb[j]), len(modelo.classes_) - 1)] 
                            for j, modelo in enumerate(modelos))
        mensaje += f"{i}. {comb} (Confianza: {confianza:.2f})\n"
    print(mensaje)
    return combinaciones, mensaje

# Determinar el próximo día hábil
def determinar_proximo_dia():
    ahora = datetime.now(pytz.timezone("America/Puerto_Rico"))
    dia_semana = ahora.weekday()
    
    def proximo_dia_habil(fecha):
        nueva_fecha = fecha + timedelta(days=1)
        while nueva_fecha.weekday() == 6:  # Saltar domingos
            nueva_fecha += timedelta(days=1)
        return nueva_fecha

    if dia_semana == 6 or (dia_semana == 5 and ahora.hour >= 21):  # Domingo o sábado después de 9 PM
        return proximo_dia_habil(ahora).strftime("%m/%d/%y")
    return ahora.strftime("%m/%d/%y")

# Función principal
async def main():
    print("Iniciando bot Pega 3 - Fecha actual:", datetime.now(pytz.timezone("America/Puerto_Rico")).strftime("%Y-%m-%d %H:%M:%S"))
    logging.info("Bot iniciado.")

    sorteos_pega3 = buscar_historial_lottostrategies("Pega 3")
    sorteos_pega2 = buscar_historial_lottostrategies("Pega 2")
    sorteos = sorteos_pega3 + sorteos_pega2
    if len(sorteos) < 20:
        print("No se recolectaron suficientes sorteos.")
        return

    sorteos = guardar_datos_csv(sorteos)
    fecha_sorteo = determinar_proximo_dia()
    mensaje_inicial = f"⏰ Hora actual (AST): {datetime.now(pytz.timezone('America/Puerto_Rico')).strftime('%H:%M')}\n"
    mensaje_inicial += f"Predicciones para el {fecha_sorteo} (Día y Noche):\n"
    print(mensaje_inicial)

    estrategias = ["segura", "balanceada", "arriesgada"]
    mensajes_telegram = [mensaje_inicial]
    for juego in ["Pega 3", "Pega 2"]:
        for estrategia in estrategias:
            combinaciones, mensaje = analizar_pega_avanzado(sorteos, juego, estrategia=estrategia)
            if combinaciones:
                mensajes_telegram.append(mensaje)

    # Enviar mensajes a Telegram
    for msg in mensajes_telegram:
        await enviar_telegram(msg)

if __name__ == "__main__":
    asyncio.run(main())
