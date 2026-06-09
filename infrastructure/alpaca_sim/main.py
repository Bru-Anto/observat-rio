
'''
Esse é um simulador, se passa por uma câmer, um domo e uma estação metereológica.
Ele serve para fazer testes do restante do software sem ter acesso ao hardware.
Esse simulador foi baseado nos padrões de comunição da ASCOM Alpaca.
'''
''' Bibliotecas '''

import asyncio # Tarefas assíncronas
import logging # Registrar mensagens 
import random # Simular mudanças climáticas
from fastapi import FastAPI, BackgroundTasks, Form # Recursos para o uso do API

''' Configuração de Logs '''

logging.basicConfig(level=logging.INFO)  # Difine que o nível mínimo do log vai ser as infos do hardware
logger = logging.getLogger("ALPACA_SIM") # logger chamado ALPACA_SIM
app = FastAPI(title="ASCOM Alpaca Simulator") # Começa a Aplicação 

''' Estados do Simulador '''

class HardwareState:
    # Domo
    dome_shutter_status = 1  # Estado inicial do domo -> 0:Open, 1:Closed, 2:Opening, 3:Closing 
    dome_is_slewing = False # Indica se o domo está se movendo -> Começa parado
    dome_azimuth = 180.0  # Posição inicial ->inicia apontado para o Sul
    
    # Camera
    camera_state = 0 # Estado inicial da câmera -> 0:Open, 1:Closed, 2:Opening, 3:Closing 
    ccd_temperature = 25.0 # Temperatura inicial do CCD
    target_temperature = -10.0 # Temperatura alvo 
    cooler_on = True # Estado inicial do cooler -> Começa ligado
    cooler_power = 0.0 # Potência inicial do cooler
    heatsink_temperature = 26.0 # Temperatura inicial do dissipador 

    # Estação da estação metereológica
    wind_speed = 5.0 # Vento incial 
    humidity = 45.0 # Humidade inicial
    rain_rate = 0.0 # Taxa de Chuva inicial
    sky_temperature = -20.0 # Temperatura inical do céu
    cloud_cover = 0.1 # Cobertura de nuvens inicial

state = HardwareState() # Guarda do estado inicial do sistema

''' Respostas '''
def create_response(value, error_num=0, error_msg=""): # Função que padroniza as respostas baseado no protocolo de comunicação da Alpaca
    return {
        "Value": value, # Valor ou Resposta
        "ClientTransactionID": 0, # ID do cliente -> nesse simulador foi fixado em 0
        "ServerTransactionID": 1, # ID do servidor -> nesse simulador foiu fixado em 1
        "ErrorNumber": error_num, # Número do erro, 0: Sem erro.
        "ErrorMessage": error_msg # Mensagem do erro
    }

''' Simulações '''

# Movimento do Domo
async def simulate_dome_movement(target_state: int): # Função para simular o abrir e fechar do domo
    state.dome_is_slewing = True # Define que o domo está em movimento 
    state.dome_shutter_status = 2 if target_state == 0 else 3 # Se o alvo for zero está abrindo senão ele está fechando
    await asyncio.sleep(5) # Espera 5 segundos, usado para ficar mais próximo de um tempo real de um simulador 
    state.dome_shutter_status = target_state # Estado final desejado
    state.dome_is_slewing = False # Define que o domo está parado
    logger.info(f"Shutter do Domo: {target_state}") # Registra o log dessa interação

# Rotaçao do Domo
async def simulate_dome_rotation(target_azimuth: float): #Função para simular a rotação do domo até o azimute
    state.dome_is_slewing = True # Define que o domo está em movimento 
    logger.info(f"Rotacionando domo para {target_azimuth}°") # Registra no log o alvo da rotação
    while abs(state.dome_azimuth - target_azimuth) > 1.0: # Até nào ficar no zero novamente ele continua girando
        if state.dome_azimuth < target_azimuth: # Verifica se precisa aumentar o azimute 
            state.dome_azimuth += 5.0 # Se precisar aumentar, aumenta 5 graus 
        else:
            state.dome_azimuth -= 5.0 # Se não precisar, reduz 5 graus
        await asyncio.sleep(0.5) # Espera 5 segundos antes de começar novamente
    
    state.dome_azimuth = target_azimuth # Vai para o azimute definido no início 
    state.dome_is_slewing = False # Define que o domo está parado 
    logger.info("Rotação concluída.") #Registra o log que a interação terminou 

# Exposição da Câmera  
async def simulate_camera_exposure(duration: float): # Função para simular a exposição da câmera
    state.camera_state = 2 # Muda o estado da câmera para expondo
    await asyncio.sleep(duration) # Espera a exposição terminar
    state.camera_state = 0 # Muda a câmera para ociosa
    logger.info("Exposição finalizada") # Registra no log que a câmera terminou de expor

# Temperatura da Câmera e do Cooler
async def update_thermal_stats(): # Função  que atualiza as temperaturas
    while True: # L oop que continua durante toda a simulação
        jitter = random.uniform(-0.1, 0.1) # Variação pequena aleatória para não manter o valor fixo
        if state.cooler_on: # Verifica se o cooler está ligado
            if state.ccd_temperature > state.target_temperature: # Verifica se a temperatura está acima da temperatura alvo
                state.ccd_temperature -= 0.5 # Reduz a temoperatura em 0.5 no ciclo
                state.cooler_power = min(100.0, state.cooler_power + 2.0) # Aumenta a potência, mas não deixa passar de 100% 
            else:
                state.ccd_temperature = state.target_temperature + jitter # Se já está na temperatura alvo mantém com uma pequena variação 
                state.cooler_power = max(40.0, state.cooler_power + jitter) # Mantém a potência em 40% com pequenas variações 
            state.heatsink_temperature = 28.0 + (state.cooler_power / 10.0) # Verifica a temperatura do dissipador baseado na temperatura e potência do cooler
        else:
            if state.ccd_temperature < 25.0: # Se o cooler está desligado e abaixo de 25 graus
                state.ccd_temperature += 0.2 # Vai aquecendo aos poucos
            state.cooler_power = 0.0 # Mantém a potência em zero
            state.heatsink_temperature = 26.0 # Difine a temperartura do dissipador em 26 graus 
        await asyncio.sleep(2) # Espera 2 segundos 

# Estação metereológica
async def update_weather_stats(): # Função para atualizar as variáveis da estação
    while True:
        # Vento
        if random.random() > 0.9: # Define um valor aleatório entre 0 e 1 
            state.wind_speed = random.uniform(20.0, 45.0) # Se esse número for maior que 0.9, temos uma rejada, que vai de 20 a 45 km/h
        else:
            state.wind_speed = max(0.0, state.wind_speed + random.uniform(-2.0, 2.0)) # Se não for maior que 0.9, o vento irá variar gradativamente 
        
        # Umidade e Nuvens
        state.humidity = max(10.0, min(95.0, state.humidity + random.uniform(-1.0, 1.0))) # Muda o valor um pouco para cima ou para baixo e define que esse valor fica entre 0 e 95
        state.cloud_cover = max(0.0, min(1.0, state.cloud_cover + random.uniform(-0.05, 0.05))) # Muda o valor um pouco para cima ou para baixo e define que esse valor fica entre 0 e 1 
        
        # Chuva
        state.rain_rate = random.uniform(0.0, 10.0) if state.humidity > 85.0 else 0.0 # Define chuva se a umidade está maior que 85
        
        await asyncio.sleep(5) # Espera 5 segundos

''' Tarefas Automáticas '''

@app.on_event("startup") # Função para iniciar quando o API iniciar
async def startup_event(): 
    asyncio.create_task(update_thermal_stats()) # Atualiza a temperatura da câmera
    asyncio.create_task(update_weather_stats()) # Atualiza o clima

''' Gerenciamento Alpaca '''

@app.get("/management/apiversions") # Rota para /management/apiversions
async def get_api_versions(): # Função para quando essa rota for aberta
    return [1] # Retornar que suporta a versão 1 do Alpaca

@app.get("/management/v1/configureddevices") # Rota que lista os dispositivos
async def get_devices(): 
    return create_response([
        {"DeviceName": "Simulated Camera", "DeviceType": "Camera", "DeviceNumber": 0, "UniqueID": "SIM-CAM-01"},
        {"DeviceName": "Simulated Dome", "DeviceType": "Dome", "DeviceNumber": 0, "UniqueID": "SIM-DOME-01"},
        {"DeviceName": "Simulated Weather Station", "DeviceType": "ObservingConditions", "DeviceNumber": 0, "UniqueID": "SIM-METEO-01"}
    ])

# API do Domo
@app.get("/api/v1/dome/0/connected")
async def dome_connected(): return create_response(True) # Verifica se está conectado

@app.get("/api/v1/dome/0/shutterstatus")
async def get_shutter_status(): return create_response(state.dome_shutter_status) # Verifica a abertura -> 0:Open, 1:Closed, 2:Opening, 3:Closing

@app.get("/api/v1/dome/0/azimuth")
async def get_azimuth(): return create_response(round(state.dome_azimuth, 1)) # Verifica o azimute atual
@app.get("/api/v1/dome/0/slewing")
async def get_dome_slewing(): return create_response(state.dome_is_slewing) # Verifica se está se movimentando

@app.put("/api/v1/dome/0/openshutter") # Cria uma rota para abrir o domo
async def open_shutter(background_tasks: BackgroundTasks): # Agenda a função para o alvo 0 
    background_tasks.add_task(simulate_dome_movement, 0) 
    return create_response(None)

@app.put("/api/v1/dome/0/closeshutter") # Cria uma rota para fechar o domo
async def close_shutter(background_tasks: BackgroundTasks):
    background_tasks.add_task(simulate_dome_movement, 1) # Agenda a função para o alvo 1 
    return create_response(None)

@app.put("/api/v1/dome/0/slewtoazimuth") # Cria uma rota para girar o domo até um azimute específico
async def slew_to_azimuth(background_tasks: BackgroundTasks, Azimuth: float = Form(...)):
    background_tasks.add_task(simulate_dome_rotation, Azimuth) # Agenda a rotação até tal azimute 
    return create_response(None)

# API da Câmera
@app.get("/api/v1/camera/0/connected") # Verifica se está conectado
async def camera_connected(): return create_response(True) 

@app.get("/api/v1/camera/0/camerastate")
async def get_camera_state(): return create_response(state.camera_state) # Verifica o estado -> 0:Ociosa, 2: Expondo

@app.get("/api/v1/camera/0/ccdtemperature")
async def get_ccd_temp(): return create_response(round(state.ccd_temperature, 2)) # Verifica a temperatura do CCD

@app.get("/api/v1/camera/0/coolerpower")
async def get_cooler_power(): return create_response(round(state.cooler_power, 1)) # Verfica a potência do Cooler

@app.get("/api/v1/camera/0/cooleron")
async def get_cooler_on(): return create_response(state.cooler_on) # Verifica se o cooler está ligado

@app.put("/api/v1/camera/0/startexposure") # Cria uma rota para começar a exposição da câmera
async def start_exposure(Duration: float = Form(...), Light: bool = Form(...)): # Função que recebe a duração e se é exposição com luz ou não
    if state.camera_state != 0: return create_response(None, 1025, "Camera Busy") # Retorna caso a câmera já esteja expondo
    bt = BackgroundTasks()
    bt.add_task(simulate_camera_exposure, Duration)
    return create_response(None)

# API da Estação Metereológica
@app.get("/api/v1/observingconditions/0/connected") # Verifica se está conectado
async def weather_connected(): return create_response(True)

@app.get("/api/v1/observingconditions/0/windspeed") # Verifica a velocidade do vento
async def get_wind_speed(): return create_response(round(state.wind_speed, 1))

@app.get("/api/v1/observingconditions/0/humidity") # Verifica a umidade
async def get_humidity(): return create_response(round(state.humidity, 1))

@app.get("/api/v1/observingconditions/0/rainrate") # Verifica a taxa de chuva
async def get_rain_rate(): return create_response(state.rain_rate)

@app.get("/api/v1/observingconditions/0/cloudcover") # Verifica a cobertura de nuvens
async def get_cloud_cover(): return create_response(round(state.cloud_cover, 2))

@app.get("/api/v1/observingconditions/0/skytemperature") # Verifica a temperatura do céu
async def get_sky_temp(): return create_response(state.sky_temperature)
