''' Código para o sequenciador
Ele tem 5 funções: manter o estado operacional no redis, recebe a telemetria e atualiza o estado, usa o fallback para caso de falha no MQTT, avalia a segurança climática e fecha o domo caso esteja inseguro, expõe a API.

'''

''' Bibliotecas '''

import asyncio # Tarefas assíncronas
import os # Variáveis de ambiente
import json # Lê e transforma JSON
import logging # Logs de serviço
import requests # Faz chamadas HTTP para o alpaca
import redis # Conecta no redis
from datetime import datetime, timezone # Importa data/hora e timezone
from threading import RLock # Protege o estado contra acessos simulatâneos 
from typing import Optional, Tuple, Dict, Any # Importa tipos usando as anotações
import paho.mqtt.client as mqtt # Importa cliente MQTT
from fastapi import FastAPI, HTTPException # Importa o API e o HTTP
from telemetry import ( # Importa algumas funções do arquivo telemetry.py
    apply_telemetry_readings, # Leituras de estado
    extract_telemetry_readings, # Interpreta a mensagem JSON da telemetria
    to_bool, # Converte valores para booleano
    to_float, # Converte valor para número decimal 
    to_int, # Converte valor para inteiro 
)

''' Configurações '''

logging.basicConfig(level=logging.INFO) # Nível padrão de logs como INFO
logger = logging.getLogger("SEQUENCER") # Cria um logger chamado sequencer 

ALPACA_URL = os.getenv("ALPACA_URL", "http://alpaca_sim:80") # Lê o URL do simulador 
MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto") # Lê o broker MQTT 
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883")) # Lê a porrta MQTT

REDIS_HOST = os.getenv("REDIS_HOST", "redis") # Host do redis
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379")) # Porta do redis

MAX_WIND = float(os.getenv("MAX_WIND", "40.0")) # Define o máximo de vento
SAFE_WIND = float(os.getenv("SAFE_WIND", "30.0")) # Define o máximo de vento para ser seguro
RAIN_THRESHOLD = float(os.getenv("RAIN_THRESHOLD", "0.0")) # Define o limite de chuva antes de fechar o domo

# Abertura automática do Domo -> Se encontra desligada para garantir a segurança 
AUTO_OPEN_ENABLED = os.getenv("AUTO_OPEN_ENABLED", "false").lower() in ("1", "true", "yes", "y", "on") # Define se a abertura automática está ligada
AUTO_OPEN_STABLE_SECONDS = int(os.getenv("AUTO_OPEN_STABLE_SECONDS", "120")) # Tempo de tempo estável antes de abrir
AUTO_OPEN_COOLDOWN_SECONDS = int(os.getenv("AUTO_OPEN_COOLDOWN_SECONDS", "60")) # Tempo mínimo entre tentaivas de abertura

REDIS_KEY = "observatory:state" # Salvar o estado no redis

# Estados do Domo 
# 0: Open, 1: Closed, 2: Opening, 3: Closing
SHUTTER_OPEN = 0
SHUTTER_CLOSED = 1
SHUTTER_OPENING = 2
SHUTTER_CLOSING = 3

# Configurações do Redis 
redis_client = redis.Redis( # Cria o cliente Redis
    host=REDIS_HOST, # Host configurado
    port=REDIS_PORT, # Porta configurada
    decode_responses=True # Faz o redis mandar strings invés de bytes
)

STATE_LOCK = RLock() # Cria um lock para evitar alterações simulatâneas de estado

# Horário
def now_iso() -> str: # Função que dá a hora e a data atuais 
    return datetime.now(timezone.utc).isoformat() # Usa o UTC e formato ISO

''' Estado padrão '''

def default_state() -> Dict[str, Any]: # Função que cria o estado inicial do sistema 
    return { 
        # Valores iniciais de clima
        "wind_speed": 0.0, 
        "rain_rate": 0.0,
        "humidity": 0.0,
        "cloud_cover": 0.0,
        "sky_temperature": 0.0,

        # Valores iniciais da câmera
        "ccd_temperature": 25.0,
        "cooler_power": 0.0,
        "cooler_on": True,
        "camera_state": 0,

        # Valores iniciais do domo
        # O none indica que ainda não há dado reconhecido
        "dome_shutter_status": None,
        "dome_azimuth": None,
        "dome_slewing": None,

        "weather_lock": False, # Bloqueio climático
        "last_update": None, # Guarda a última atualização
        "last_mapped_update": None, # Guarda a última tentativa de telemetria reconhecida
        "last_weather_update": None, # Guarda a última telemetria metereológica reconhecida
        "source": None, # Indica a origem dos dados

        # Auditoria
        "last_action": None,
        "last_action_at": None, 

        "stable_since": None, # Desde quando o clima está estável
        "last_open_attempt_at": None, # Última tentativa de abir o domo
        "last_close_attempt_at": None, # Última tentativa de fechar o domo

        # Mapa com todas as telemetrias recebidas e normalizadas
        "telemetry": {},
    }

''' Estado '''

def load_state() -> Dict[str, Any]: # Função para carregar o estado do redis
    raw = redis_client.get(REDIS_KEY) # Busca a chave
    if raw: # Se existe alguma coisa salva
        try: # Tenta processar
            parsed = json.loads(raw) # Transforma de JSON para dicionário python
            if isinstance(parsed, dict): # Garante que o resultado é dicionário
                state = default_state() # Cria o estado padrão
                state.update(parsed) # Atualiza o padrão com o dados salvos
                state.setdefault("telemetry", {}) # Garante que telemetry existe
                return state # Retorna o estado
        except Exception: # Caso ocorra algum erro
            pass # Igmora o erro
    return default_state() # Retorna o estado padrão
 
def save_state(state: Dict[str, Any]) -> None: # Função para salvar o estado
    redis_client.set(REDIS_KEY, json.dumps(state)) # Converte o esatdo para JSON e salva no redis

def update_state(mutator): # Função para alterar o estado
    with STATE_LOCK: # Entra no lock
        state = load_state() # Carrega o estado atual 
        state = mutator(state) # Aplica a função mutator para modificar o estado
        save_state(state) # Salva o novo estado
        return state # Retorna o novo estado

''' Simulador '''

def alpaca_put0(path: str, data: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> requests.Response: # Função para enviar comandos PUT 
    url = f"{ALPACA_URL}{path}" # Define o caminho, os dados que vão ser enviados e quanto tempo de espera. Monta o URL completo 
    return requests.put(url, data=data or {}, timeout=timeout)  # Faz a chamada

def alpaca_get(path: str, timeout: float = 2.0) -> Dict[str, Any]: # Função para pegar comandos GET
    url = f"{ALPACA_URL}{path}" # Monta a URL completa 
    r = requests.get(url, timeout=timeout) # Faz o pedido
    r.raise_for_status() # Se o status for erro levanta exceção
    return r.json() # Retorna a resposta

def alpaca_get_value(path: str, timeout: float = 2.0) -> Any: # Função para pegar apenas o campo value
    return alpaca_get(path, timeout=timeout).get("Value", None) # Chama o GET, pega o value e retorna none se não existir 

def refresh_dome_status_from_alpaca(state: Dict[str, Any]) -> Dict[str, Any]: # Função para atualizar os dados do domo
    try: 
        state["dome_shutter_status"] = alpaca_get_value("/api/v1/dome/0/shutterstatus") # Verifica o estado do shutter 
        state["dome_azimuth"] = alpaca_get_value("/api/v1/dome/0/azimuth") # Verifica o azimute 
        state["dome_slewing"] = alpaca_get_value("/api/v1/dome/0/slewing") # Verifica se o domo está se movendo 
    except Exception as e: # Se tiver erro
        logger.warning(f"Não consegui atualizar status do domo via Alpaca: {e}") # Registra o log de erro
    return state # Retorna o estado do domo, mesmo que não esteja atualizado

def close_dome(state: Dict[str, Any], reason: str) -> Dict[str, Any]: # Função para fechar o domo -> recebe o estado atual e qual o motivo que vai fechar
    state = refresh_dome_status_from_alpaca(state) # Consult o estado atual antes de qualquer coisa
    ss = state.get("dome_shutter_status")# Salva o status do shutter na variável ss

    if ss in (SHUTTER_CLOSED, SHUTTER_CLOSING): # Se está fechado ou não 
        return state # Apenas retorna

    last = state.get("last_close_attempt_at") # Pega o horário da última tentativa de fechar o domo
    if last: # Se tiver alguma tentaiva anterior 
        try: # Tenta interpretar o que foi feito antes
            last_dt = datetime.fromisoformat(last) # Converte a string ISO para datatime 
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < 5: # Calcula quanto tempo se passou, se passou menos de 5 segundos retorna sem tentar novamente
                return state # Retorna o estado
        except Exception: # Se tiver erro
            pass # Ignora e segue 

    try: # Tenta enviar comando 
        alpaca_put("/api/v1/dome/0/closeshutter") # Faz o PUT para fechar o domo
        state["last_action"] = "close_dome ({})".format(reason) # Registra a última ação e o motivo
        state["last_action_at"] = now_iso() # Registra quando a ação aconteceu 
        state["last_close_attempt_at"] = now_iso() # Registra a última tentativa de fechar 
        logger.critical("FECHANDO DOMO | motivo=%s | shutterstatus=%s", reason, ss) # Log crítico que está sendo fechado o domo
    except Exception as e: # Se tiver erro
        logger.error(f"Erro ao fechar domo: {e}") # Registra o erro

    return state # Retorna o estado

def open_dome(state: Dict[str, Any], reason: str) -> Dict[str, Any]: # Função para abrir o domo
    state = refresh_dome_status_from_alpaca(state) # Atualiza dados do domo
    ss = state.get("dome_shutter_status") # Pega o status do shutter
    
    if ss in (SHUTTER_OPEN, SHUTTER_OPENING): # Se já está aberto ou abrindo 
        return state # Não faz nada

    last = state.get("last_open_attempt_at") # Pega a última tentativa de abertura
    if last: # Caso já tenha uma tentativa anterior 
        try: # Tenta converter os dados
            last_dt = datetime.fromisoformat(last) # Converte para datetime
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < AUTO_OPEN_COOLDOWN_SECONDS: # Se passou menos tempo que o definido no cooldown não tenta novamente
                return state # Retorna o estado
        except Exception: # Se tiver erro
            pass # Ignora e segue 

    try: # Tenta enviar comando
        alpaca_put("/api/v1/dome/0/openshutter") # Faz o PUT de abir o shutter 
        state["last_action"] = "open_dome ({})".format(reason) # Registra ação e motivo 
        state["last_action_at"] = now_iso() # Registra a hora e a ação 
        state["last_open_attempt_at"] = now_iso() # Registra a última tentativa de abertura
        logger.warning("ABRINDO DOMO | motivo=%s | shutterstatus=%s", reason, ss) # Registra o aviso no log
    except Exception as e: # Se tiver erro 
        logger.error(f"Erro ao abrir domo: {e}") # Registra o erro

    return state # Retorna o estado

''' Segurança '''

def is_unsafe(state: Dict[str, Any]) -> Tuple[bool, Optional[str]]: # Função que avalia se o clima está inseguro
    if float(state.get("rain_rate", 0.0)) > RAIN_THRESHOLD: # Pega o estado de chuva e compara com o RAIN_THRESHOLD
        return True, "rain" # Se está acima retorna como inseguro e com o motivo de chuva 
    if float(state.get("wind_speed", 0.0)) > MAX_WIND: # Pega o estado da velocidade do vento e compara com MAX_WIND
        return True, "wind" # Se o vento está acima do limite define como inseguro e retorna com o motivo de vento 
    return False, None # Se nada está acima retorna como seguro 

def is_stable(state: Dict[str, Any]) -> bool: # Define a função que verifica a estabilidade do clima 
    return (float(state.get("wind_speed", 0.0)) < SAFE_WIND) and (float(state.get("rain_rate", 0.0)) == 0.0) # Retorna como estável se o vento estiver abaixo do safe wind e se a chuva estiver 0

def evaluate_safety(state: Dict[str, Any]) -> Dict[str, Any]: # Define a função principal de segurança 
    unsafe, reason = is_unsafe(state) # Chama a is_unsafe e retorna se está inseguro ou seguro

    if unsafe: # Se o clima está inseguro 
        state["weather_lock"] = True # Ativa o bloqueio
        state["stable_since"] = None # Apaga o início da estabilidade 
        state = close_dome(state, reason=reason or "unsafe") # Manda o domo fechar 
        return state # Retorna o estado imediatamente 

    if state.get("weather_lock") and is_stable(state): # Se estava em bloqueio e agora o clima está estável
        if not state.get("stable_since"): # Se ainda não marcou o início da estabilidade
            state["stable_since"] = now_iso() # Grava o momento atual como início da estabilidade
        state["weather_lock"] = False # Libera do bloqueio
        logger.info("Clima normalizado (lock liberado)") # Registra no log que o clima está normal

    if AUTO_OPEN_ENABLED: # Se a abertura automática tiver ligada
        if (not state.get("weather_lock")) and state.get("stable_since") and is_stable(state): # Verifica se não está em bloqueio, se existe o periodo de estabilidade e se o clima ainda está estável
            try: 
                stable_dt = datetime.fromisoformat(state["stable_since"]) # Converte para datetime
                stable_for = (datetime.now(timezone.utc) - stable_dt).total_seconds() # Calcula a quanto tempo está estável
                if stable_for >= AUTO_OPEN_STABLE_SECONDS: # Se o tempo superou o mínimo programado 
                    state = open_dome(state, reason="stable_for_{}s".format(int(stable_for))) # Manda o domo abrir
            except Exception: # Se der erro
                pass # Ignora e continua

    return state # Retorna o estado

''' Conexão MQTT'''

def on_mqtt_connect(client, userdata, flags, rc): # Função que é chamada quando o cliente conecta ao broker
    if rc == 0: # Conexão bem sucedida
        logger.info("MQTT conectado") # Registra a conexão
        client.subscribe("observatory/telemetry/#") # Assina os subtópicos de telemetria
    else: # Se der erro
        logger.error("Falha MQTT rc=%s", rc) # Registra que a conexão deu erro

def on_mqtt_message(client, userdata, msg): # Função chamada para as mensagens recebidas em MQTT
    try: 
        payload = json.loads(msg.payload.decode(errors="replace")) # Decodifica o payload e converte para JSON
        readings = extract_telemetry_readings(payload, topic=msg.topic) # Identifica qual medição chegou e qual campo ele deve atualizar

        if not readings: # Se não foi extraidos dados
            logger.warning("Telemetria MQTT sem valor reconhecivel | topic=%s payload=%s", msg.topic, payload) # Registra que nada foi reconhecido  
            return 

        updated_at = now_iso() # Marca o horário da atualização 

        def mutate(state: Dict[str, Any]) -> Dict[str, Any]: # Função que altera o estado
            state, mapped = apply_telemetry_readings( # Aplica as leituras de estado
                state, # Passa o estado atual 
                readings, # Passa as leituras extraídas
                topic=msg.topic, # Tópico MQTT
                updated_at=updated_at, # Informa o horário
                source="mqtt", # Origem como MQTT
            ) 
            if mapped == 0: # Se nenhuma leitura foi mapeada para um campo conhecido 
                logger.info("Telemetria generica registrada | topic=%s readings=%s", msg.topic, len(readings)) # Registra como telemetria genérica
            return evaluate_safety(state) # Atualiza o estado e verifica a segurança

        update_state(mutate) # Aplica alterações dentro do lock e salva no redis

    except Exception as e: # Se tiver erro
        logger.error("Erro MQTT: %s | topic=%s payload=%s", e, msg.topic, msg.payload.decode(errors="replace")) # Registra o erro, o tópico e o payload bruto

def create_mqtt_client(): # Função para criar o cliente MQTT
    callback_api_version = getattr(mqtt, "CallbackAPIVersion", None) # Tenta obter o CallbackAPIVersion
    if callback_api_version is not None: # Se existe alguma nova versão
        return mqtt.Client(client_id="sequencer", callback_api_version=callback_api_version.VERSION1) # Cria o cliente MQTT com client_id e força callbacks no estilo da versão 1
    return mqtt.Client(client_id="sequencer") # Se a versão for mais antiga cria o cliente se esse argumento extra 

mqtt_client = None # Variável que guarda o cliente MQTT

def start_mqtt(): # Função que inicia o cliente MQTT
    global mqtt_client # Função altera a variável
    if mqtt_client is not None: # Se o cliente ja existe 
        return # Sai e não faz nada

    mqtt_client = create_mqtt_client() # Cria o cliente
    mqtt_client.on_connect = on_mqtt_connect # Registra a função ao conectar 
    mqtt_client.on_message = on_mqtt_message # Registra a função ao receber mensagem 
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60) # Conecta ao broker configurado, keepalive de 60 segundos
    mqtt_client.loop_start() # Inicia o loop -> Permite que o API continue atendendo o HTTP equanto o MQTT recebe mensagens

def stop_mqtt(): # Define a função para parar o cliente MQTT
    global mqtt_client # Função altera a variável
    if mqtt_client is None: # Se não tem cliente ativo
        return # Sai sem fazer nada
    mqtt_client.loop_stop() # Para o loop
    mqtt_client.disconnect() # Desconecta o broker 
    mqtt_client = None # Limpa a variável 

''' Fallback do Simulador -> Continua funcionando se o fluxo MQTT parar''' 
async def alpaca_fallback(): # Tarefa assincrona que roda em loop
    while True: # Loop infinito 
        with STATE_LOCK: # Entra em lock de estado
            state = load_state() # Carrega o esatdo atual do redis

        if state.get("last_weather_update"): # Se existe timestamp da última telemetria de clima
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(state["last_weather_update"])).total_seconds() # Calcula a quanto tempo a telemetria chegou
                if age < 10: # Se a telemetria tem menos de 10 segundos 
                    await asyncio.sleep(2) # Espera 2 segundos 
                    continue # Recomeça o loop -> Se o MQTT está normal não vai consultar o simulador
            except Exception: # Se tiver erro
                pass # Ignora e continua

        logger.warning("FALLBACK ALPACA") # Registra que o fallback vai consultar o simulador

        try: # Começa tentativa de coleta
            values = { 
                # Coleta de Clima 
                "wind_speed": to_float(alpaca_get_value("/api/v1/observingconditions/0/windspeed")),
                "rain_rate": to_float(alpaca_get_value("/api/v1/observingconditions/0/rainrate")),
                "humidity": to_float(alpaca_get_value("/api/v1/observingconditions/0/humidity")),
                "cloud_cover": to_float(alpaca_get_value("/api/v1/observingconditions/0/cloudcover")),
                "sky_temperature": to_float(alpaca_get_value("/api/v1/observingconditions/0/skytemperature")),

                # =Coleta da câmera
                "ccd_temperature": to_float(alpaca_get_value("/api/v1/camera/0/ccdtemperature")),
                "cooler_power": to_float(alpaca_get_value("/api/v1/camera/0/coolerpower")),
                "cooler_on": to_bool(alpaca_get_value("/api/v1/camera/0/cooleron")),
                "camera_state": to_int(alpaca_get_value("/api/v1/camera/0/camerastate")),

                # Coleta do domo
                "dome_shutter_status": to_int(alpaca_get_value("/api/v1/dome/0/shutterstatus")),
                "dome_azimuth": to_float(alpaca_get_value("/api/v1/dome/0/azimuth")),
                "dome_slewing": to_bool(alpaca_get_value("/api/v1/dome/0/slewing")),
            }

            updated_at = now_iso() # Marca o horário de atualização

            def mutate(state: Dict[str, Any]) -> Dict[str, Any]: # Função para alterar o estado
                state.update(values) # Atualiza com os valores coletados diretamente do simulador
                state["last_update"] = updated_at # Última atualização geral
                state["last_mapped_update"] = updated_at # Última atualização mapeada
                state["last_weather_update"] = updated_at # Última atualização matereológica
                state["source"] = "alpaca" # Define a origem como alpaca
                return evaluate_safety(state) # Verifica a segurança com esses dados

            update_state(mutate) # Aplica o lock e salva no redis

        except Exception as e: # Se tiver erro
            logger.error(f"Erro Alpaca fallback: {e}") # Registra o erro 

        await asyncio.sleep(2) # Espera 2 segundos antes de começar novamente

''' API '''

app = FastAPI(title="Observatory Sequencer") # Título do app

@app.on_event("startup") # Função para rodar quando o API iniciar 
async def startup(): # Função assíncrona startup
    start_mqtt() # inicia o cliente MQTT
    asyncio.create_task(alpaca_fallback()) # Inicia as tarefas assíncronas do fallback

@app.on_event("shutdown") # Função para quando o API estiver encerrando
async def shutdown(): # Define a função assíncrona shutdown
    stop_mqtt() # Para o cliente MQTT

@app.get("/health") # Cria o endpoint da saúde
def health(): # Função que responde essa rota
    with STATE_LOCK: # Entra no lock para ler a segurança
        return load_state() # Retorna o estado completo

@app.get("/telemetry") # Cria o endpoint para a telemetria 
def telemetry(): # Função para a rota
    with STATE_LOCK: # Entra o lock
        return load_state().get("telemetry", {}) # Retorna apenas o mapa da telemetria

@app.post("/camera/expose/{seconds}") # Cria endpoints POST 
def expose(seconds: float): # Função que recebe seconds como um número
    with STATE_LOCK: # Entra no lock
        state = load_state() # Carrega o estado atual 
    if state.get("weather_lock"): # Verifica se está em bloqueio 
        raise HTTPException(403, "Bloqueado por segurança climática") # Se tiver bloqueiro retorna erro 
    return alpaca_put( # Envia comando para o alpaca
        "/api/v1/camera/0/startexposure", # Rota para começar a exposição
        data={"Duration": seconds, "Light": True}, # Envia a duração e a luz
        timeout=5 # Tempo de espera
    ).json() # Retorna a resposta JSON do alpaca

@app.post("/dome/close") # Fechar o domo manualmente -> Cria endpoit POST 
def api_close_dome(): # Função da rota 
    return update_state(lambda state: close_dome(state, reason="manual_api")) # Chama a função update_state

@app.post("/dome/open") # Abrir o domo manualmente -> Cria endpoit POST 
def api_open_dome(): # Define a função da rota 
    def mutate(state: Dict[str, Any]) -> Dict[str, Any]: # Define função para mudar o estado
        if state.get("weather_lock"): # Verifica se está em lock
            raise HTTPException(403, "Bloqueado por segurança climática") # Impede a abertura e retorna erro
        return open_dome(state, reason="manual_api") # Se não tem bloqueio chama a função open_dome

    return update_state(mutate) # Aplica a alteração, salva no redis e retorna o estado atualizado
