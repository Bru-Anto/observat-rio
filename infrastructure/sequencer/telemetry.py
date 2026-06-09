''' Código da Telemetria
 Ele é responsável por aceitar telemetrias com nomes diferentes e tentar descobrir qual campo do estado do observatório elas representam.
 Ele pega os JSON MQTT extrai os nomes possíveis, extrai valores, resolve aliases, converte tipos, aplica estado e preserva a telemetria genérica.
'''

''' Bibliotecas '''
import re # Expressões regulares
from typing import Any, Dict, List, Optional, Tuple # Tipos para anotações

''' Chaves de valor '''

VALUE_KEYS = ("Value", "value", "VALUE") # Variações para o campo de valor principal 

# Chaves para o payload
NAME_KEYS = (
    "name",
    "measurement",
    "metric",
    "model",
    "model_name",
    "field",
    "sensor",
    "property",
)

#  Chaves para dentro de tags
TAG_NAME_KEYS = (
    "name",
    "measurement",
    "metric",
    "model",
    "model_name",
    "field",
    "sensor",
    "property",
    "device",
)

# Campos que devem ser ignorados
METADATA_FIELD_NAMES = {
    "clienttransactionid",
    "servertransactionid",
    "errornumber",
    "errormessage",
    "timestamp",
    "time",
}

# Campos de telemetria
TELEMETRY_FIELDS: Dict[str, Dict[str, Any]] = {

    # Vento
    "wind_speed": {
        "type": "float",
        "aliases": (
            "wind",
            "windspeed",
            "wind_speed",
            "wind-speed",
            "wind speed",
            "observingconditions.windspeed",
            "weather.wind",
            "weather.windspeed",
        ),
    },

    # Taxa de chuva
    "rain_rate": {
        "type": "float",
        "aliases": (
            "rain",
            "rainrate",
            "rain_rate",
            "rain-rate",
            "rain rate",
            "observingconditions.rainrate",
            "weather.rain",
        ),
    },

    # Umidade
    "humidity": {
        "type": "float",
        "aliases": (
            "humidity",
            "relativehumidity",
            "relative_humidity",
            "observingconditions.humidity",
            "weather.humidity",
        ),
    },

    # Cobertura de nuvens
    "cloud_cover": {
        "type": "float",
        "aliases": (
            "cloudcover",
            "cloud_cover",
            "cloud-cover",
            "cloud cover",
            "observingconditions.cloudcover",
            "weather.cloudcover",
        ),
    },

    # Temperatura do céu
    "sky_temperature": {
        "type": "float",
        "aliases": (
            "skytemperature",
            "sky_temperature",
            "sky-temperature",
            "sky temperature",
            "observingconditions.skytemperature",
            "weather.skytemperature",
        ),
    },

    # Temperatura do CCD
    "ccd_temperature": {
        "type": "float",
        "aliases": (
            "temperature",
            "ccdtemperature",
            "ccd_temperature",
            "ccd-temperature",
            "camera.temperature",
            "camera.ccdtemperature",
        ),
    },

    # Potência do cooler
    "cooler_power": {
        "type": "float",
        "aliases": (
            "coolerpower",
            "cooler_power",
            "cooler-power",
            "camera.coolerpower",
        ),
    },

    # Cooler ligado
    "cooler_on": {
        "type": "bool",
        "aliases": (
            "cooleron",
            "cooler_on",
            "cooler-on",
            "camera.cooleron",
        ),
    },

    # Estado da câmera
    "camera_state": {
        "type": "int",
        "aliases": (
            "camerastate",
            "camera_state",
            "camera-state",
            "camera.state",
            "camera.camerastate",
        ),
    },
    
    # Estado do shutter
    "dome_shutter_status": {
        "type": "int",
        "aliases": (
            "dome_shutterstatus",
            "domeshutterstatus",
            "dome_shutter_status",
            "shutterstatus",
            "shutter_status",
            "dome.shutterstatus",
        ),
    },

    # Azimute do domo
    "dome_azimuth": {
        "type": "float",
        "aliases": (
            "dome_azimuth",
            "domeazimuth",
            "azimuth",
            "dome.azimuth",
        ),
    },

    # Domo em movimento 
    "dome_slewing": {
        "type": "bool",
        "aliases": (
            "dome_slewing",
            "domeslewing",
            "slewing",
            "dome.slewing",
        ),
    },
}

# Campos metereológicos 
WEATHER_STATE_FIELDS = {
    "wind_speed",
    "rain_rate",
    "humidity",
    "cloud_cover",
    "sky_temperature",
}

''' Identificador '''

def normalize_identifier(value: Any) -> str: # Função que normalixa nomes 
    if value is None: # Se o valor é none 
        return "" # Retorna uma string vazia
    return "".join(ch for ch in str(value).lower() if ch.isalnum()) # Transforma em maiúsculo e mantém apenas eltras e números


def slug_identifier(value: Any) -> str: # Função para criar nome seguro
    if value is None: # Se não tiver valor
        return "unknown" # Retorna como unknown
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(value).strip().lower()).strip("_") # Substitui caracteres estranhos por _
    return slug or "unknown" # Se o resultado ficar vazio retorna como unknown


def _build_aliases() -> Dict[str, str]: # Função que cria mapa de alias para campo real
    aliases: Dict[str, str] = {} # Começa dicionário vazio
    for state_field, config in TELEMETRY_FIELDS.items(): # Percorre os campos conhecidos 
        aliases[normalize_identifier(state_field)] = state_field # Adiciona o próprio nome interno como alias
        for alias in config.get("aliases", ()): # Percorre os alises configurados 
            aliases[normalize_identifier(alias)] = state_field # Normaliza dos aliases e aponta o campo interno
    return aliases # Retorna o mapa de aliases

ALIAS_TO_STATE_FIELD = _build_aliases() # Mapa global de aliases

''' Funções de Normalização '''

def parse_value(value: Any) -> Any: # Função para interpretar um valor bruto -> Tenta transformar strings em tipos reais do python
    if value is None: # Se p valor for none
        return None # Retorna none
    if isinstance(value, bool): # Se já for booleano
        return value # Retorna como já está
    if isinstance(value, (int, float)): # Se já for inteiro ou float 
        return value # Retorna como já está 
    if isinstance(value, str): # Se for texto
        text = value.strip().lower() # Remove os espaços no começo e fim e transforma em minúsculo
        if text in ("true", "t", "yes", "y", "on", "1"): # Palavras para verdadeiro
            return True # Retorna true
        if text in ("false", "f", "no", "n", "off", "0"): # Palavras para falso 
             return False # Retorna false
        try: # Tenta converter o texto para decimal 
            return float(text) # Se conseguir retorna como float
        except ValueError: # Se não conseguir 
            return value # Retorna o original
    return value # Retorna como chegou


def to_float(value: Any, default: float = 0.0) -> float: # Função para conveter valor para float 
    try: 
        if value is None: # Se o valor é none 
            return default # Retorna o padrão
        if isinstance(value, bool): # Se for booleano
            return 1.0 if value else 0.0 # True vira 1.0 e false vira 0.0
        return float(value) # Tenta converter para decimal
    except Exception: # Se ocorrer algum erro
        return default # Retorna o padrão que é 0.0


def to_int(value: Any, default: int = 0) -> int: # Função para converter para inteiro 
    try:
        if value is None: # Se o valor é none 
            return default # Retorna o padrão
        if isinstance(value, bool): # Se for booleano
            return 1 if value else 0 # True vira 1 e false vira 0
        return int(float(value)) # Converte primeiro para float depois para int
    except Exception: # Se ocorrer algum erro
        return default # Retorna o padrão que é 0.0


def to_bool(value: Any, default: bool = False) -> bool: # Função para converter para booleano
    if value is None: # Se o valor é none 
        return default # Retorna o padrão
    if isinstance(value, bool): # Se for booleano
        return value # Retorna como está 
    if isinstance(value, (int, float)): # Se for um número
        return value != 0 # Retorna True se for 1 e False se for 0
    if isinstance(value, str): # Se é texto 
        text = value.strip().lower() # Normaliza o texto
        if text in ("true", "t", "yes", "y", "on", "1"): # Textos para verdadeiro 
            return True # Retorna true
        if text in ("false", "f", "no", "n", "off", "0"): # Textos para falso
            return False # Retorna false
    return default # Retorna o padrão que é 0.0


def convert_for_state_field(value: Any, state_field: Optional[str]) -> Any: # Função para converter valor com base no campo de destino
    parsed = parse_value(value) # Interpreta o valor bruto
    if not state_field: # Se não tem campo reconhecido 
        return parsed # Retorna o valor apenas interpretado

    field_type = TELEMETRY_FIELDS.get(state_field, {}).get("type") # Busca o tipo esperado do campo
    if field_type == "float": # Se o tipo é float 
        return to_float(parsed) # Converte para decimal 
    if field_type == "int": # Se o tipo é inteiro 
        return to_int(parsed) # Converte para inteiro 
    if field_type == "bool": # Se é booleano
        return to_bool(parsed) # Converte para booleano
    return parsed # Se não for reconhecido retorna o valor interpretado


def candidate_names_from_topic(topic: str) -> List[str]: # Função que tenta extrair nomes úteis pelo tópico MQTT
    parts = [part for part in (topic or "").split("/") if part] # Divide o tópico por / e remove as partes vazias 
    if not parts: # Se não tiver partes vazias 
        return [] # Retorna lista vazia

    candidates: List[str] = [] # Cria uma lista de candidatos
    lowered = [part.lower() for part in parts] # Cria versão minúscula das partes

    if "telemetry" in lowered: # Verifica se o tópico tem a palavra telemetria
        index = lowered.index("telemetry") # Pega a posição da palavra 
        tail = parts[index + 1 :] # Pega tudo que vem depois dela
        if tail: # Se há algo depois de telemetry
            candidates.extend((".".join(tail), "_".join(tail), tail[-1])) # Adiciona 3 formas candidatas, usando ponto, usando underline e usando elemento único

    candidates.append(parts[-1]) # Adiciona sempre a última parte do tópico 
    return _dedupe(candidates) # Remove duplicados


def candidate_names_from_payload(payload: Dict[str, Any], topic: str = "") -> List[str]: # Função que extrai os nomes do JSON da mensagem
    candidates: List[str] = [] # Começa lista vazia 

    for key in NAME_KEYS: # Percorre as chaves possíveis de nomes
        value = payload.get(key) # Pega o valor dessa chave no payload 
        if _is_scalar(value): # Verifica se o valor é simples
            candidates.append(str(value)) # Adicona como candidato

    tags = payload.get("tags") # Pega o campo tags
    if isinstance(tags, dict): # Se tags é um dicionário
        for key in TAG_NAME_KEYS: # Percorre chaves possíveis dentro de tags
            value = tags.get(key) # Pega o valor dentro de tags
            if _is_scalar(value): # Se o valor for simples 
                candidates.append(str(value)) # Adiciona como candidato 

    candidates.extend(candidate_names_from_topic(topic)) # Adiciona candidatos vindos do tópico MQTT
    return _dedupe(candidates) # Remove os duplicados 


def resolve_state_field(candidates: List[str]) -> Optional[str]: # Função que recebe candidatos e tenta achar o campo interno correspondente
    for candidate in candidates: # Percorre os candidatos em ordem 
        state_field = ALIAS_TO_STATE_FIELD.get(normalize_identifier(candidate)) # Normaliza os candidatos e procura no mapa de aliases
        if state_field: # Caso tenha encontrado um campo
            return state_field # Retorna imediatamente
    return None # Se não retorna none 


def extract_field_values(payload: Dict[str, Any]) -> List[Tuple[Optional[str], Any]]: # Função que extrai pares do JSON
    fields = payload.get("fields") # Pega do fields

    if isinstance(fields, dict): # Se existe e é dicionário
        for key in VALUE_KEYS: # Percorre a chave de value
            if key in fields: # Se encontrou alguma dessas chaves 
                return [(None, fields[key])] # Retorna uma lista única com o nome none

        items: List[Tuple[Optional[str], Any]] = [] # Cria lista de itens 
        for key, value in fields.items(): # Percorre cada campo no fields
            if normalize_identifier(key) in METADATA_FIELD_NAMES: # Se for matadatado
                continue # Ignora
            if _is_scalar(value): # Se é valor simples
                items.append((str(key), value)) # Adiciona (nome, valor)
        return items # Retorna os campos extraídos 

    for key in VALUE_KEYS: # Percorre as chaves de value
        if key in payload: # Se existe alguma chave no payload
            return [(None, payload[key])] # Retorna o valor

    items = [] # Cria lista vazia 
    for key, value in payload.items(): # Percorre todas as chaves dentro do payload 
        if key in NAME_KEYS or key in ("tags", "timestamp", "time"): # Ignora os campos de nomes ou de matadados
            continue # Pula 
        if normalize_identifier(key) in METADATA_FIELD_NAMES: # Ignora metadados conhecidos 
            continue # Pula 
        if _is_scalar(value): # Se é valor simples
            items.append((str(key), value)) # Adiciona a lista 
    return items 


''' Leituras'''

def extract_telemetry_readings(payload: Dict[str, Any], topic: str = "") -> List[Dict[str, Any]]: # Função principal para a extração -> Recebe o JSON e o tópico onde a mensagem chegou
    if not isinstance(payload, dict): # Verifica se o payload é um dicionário
        return [] # Se não for retorna uma lista vazia

    base_candidates = candidate_names_from_payload(payload, topic) # Extrai nomes candidatos pelo payload e pelo tópico MQTT
    readings: List[Dict[str, Any]] = [] # Cria lista vazia onde as leituras normalizadas serão guardadas 

    for field_name, raw_value in extract_field_values(payload): # Percorre os valores extraídos do payload
        candidates = _dedupe(([field_name] if field_name else []) + base_candidates) # Monta a lista final de candidatos
        state_field = resolve_state_field(candidates) # Tenta descobrir o campo interno
        source_name = field_name or (base_candidates[0] if base_candidates else topic) or "unknown" # Define o nome de origem 

        readings.append( # Adiciona a leitura normalizada
            {
                "name": source_name, # Guarda o nome original 
                "state_field": state_field, # Gaurda o campo interno reconhecido 
                "value": convert_for_state_field(raw_value, state_field), # Guarda o valor convertido
                "raw_value": raw_value, # Guarda o valor original 
                "candidates": candidates, # Guarda os nomes candidatos 
            }
        )

    return readings # Retorna todas as leituras extraídas


def apply_telemetry_readings( # Função que aplica as leituras ao estado 
    state: Dict[str, Any], # Recebe o estado atual 
    readings: List[Dict[str, Any]], # Recebe as leituras extraídas
    topic: str, # Recebe o tópico MQTT
    updated_at: str, # Recebe o timestamp a atualização
    source: str = "mqtt", # Recebe a origem 
) -> Tuple[Dict[str, Any], int]: # Retorna o estado atualizado e a quantidade de campos mapeados
    if not readings: # Se não tem leituras
        return state, 0 # Retorna o estado sem mudanças

    telemetry = state.setdefault("telemetry", {}) # Garante que o estado tenha o dicionário telemetry
    mapped = 0 # Contador de leituras que são reconhecidas como campos operacionais 
    weather_mapped = 0 # Contador específico para leituras metereológicas 

    for reading in readings: # Percorre cada leitura
        state_field = reading.get("state_field") # Campo interno reconhecido
        value = reading.get("value") # Pega o valor convertido

        if state_field: # Se a leitura for reconhecida
            state[state_field] = value # Atualiza o campo 
            mapped += 1 # Incrementa o contador
            if state_field in WEATHER_STATE_FIELDS: # Se for campo metereológico 
                weather_mapped += 1 # Incrementa o contador metereológico

        telemetry_key = slug_identifier(reading.get("name") or state_field or topic) # Cria uma chave segura para guardar a leitura o mapa telemetry 
        telemetry[telemetry_key] = { # Salva a leitura no mapa de telemetria 
            "value": value, # Valor convertido
            "state_field": state_field, # Campo interno reconhecido
            "topic": topic, # Tópico MQTT
            "updated_at": updated_at, # Horário da atualização 
            "candidates": reading.get("candidates", [])[:8], # Lista os 8 primeiros candidatos
        }

    state["last_update"] = updated_at # Atuliza o timestamp
    state["source"] = source # Marca a origem da atualização
    if mapped > 0: # Se for identificada pelo menos uma leitura
        state["last_mapped_update"] = updated_at # Atualiza o last_mapped_update
    if weather_mapped > 0: # Se pelo menos uma leitura metereológica foi reconhecida 
        state["last_weather_update"] = updated_at # last_weather_update
    return state, mapped # Retorna novo estado e a quantidade de mapeamentos 


def _is_scalar(value: Any) -> bool: # Função auxiliar 
    return value is None or isinstance(value, (str, int, float, bool)) # Retorna true se o valor é simples 

''' Dupliacados'''

def _dedupe(values: List[Any]) -> List[str]: # Função para remover os duplicados preservando a ordem 
    result: List[str] = [] # Lista final
    seen = set() # Valores já vistos
    for value in values: # Percorre os valores já recebidos 
        if value is None: # Ignora o none
            continue
        text = str(value).strip() # Transforma em texto e remove espaços 
        if not text: # Se o texto ficou vazio
            continue # Pula
        key = text.lower() # Cria chave para comparar duplicados 
        if key in seen: # Se já apareceu 
            continue # Pula 
        seen.add(key) # Marca como visto
        result.append(text) # Adiciona a lista final 
    return result # Retorna a lista de duplicados 
