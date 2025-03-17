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
from deap import base, creator, tools
import telegram
import asyncio

# Configurar logging
logging.basicConfig(filename="pega_bot_avanzado.log", level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# Configuración de Telegram (reemplaza con tus valores)
TELEGRAM_TOKEN = "7458538344:AAG0dQvkgEA99oxY5OMTocN_UtS948Z5lnU"  # Obtén esto de BotFather en Telegram
TELEGRAM_CHAT_ID = "-1002594359155"    # Obtén esto enviando un mensaje al bot y revisando la API

# Función para enviar mensaje a Telegram
async def enviar_telegram(mensaje):
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensaje)
        logging.info("Mensaje enviado a Telegram exitosamente.")
    except Exception as e:
        logging.error(f"Error al enviar mensaje a Telegram: {e}")
        print(f"Error al enviar mensaje a Telegram: {e}")

# Función para recolectar historial de LottoStrategies
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
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            filas = soup.find_all("tr")[1:]
            for fila in filas:
                celdas = fila.find_all("td")
                if len(celdas) >= 2:
                    fecha_raw = celdas[0].text.strip()
                    numeros = celdas[1].text.strip().replace("-", "")[:3 if juego == "Pega 3" else 2]
                    fecha_parts = fecha_raw.split()
                    if len(fecha_parts) >= 2:
                        fecha = fecha_parts[1]  # Formato MM/DD/YY
                        if validar_datos(fecha, numeros):
                            sorteos.append({"fecha": fecha, "tipo": tipo, "numeros": numeros, "juego": juego})
        except requests.RequestException as e:
            logging.error(f"Error al acceder a LottoStrategies ({juego} {tipo}): {e}")
            print(f"Error al acceder a LottoStrategies ({juego} {tipo}): {e}")
    logging.info(f"Recolectados {len(sorteos)} sorteos de {juego} desde LottoStrategies.")
    print(f"Recolectados {len(sorteos)} sorteos de {juego} desde LottoStrategies.")
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
    logging.info(f"Datos guardados en {archivo} con {len(sorteos_unicos)} sorteos únicos.")
    print(f"Datos guardados en {archivo} con {len(sorteos_unicos)} sorteos únicos.")
    return sorteos_unicos

# Guardar predicciones en CSV
def guardar_predicciones_csv(predicciones, tipo_sorteo, juego, archivo="pega_predicciones.csv", ultimos_sorteos=None):
    fecha_actual = datetime.now(pytz.timezone("America/Puerto_Rico")).strftime("%Y-%m-%d %H:%M:%S")
    registro = {
        "fecha_prediccion": fecha_actual,
        "tipo": tipo_sorteo,
        "juego": juego,
        "opcion_1": predicciones[0], "opcion_2": predicciones[1], "opcion_3": predicciones[2],
        "opcion_4": predicciones[3], "opcion_5": predicciones[4], "opcion_6": predicciones[5],
        "opcion_7": predicciones[6], "opcion_8": predicciones[7], "opcion_9": predicciones[8],
        "opcion_10": predicciones[9],
        "aciertos": "N/A" if not ultimos_sorteos else str(sum(1 for p in predicciones if p in ultimos_sorteos[:1]))
    }
    fieldnames = ["fecha_prediccion", "tipo", "juego"] + [f"opcion_{i}" for i in range(1, 11)] + ["aciertos"]
    try:
        with open(archivo, "r", newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            existing = list(reader) if "tipo" in reader.fieldnames and "juego" in reader.fieldnames else []
    except (FileNotFoundError, TypeError):
        existing = []
    if not any(row["tipo"] == tipo_sorteo and row["juego"] == juego and row["fecha_prediccion"][:10] == fecha_actual[:10] for row in existing):
        mode = "a" if existing else "w"
        with open(archivo, mode, newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if mode == "w" or csvfile.tell() == 0:
                writer.writeheader()
            writer.writerow(registro)
            logging.info(f"10 Predicciones guardadas para {juego} {tipo_sorteo} en {archivo}.")
            print(f"10 Predicciones guardadas para {juego} {tipo_sorteo} en {archivo}.")
    else:
        print(f"Predicciones para {juego} {tipo_sorteo} ya existen para hoy. No se guardaron duplicados.")
    return registro

# Preparar datos para machine learning con más características
def preparar_datos_ml(sorteos, juego, tipo_sorteo):
    df = pd.DataFrame(sorteos)
    df = df[(df["juego"] == juego) & (df["tipo"] == tipo_sorteo)]
    df["fecha"] = pd.to_datetime(df["fecha"], format="%m/%d/%y")
    df = df.sort_values("fecha")
    
    df["dia_semana"] = df["fecha"].dt.dayofweek
    df["mes"] = df["fecha"].dt.month
    df["dias_desde_inicio"] = (df["fecha"] - df["fecha"].min()).dt.days
    num_pos = 3 if juego == "Pega 3" else 2
    for i in range(num_pos):
        df[f"pos_{i+1}"] = df["numeros"].str[i].astype(int)
        df[f"ultima_aparicion_pos_{i+1}"] = df.groupby(f"pos_{i+1}")["dias_desde_inicio"].shift().fillna(0)
        df[f"freq_reciente_pos_{i+1}"] = df[f"pos_{i+1}"].rolling(window=15, min_periods=1).apply(lambda x: Counter(x).most_common(1)[0][1], raw=True)
        df[f"media_ultimos_5_pos_{i+1}"] = df[f"pos_{i+1}"].rolling(window=5, min_periods=1).mean()
    return df

# Entrenar modelo de Random Forest por posición
def entrenar_modelo(df, posicion):
    X = df[["dia_semana", "mes", "dias_desde_inicio", f"ultima_aparicion_pos_{posicion}", 
            f"freq_reciente_pos_{posicion}", f"media_ultimos_5_pos_{posicion}"]]
    y = df[f"pos_{posicion}"]
    modelo = RandomForestClassifier(n_estimators=200, random_state=42, max_depth=12, min_samples_split=5)
    modelo.fit(X, y)
    return modelo

# Configurar algoritmo genético
creator.create("FitnessMax", base.Fitness, weights=(1.0,))
creator.create("Individual", list, fitness=creator.FitnessMax)

toolbox = base.Toolbox()

def generar_individuo(top_posiciones):
    return creator.Individual([random.choice(pos[:5]) for pos in top_posiciones])

def evaluar_individuo(individuo, ultimos_sorteos, modelos, df_ultimo):
    comb = "".join(map(str, individuo))
    if comb in ultimos_sorteos:
        return -1,  # Penalizar repeticiones
    score = 0
    X_nuevo = df_ultimo.iloc[-1:]
    for i, modelo in enumerate(modelos):
        cols = ["dia_semana", "mes", "dias_desde_inicio", f"ultima_aparicion_pos_{i+1}", 
                f"freq_reciente_pos_{i+1}", f"media_ultimos_5_pos_{i+1}"]
        X_pos = X_nuevo[cols]
        pred_proba = modelo.predict_proba(X_pos)[0]
        if len(pred_proba) < 10:
            pred_proba = list(pred_proba) + [0] * (10 - len(pred_proba))
        score += pred_proba[individuo[i]] * (1 + i * 0.1)  # Dar más peso a posiciones posteriores
    return score,

toolbox.register("mate", tools.cxTwoPoint)
toolbox.register("mutate", tools.mutUniformInt, low=0, up=9, indpb=0.4)
toolbox.register("select", tools.selTournament, tournsize=5)

# Analizar sorteos con ML y algoritmos genéticos
def analizar_pega_avanzado(sorteos, tipo_sorteo="Día", juego="Pega 3", num_combinaciones=10, estrategia="balanceada", min_sorteos=15):
    sorteos_filtrados = [s for s in sorteos if s["tipo"] == tipo_sorteo and s["juego"] == juego]
    if len(sorteos_filtrados) < min_sorteos:
        print(f"No hay suficientes sorteos de {juego} {tipo_sorteo} (mínimo {min_sorteos}).")
        return None

    # Preparar datos y entrenar modelos
    df = preparar_datos_ml(sorteos_filtrados, juego, tipo_sorteo)
    modelos = [entrenar_modelo(df, i+1) for i in range(3 if juego == "Pega 3" else 2)]
    
    # Obtener últimos sorteos
    ast_tz = pytz.timezone("America/Puerto_Rico")
    fechas = [ast_tz.localize(datetime.strptime(s["fecha"], "%m/%d/%y")) for s in sorteos_filtrados]
    sorteos_con_fechas = list(zip(sorteos_filtrados, fechas))
    sorteos_con_fechas.sort(key=lambda x: x[1], reverse=True)
    ultimos_sorteos = [s["numeros"] for s, _ in sorteos_con_fechas[:5]]

    # Frecuencias ponderadas para inicializar
    posiciones = [[] for _ in range(3 if juego == "Pega 3" else 2)]
    hoy = datetime.now(pytz.timezone("America/Puerto_Rico"))
    pesos = []
    for i, (sorteo, fecha) in enumerate(sorteos_con_fechas):
        dias_diferencia = max((hoy - fecha).days, 1)
        peso = 2.0 if i < 2 else 1 / (dias_diferencia ** 0.7)  # Mayor peso a sorteos recientes
        for j in range(len(sorteo["numeros"])):
            posiciones[j].append(int(sorteo["numeros"][j]))
        pesos.append(peso)
    
    freq_posiciones = [Counter() for _ in range(len(posiciones))]
    for i, pos in enumerate(posiciones):
        for j, num in enumerate(pos):
            freq_posiciones[i][num] += pesos[j]
    top_posiciones = [[x[0] for x in freq.most_common(5)] for freq in freq_posiciones]

    # Registrar funciones del algoritmo genético
    toolbox.register("individual", generar_individuo, top_posiciones=top_posiciones)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", evaluar_individuo, ultimos_sorteos=ultimos_sorteos, modelos=modelos, df_ultimo=df)
    
    # Ejecutar algoritmo genético
    population = toolbox.population(n=300)  # Más individuos
    for gen in range(60):  # Más generaciones
        offspring = toolbox.select(population, len(population))
        offspring = list(map(toolbox.clone, offspring))
        for child1, child2 in zip(offspring[::2], offspring[1::2]):
            if random.random() < 0.8:
                toolbox.mate(child1, child2)
                del child1.fitness.values
                del child2.fitness.values
        for mutant in offspring:
            if random.random() < 0.4:
                toolbox.mutate(mutant)
                del mutant.fitness.values
        for ind in offspring:
            if not ind.fitness.valid:
                ind.fitness.values = toolbox.evaluate(ind)
        population = offspring
    
    # Seleccionar combinaciones únicas
    combinaciones_set = set()
    ranked_population = sorted(population, key=lambda x: x.fitness.values[0], reverse=True)
    for ind in ranked_population:
        comb = "".join(map(str, ind))
        if comb not in combinaciones_set and comb not in ultimos_sorteos:
            combinaciones_set.add(comb)
        if len(combinaciones_set) == num_combinaciones:
            break
    combinaciones = list(combinaciones_set)
    
    # Completar si faltan combinaciones
    while len(combinaciones) < num_combinaciones:
        new_comb = "".join([str(random.choice(top_posiciones[i])) for i in range(len(top_posiciones))])
        if new_comb not in combinaciones and new_comb not in ultimos_sorteos:
            combinaciones.append(new_comb)

    # Ajustar según estrategia
    if estrategia == "arriesgada":
        combinaciones = set()
        while len(combinaciones) < num_combinaciones:
            new_comb = ''.join([str(random.randint(0, 9)) for _ in range(3 if juego == "Pega 3" else 2)])
            if new_comb not in ultimos_sorteos and new_comb not in combinaciones:
                combinaciones.add(new_comb)
        combinaciones = list(combinaciones)
    elif estrategia == "segura":
        pass  # Usamos las más probables

    # Mostrar información detallada
    mensaje = f"\n=== Análisis Avanzado {juego} {tipo_sorteo} - {num_combinaciones} Combinaciones ===\n"
    mensaje += f"Sorteos analizados: {len(sorteos_filtrados)}\n"
    mensaje += f"Últimos sorteos: {ultimos_sorteos}\n"
    mensaje += f"Estrategia: {estrategia}\n"
    mensaje += "Frecuencias ponderadas por posición: " + str([dict(freq) for freq in freq_posiciones]) + "\n"
    for i, comb in enumerate(combinaciones, 1):
        confianza = sum(modelo.predict_proba(df.iloc[-1:][["dia_semana", "mes", "dias_desde_inicio", 
                                                           f"ultima_aparicion_pos_{j+1}", 
                                                           f"freq_reciente_pos_{j+1}", 
                                                           f"media_ultimos_5_pos_{j+1}"]])[0][int(comb[j])] 
                        for j, modelo in enumerate(modelos))
        mensaje += f"  Opción {i}: {comb} (Confianza: {confianza:.3f})\n"
    print(mensaje)
    
    return combinaciones, mensaje

# Determinar el próximo día hábil con sorteos Día y Noche
def determinar_siguiente_sorteo():
    ahora = datetime.now(pytz.timezone("America/Puerto_Rico"))
    hora = ahora.hour
    minuto = ahora.minute
    dia_semana = ahora.weekday()  # 0 = lunes, 6 = domingo
    
    hora_sorteo_dia = 14  # 2 PM
    hora_sorteo_noche = 21  # 9 PM
    
    def proximo_dia_habil(fecha):
        nueva_fecha = fecha + timedelta(days=1)
        while nueva_fecha.weekday() == 6:  # Saltar domingos
            nueva_fecha += timedelta(days=1)
        return nueva_fecha

    if dia_semana == 6:  # Domingo
        proximo_dia = proximo_dia_habil(ahora)
        fecha_sorteo = proximo_dia.strftime("%m/%d/%y")
        return [("Día", fecha_sorteo), ("Noche", fecha_sorteo)]
    else:  # Lunes a sábado
        if hora < hora_sorteo_dia or (hora == hora_sorteo_dia and minuto < 0):
            fecha_sorteo = ahora.strftime("%m/%d/%y")
            return [("Día", fecha_sorteo), ("Noche", fecha_sorteo)]
        elif hora < hora_sorteo_noche or (hora == hora_sorteo_noche and minuto < 0):
            fecha_sorteo = ahora.strftime("%m/%d/%y")
            return [("Noche", fecha_sorteo)]
        else:
            proximo_dia = proximo_dia_habil(ahora)
            fecha_sorteo = proximo_dia.strftime("%m/%d/%y")
            return [("Día", fecha_sorteo), ("Noche", fecha_sorteo)]

# Iniciar el bot avanzado
async def main():
    print("Iniciando bot avanzado Pega - Fecha actual:", datetime.now(pytz.timezone("America/Puerto_Rico")).strftime("%Y-%m-%d %H:%M:%S"))
    logging.info("Bot avanzado iniciado.")

    print("Recolectando datos históricos desde LottoStrategies...")
    sorteos_pega3 = buscar_historial_lottostrategies("Pega 3")
    sorteos_pega2 = buscar_historial_lottostrategies("Pega 2")
    sorteos = sorteos_pega3 + sorteos_pega2

    if len(sorteos) < 30:
        print("No se recolectaron suficientes sorteos desde LottoStrategies. Abortando...")
        logging.error("No se recolectaron suficientes sorteos.")
        return

    sorteos = guardar_datos_csv(sorteos)

    sorteos_futuros = determinar_siguiente_sorteo()
    mensaje_inicial = f"\nHora actual (AST): {datetime.now(pytz.timezone('America/Puerto_Rico')).strftime('%H:%M')}\n"
    mensaje_inicial += f"Siguientes sorteos:\n"
    for tipo, fecha in sorteos_futuros:
        mensaje_inicial += f"  {tipo} (Fecha: {fecha})\n"
    mensaje_inicial += "\nPredicciones para los siguientes sorteos:\n"
    print(mensaje_inicial)

    estrategias = ["segura", "balanceada", "arriesgada"]
    mensajes_telegram = [mensaje_inicial]
    for juego in ["Pega 3", "Pega 2"]:
        for tipo_sorteo, fecha_sorteo in sorteos_futuros:
            for estrategia in estrategias:
                combinaciones, mensaje = analizar_pega_avanzado(sorteos, tipo_sorteo, juego, num_combinaciones=10, estrategia=estrategia)
                if combinaciones:
                    registro = guardar_predicciones_csv(combinaciones, tipo_sorteo, juego, archivo=f"pega_predicciones_{estrategia}.csv", ultimos_sorteos=[s["numeros"] for s in sorteos if s["juego"] == juego and s["tipo"] == tipo_sorteo][-1:])
                    mensajes_telegram.append(mensaje)

    # Enviar predicciones a Telegram
    for msg in mensajes_telegram:
        await enviar_telegram(msg)

if __name__ == "__main__":
    asyncio.run(main())

# Ejemplo de cron (colocar en crontab -e en Linux/Mac):
# Ejecuta el script todos los días a las 00:30 AST (ajusta según tu zona horaria)
# 30 0 * * 1-6 python3 /ruta/a/pega3.py
